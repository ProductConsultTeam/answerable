# -*- coding: utf-8 -*-
"""Crawl a site, score it, report what a customer could not find out."""
import time

from . import bank as banks, fetch, score as scoring
from .extract import clean_lines, opening_hours

# Where small business websites actually put things. Ordered roughly by how
# often each path exists, because the page budget runs out before the list
# does and the early ones should be the ones that pay.
PATHS = (
    "/contact", "/contact-us", "/about", "/about-us", "/services",
    "/opening-hours", "/opening-times", "/prices", "/pricing", "/fees",
    "/faq", "/faqs", "/team", "/our-team", "/book", "/appointments",
    "/new-patients", "/treatments", "/find-us", "/parking",
)


def crawl(domain, max_pages=12, timeout=15):
    """Fetch a site and reduce it to the lines the business itself wrote."""
    started = time.time()
    try:
        base, pages = fetch.get_site(domain, PATHS, timeout=timeout,
                                     max_pages=max_pages)
    except fetch.Unresolved:
        # Says nothing about the site. Worth retrying before it is reported.
        return {"domain": domain, "reachable": False,
                "why": "the domain did not resolve, which is usually the "
                       "network doing the asking rather than the site",
                "retryable": True,
                "pages_read": [], "lines": [], "hours": []}
    except fetch.Blocked as e:
        return {"domain": domain, "reachable": False, "why": str(e),
                "pages_read": [], "lines": [], "hours": []}

    if not base:
        # Deliberately specific. This is a statement about our access, not
        # about the business, and the report has to be able to say so.
        return {"domain": domain, "reachable": False,
                "why": "no response over https, www or http; the site may "
                       "block automated access",
                "pages_read": [], "lines": [], "hours": []}

    lines, hours, read = [], [], []
    for path, doc in pages.items():
        read.append(base + path)
        lines.extend(clean_lines(doc))
        hours.extend(opening_hours(doc))

    joined = " ".join(lines)
    if fetch.looks_parked(joined):
        return {"domain": domain, "reachable": False,
                "why": "the domain serves a parking or holding page",
                "pages_read": read, "lines": [], "hours": []}

    seen = set()
    unique = []
    for l in lines:
        if l not in seen:
            seen.add(l)
            unique.append(l)

    return {"domain": domain, "base": base, "reachable": True, "why": "",
            "pages_read": read, "lines": unique,
            "hours": list(dict.fromkeys(hours)),
            "took_ms": int((time.time() - started) * 1000)}


def audit(domain, bank="default", model=None, max_pages=12, timeout=15):
    """Full run: crawl, score, summarise.

    `model` is an optional callable(question, extract) -> bool. Without one the
    audit still works: the patterns settle most questions, and a tool that
    needs an API key to run at all is a tool most people never try.
    """
    b = banks.load(bank) if isinstance(bank, str) else bank
    site = crawl(domain, max_pages=max_pages, timeout=timeout)
    verdicts = scoring.score(site, b, model=model)
    return {
        "domain": domain,
        "bank": b.get("name", bank if isinstance(bank, str) else "custom"),
        "reachable": site["reachable"],
        "why": site["why"],
        # Listing what was actually read is what stops the result being a black
        # box, and it is the first thing a sceptical reader checks.
        "pages_read": site["pages_read"],
        "hours": site["hours"],
        "summary": scoring.summarise(verdicts),
        "verdicts": [v.as_dict() for v in verdicts],
    }
