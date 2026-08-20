# -*- coding: utf-8 -*-
"""Command line: answerable <domain> [options]."""
import argparse
import json
import os
import sys

from . import bank as banks
from .audit import audit
from .score import ANSWERED, MISSING


# Console encoding is not a cosmetic problem here. A cp1252 terminal cannot
# print "·" and, worse, cannot print the pound signs and dashes that turn up in
# evidence lines quoted straight off a British website, so an unguarded print
# kills the run at the last step after the crawl has already been paid for.
def _utf8_stdout():
    enc = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    return enc in ("utf8", "utf8sig", "cp65001")


# A middle dot only where the terminal is definitely UTF-8. It exists in most
# Windows code pages too, but at a different byte, and a report that renders as
# rubbish on somebody else's machine is worse than one that uses a pipe.
SEP = " · " if _utf8_stdout() else " | "


def _wrap(items, indent=16, width=78):
    """Pack keys onto lines without letting a separator start one.

    textwrap breaks on spaces, so " | " between two long keys leaves a lone
    pipe hanging at the front of the next line. Packing by hand is shorter than
    explaining that to textwrap.
    """
    lines, cur, room = [], "", width - indent
    for i, item in enumerate(items):
        piece = item + (SEP if i < len(items) - 1 else "")
        if cur and len(cur) + len(piece) > room:
            lines.append(cur.rstrip().rstrip("|·").rstrip())
            cur = ""
        cur += piece
    if cur:
        lines.append(cur.rstrip().rstrip("|·").rstrip())
    return ("\n" + " " * indent).join(lines)


def report(result, show_evidence=False):
    out = []
    name = result["domain"]
    s = result["summary"]

    if not result["reachable"]:
        out.append(name)
        out.append("")
        # No score. Saying nought out of twenty here would be a claim about the
        # business when the only fact available is about our access to it.
        out.append("  NOT READ    %s" % result["why"])
        if result["pages_read"]:
            out.append("  tried       %s" % result["pages_read"][0])
        return "\n".join(out)

    head = "%d of %d answered" % (s["answered"], s["total"])
    out.append("%s%s%s" % (name, " " * max(2, 62 - len(name) - len(head)), head))
    out.append("")

    answered = [v for v in result["verdicts"] if v["status"] == ANSWERED]
    missing = [v for v in result["verdicts"] if v["status"] == MISSING]

    if answered:
        out.append("  ANSWERED      " + _wrap([v["key"] for v in answered]))
    if missing:
        out.append("  NOT ANSWERED  " + _wrap([v["key"] for v in missing]))
    out.append("")

    if missing:
        out.append("  A customer cannot find out:")
        for v in missing:
            note = "  (%s)" % v["why"] if v["why"] else ""
            out.append("    - %s%s" % (v["question"], note))
        out.append("")

    if show_evidence and answered:
        out.append("  Evidence:")
        for v in answered:
            ev = v["evidence"] or "(matched)"
            out.append("    %-14s %s" % (v["key"], ev[:90]))
        out.append("")

    # Showing the crawl is what stops this being a black box, and it is the
    # first thing anyone sceptical of the score checks.
    out.append("  Pages read (%d):" % len(result["pages_read"]))
    for u in result["pages_read"]:
        out.append("    %s" % u)
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="answerable",
        description="Check what a customer can actually find out from a website.")
    p.add_argument("domain", nargs="?", help="e.g. example.co.uk")
    p.add_argument("--bank", default="default",
                   help="a shipped bank name, or a path to your own .yml "
                        "(default: default)")
    p.add_argument("--list-banks", action="store_true")
    p.add_argument("--pages", type=int, default=12,
                   help="max pages to fetch (default: 12)")
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--model", action="store_true",
                   help="use OpenRouter for questions the patterns cannot "
                        "settle (needs OPENROUTER_API_KEY)")
    p.add_argument("--model-name", default=None)
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--evidence", action="store_true",
                   help="show the line that answered each question")
    a = p.parse_args(argv)

    # Replace rather than raise: a character the terminal cannot show is not a
    # reason to lose the report.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    if a.list_banks:
        for b in banks.available():
            bank = banks.load(b)
            print("%-12s %-28s %d questions"
                  % (b, bank.get("name", ""), len(bank["questions"])))
        return 0

    if not a.domain:
        p.error("a domain is required")

    checker = None
    if a.model:
        from .llm import checker as make_checker, DEFAULT_MODEL
        if not os.environ.get("OPENROUTER_API_KEY"):
            print("OPENROUTER_API_KEY is not set; running patterns only",
                  file=sys.stderr)
        else:
            checker = make_checker(model=a.model_name or DEFAULT_MODEL)

    result = audit(a.domain, bank=a.bank, model=checker,
                   max_pages=a.pages, timeout=a.timeout)

    if a.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(report(result, show_evidence=a.evidence))

    # Exit codes are for scripts. 0 read it, 1 could not, 2 read it and found
    # gaps, so a CI job can fail a build on an unanswerable site.
    if not result["reachable"]:
        return 1
    return 2 if result["summary"]["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
