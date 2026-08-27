# answerable

Check what a customer can actually find out from a website.

Give it a domain. It reads the site the way a stranger would, then reports which
of the questions people actually ask are answered on the page and which are not.

```
$ answerable example-dental.co.uk --bank dental

example-dental.co.uk                          9 of 20 answered

  ANSWERED      phone · address · nhs_private · prices · emergency
                treatments · payment_plans · payment_methods · team
  NOT ANSWERED  hours · new_patients · nhs_availability
                emergency_same_day · registration · cancellation · nervous
                children · parking · access · booking

  A customer cannot find out:
    - When are you open?
    - Are you taking new patients?
    - Do you have NHS places available?
    - Can I be seen the same day?
    - How do I register?
    - What happens if I cancel or miss an appointment?
    - What if I am nervous about the dentist?
    - Do you see children?
    - Where do I park?
    - Can I get in with a wheelchair or a pushchair?
    - How do I book?

  Pages read (3):
    https://example-dental.co.uk
    https://example-dental.co.uk/contact
    https://example-dental.co.uk/about
```

## Why

The same question decides two different things.

A person deciding whether to phone a business is looking for two or three
specific facts, and the most common ones are missing far more often than site
owners expect. Prices, whether you are taking new customers, and what happens
outside working hours are the usual holes.

An answer engine reading the same page is doing the same job with the same
material. If the site does not state a fact, nothing downstream can state it
either, and the business does not get cited.

This tool measures that, per question, with the evidence shown.

## Install

```bash
pip install .
```

One dependency, PyYAML, because the question banks are YAML. The crawler is
`urllib` and the scorer is `re`.

## Use

```bash
answerable example.co.uk                      # the general bank
answerable example.co.uk --bank legal         # a vertical
answerable example.co.uk --bank ./mine.yml    # your own questions
answerable example.co.uk --evidence           # show the line that answered each
answerable example.co.uk --json               # machine readable
answerable --list-banks
```

Exit codes are for scripts: `0` the site was read and answered everything, `1`
the site could not be read, `2` the site was read and has gaps. A CI job can
fail a build on an unanswerable page.

From Python:

```python
from answerable import audit

result = audit("example.co.uk", bank="dental")
print(result["summary"]["missing_keys"])
```

## The three verdicts

`ANSWERED`, `MISSING`, and `UNREADABLE`.

The third one is the reason this is not a two-state tool. Some sites are behind
a WAF that answers 403 to anything not shaped like a browser, and some simply do
not respond. Scoring those zero out of twenty would be a statement about those
businesses when the only fact available is a statement about our access to them.
When a site cannot be read, `summary["score"]` is `None`, not `0`.

How often does it happen? On a clean run over 972 UK law firm sites, 937 were
read and 35 were not. Under 4 per cent.

That number is worth the space it takes, because an earlier run of the same tool
over the same kind of list reported 27 per cent, and almost all of it was this
tool's fault rather than theirs. A default Python user agent, no NAT64 handling
and a guard that refused a host if any of its DNS records looked unusual will
between them report that a quarter of the legal profession has no website. Every
one of those faults failed towards "their site is broken" rather than "our
crawler is". If this verdict starts looking common, suspect the crawler first.

## Question banks

The banks are the opinionated part, so they are plain YAML in
[`answerable/banks/`](answerable/banks) rather than code. Read them, disagree,
send a better one.

```yaml
- key: new_patients
  question: Are you taking new patients?
  # "patients" alone is on every dental page ever written. The question is
  # settled only by a statement about accepting them, or a waiting list.
  pattern: '\b(new patients? (are )?(welcome|accepted)|not (currently )?(accepting|taking) new patients|waiting list)\b'
```

Shipped: `default`, `dental`, `legal`, `veterinary`, `consultancy`.

Pick the one that matches the trade, because the wrong bank produces a
confidently wrong result rather than no result. Scoring a remote consultancy
against the general bank marks it down for not saying where to park.

Each question needs a `pattern`. The one exception is `kind: hours`, which is
settled by a dedicated extractor instead, because opening hours are structural
rather than prose and a keyword match finds the word "hours" inside "24 hours a
day" on a page that never states any.

## The optional model pass

Patterns settle most questions and cost nothing. For the rest, an OpenRouter
call can read an extract and say whether it contains an answer:

```bash
export OPENROUTER_API_KEY=...
answerable example.co.uk --bank dental --model
```

It is a reader, not a knower. It is only ever shown text and asked whether that
text settles the question, never asked what a business does, because a model
asked to recall will invent. It only sees questions the patterns could not
settle, so a run does not pay twice for a settled answer. If the call fails, the
question stays `MISSING` with a note that the check was unavailable, which is
different from a confirmed no.

The tool works without a key. That is deliberate.

## What it does not do

- It does not render JavaScript. A site that ships an empty shell and paints the
  content client side will under-report.
- It reads up to 12 pages from a fixed list of common paths. It does not follow
  the sitemap or crawl the whole site.
- It does not judge whether an answer is good, only whether one is present.
- It has no opinion about design, speed, or rankings.

## If you host it

The crawler accepts arbitrary input, which makes it a proxy and an
amplification vector unless it is fenced. This repo blocks private, loopback,
link local and reserved address ranges, refuses anything that is not http or
https, caps redirects and response size, and caps pages per run.

That is the inside of the process. Anything public also needs per-IP and
per-domain rate limits, a cache keyed by domain so the same site audited twice
in a day costs one crawl, and a filter on visitor-supplied text. `llm.is_safe()`
wires up a content safety classifier for the last of those.

## The traps, and why they are in the code

Most of the rules in `extract.py` exist because their absence produced a
specific wrong answer while building an agent that read business websites and
spoke to callers on their behalf.

- **Reviews read exactly like policy.** They are fluent English about the
  business and therefore invisible to every other filter. One run captured "I
  moved over to Quality Dental after having a bad experience with Worthing
  Dental" as a practice emergency policy.
- **Biographies are not policy.** "Since qualifying, he has worked in both NHS
  and private practices" is a career history, and reading it as an answer to
  "do you take NHS patients" is a confident wrong answer.
- **Opening hours live in tables.** Breaking on `</td>` puts the day and the
  time on separate lines, so a pattern needing both matches neither.
- **Day stems have to reach their full spelling.** `wed(?:day|s)?` never matches
  "Wednesday" and `sat(?:day|s)?` never matches "Saturday". Two sites had
  exactly those rows dropped, which would have reported a business as shut on a
  day it opens.
- **Word boundaries at both ends**, or "mon" matches inside "Monument" and
  "testimonials".

The test suite is those bugs, one test each.

```bash
python -m unittest discover -s tests
```

## Licence

MIT.

Built by [Product Consult](https://productconsult.com), who make tailored
software for UK businesses. The hosted version of this, with curated banks and
a report you can send to someone, lives there.
