# -*- coding: utf-8 -*-
"""Loading question banks.

A bank is the opinionated part of this tool and the part worth arguing about,
so it lives in YAML rather than in code: anyone can read it, disagree with it,
and send a better one.

Each question carries a regex that decides it cheaply. Writing those patterns
is where the judgement is. "Do you take new patients" is not answered by a page
containing the word "patients"; it is answered by a page that says new patients
are welcome, or that there is a waiting list.
"""
import os
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
BANKS = os.path.join(HERE, "banks")


def available():
    return sorted(f[:-4] for f in os.listdir(BANKS) if f.endswith(".yml"))


def _resolve(name):
    """A shipped bank name, or a path to somebody else's file.

    Accepting a path matters more than it looks: the banks are the arguable
    part, and a person who disagrees with one should be able to run their own
    version without forking anything or installing it.
    """
    if name.endswith((".yml", ".yaml")) or os.sep in name or "/" in name:
        if os.path.exists(name):
            return name
        raise SystemExit("no such bank file: %s" % name)
    path = os.path.join(BANKS, name + ".yml")
    if not os.path.exists(path):
        raise SystemExit("no bank %r. available: %s"
                         % (name, ", ".join(available())))
    return path


def load(name):
    path = _resolve(name)
    with open(path, encoding="utf-8") as f:
        bank = yaml.safe_load(f)

    if not isinstance(bank, dict) or not bank.get("questions"):
        raise SystemExit("%s has no questions" % path)

    seen = set()
    for q in bank["questions"]:
        for field in ("key", "question"):
            if not q.get(field):
                raise SystemExit("question missing %s in %s" % (field, path))
        if q["key"] in seen:
            raise SystemExit("duplicate key %r in %s" % (q["key"], path))
        seen.add(q["key"])
        # Only the hours question is allowed to have no pattern, because it is
        # settled by a dedicated extractor instead. Anything else without one
        # is unanswerable and would be reported as a gap on every site.
        if not q.get("pattern") and q.get("kind") != "hours":
            raise SystemExit("question %r needs a pattern or kind: hours"
                             % q["key"])
    return bank
