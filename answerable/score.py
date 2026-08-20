# -*- coding: utf-8 -*-
"""Deciding whether a site answers a question.

Two passes, cheapest first.

The regex pass is deterministic, free, and does most of the work: if a site
states its opening hours, the words are on the page and a pattern finds them.
It is deliberately the primary mechanism, because a language model asked "does
this site state its prices?" will cheerfully say yes about a page mentioning
the word "affordable".

The model pass is optional and only sees questions the patterns could not
settle. Its job is narrow: read a supplied extract and say whether it contains
an answer. It is never asked to recall anything, and it never sees a question
that has already been answered, because paying for a second opinion on a
settled question is how a free tool becomes an expensive one.

The verdicts are three, not two. "Unreadable" is a real outcome: 432 of the
1,606 law firm sites this came from, 27%, refused automated access even after a
retry with a browser user agent. Telling those businesses they answer nothing
would be a claim about them rather than a fact.
"""
import re

ANSWERED = "answered"
MISSING = "missing"
UNREADABLE = "unreadable"


class Verdict(object):
    __slots__ = ("key", "question", "status", "evidence", "why")

    def __init__(self, key, question, status, evidence="", why=""):
        self.key = key
        self.question = question
        self.status = status
        self.evidence = evidence
        self.why = why

    def as_dict(self):
        return {"key": self.key, "question": self.question,
                "status": self.status, "evidence": self.evidence,
                "why": self.why}


def _match(pattern, lines):
    """First line the business itself wrote that satisfies the pattern."""
    rx = re.compile(pattern, re.I)
    for line in lines:
        if rx.search(line):
            return line
    return ""


def score(site, bank, model=None):
    """Score one crawled site against one question bank.

    `site` is a dict from crawl(): {"lines": [...], "hours": [...],
    "reachable": bool}. `bank` is the loaded YAML. `model` is an optional
    callable(question, extract) -> bool for the second pass.
    """
    if not site.get("reachable"):
        return [Verdict(q["key"], q["question"], UNREADABLE, why=site.get("why", ""))
                for q in bank["questions"]]

    lines = site.get("lines") or []
    verdicts = []
    unsettled = []

    for q in bank["questions"]:
        # Opening hours have their own extractor: they are structural rather
        # than prose, and a generic keyword match finds the word "hours" in
        # "24 hours a day" on a page that never states any.
        if q.get("kind") == "hours":
            hours = site.get("hours") or []
            verdicts.append(Verdict(
                q["key"], q["question"],
                ANSWERED if hours else MISSING,
                evidence=hours[0] if hours else ""))
            continue

        hit = _match(q["pattern"], lines) if q.get("pattern") else ""
        if hit:
            verdicts.append(Verdict(q["key"], q["question"], ANSWERED, evidence=hit))
        else:
            v = Verdict(q["key"], q["question"], MISSING)
            verdicts.append(v)
            unsettled.append(v)

    # Second pass, only over what the patterns could not settle, and only if a
    # model was supplied. A tool that works without an API key is a tool people
    # will actually run.
    if model and unsettled:
        extract = "\n".join(lines[:400])[:12000]
        for v in unsettled:
            try:
                if model(v.question, extract):
                    v.status = ANSWERED
                    v.why = "found by model, not by pattern"
            except Exception:
                # A model failure must not turn into a claim about the site.
                v.why = "pattern found nothing; model check unavailable"

    return verdicts


def summarise(verdicts):
    answered = [v for v in verdicts if v.status == ANSWERED]
    missing = [v for v in verdicts if v.status == MISSING]
    unreadable = [v for v in verdicts if v.status == UNREADABLE]
    total = len(verdicts)
    return {
        "total": total,
        "answered": len(answered),
        "missing": len(missing),
        "unreadable": len(unreadable),
        # A score is withheld rather than guessed when the site could not be
        # read. Zero out of twenty would be read as a judgement on the
        # business, and it is a judgement on our access to it.
        "score": None if unreadable else len(answered),
        "answered_keys": [v.key for v in answered],
        "missing_keys": [v.key for v in missing],
    }
