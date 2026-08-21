# -*- coding: utf-8 -*-
"""HTML to text that is safe to reason about.

Every rule in this file is here because its absence produced a specific wrong
answer while building an AI receptionist that read practice websites and spoke
to callers on their behalf. They are not stylistic.

The one that matters most is REVIEW. Customer testimonials are the single
biggest pollutant on a small business website and the most dangerous, because
they read as fluent English about the business and are therefore invisible to
every other filter. One extraction run captured "I moved over to Quality Dental
after having a bad experience with Worthing Dental" as a practice's emergency
policy, which would have had an agent badmouthing a named competitor to a
caller. "Free parking as well brilliant" is an ordinary sentence that happens
to have been written by a customer rather than by the business.

A page says two kinds of thing: what the business states about itself, and what
other people say about it. Only the first can be quoted back as fact.
"""
import html
import re

# Comments first. The tail of an HTML comment survives tag stripping and
# arrives looking like a line of content, which is how "-->" ended up in a
# list of dental treatments.
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_DROP = re.compile(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>")

# Table cells collapse to a separator rather than a line break. Opening hours
# are usually <tr><td>Monday</td><td>9:00 - 17:00</td></tr>, and breaking on
# </td> puts the day and the time on separate lines, so a pattern needing both
# matches neither.
_CELL = re.compile(r"(?i)</t[dh]>")
_BLOCK = re.compile(r"(?i)<(br|/p|/li|/tr|/h[1-6]|/div|/section)[^>]*>")
_TAG = re.compile(r"<[^>]+>")

# Every stem must reach its own full spelling. "wed" + "day" is not
# "Wednesday" and "sat" + "day" is not "Saturday": an earlier version dropped
# exactly those two rows out of otherwise complete opening hours, which would
# have told a caller the business was shut on a day it opens. Word boundaries
# at both ends, or "mon" matches inside "Monument" and "testimonials".
DAY = r"\b(?:mon|tues?|wed(?:nes)?|thur?s?|fri|sat(?:ur)?|sun)(?:day)?s?\b"
TIME = r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)?"
HOURS_LINE = re.compile(
    r"%s(?:\s*(?:-|–|to|&|,)\s*%s)*\s*[:\-–·|]?\s*(?:%s\s*(?:-|–|to|until|til)\s*%s|closed)"
    % (DAY, DAY, TIME, TIME), re.I)

# Somebody else talking about the business. Never quotable as the business.
REVIEW = re.compile(
    r"(\bread more\b|\d{1,2}:\d{2}\s+\d{1,2}\s+\w{3}\s+\d{2}|"
    r"\b(would |highly |i'?d )?recommend\b|\bfriendly staff\b|\bthank you\b|"
    r"\bgreat (experience|service|treatment)\b|"
    r"\bvery (thorough|friendly|professional|happy)\b|"
    r"\bmoved over\b|\bbad experience\b|\bused to go\b|\bmy first choice\b|"
    r"\b\d(\.\d)? ?(stars?|out of 5)\b|\bverified (review|patient|customer)\b|"
    r"^\s*(i|my|we were|they (were|provided))\b)", re.I)

# One person's career, not the business's policy. "Since qualifying, he has
# worked in both NHS and private practices" is a biography, and reading it as
# an answer to "do you take NHS patients" is a confident wrong answer.
BIO = re.compile(
    r"(^\s*(he|she|I)\b|\bI (see|offer|provide|currently|enjoy|have been)\b|"
    r"\b(since qualifying|graduated|qualified (in|from|at)|his career|"
    r"her career|he (has|is|provides|offers|works|treats)|"
    r"she (has|is|provides|offers|works|treats)|completed (his|her)|"
    r"trained at|"
    # "Philippa joined the Goddard Group in 1999" is a staff biography, and the
    # earlier list only knew "joined the practice". A bio that happens to name
    # the firm is still a bio, and this one was being quoted as the answer to
    # which animals a veterinary group treats.
    r"joined (us|the (practice|team|firm|group|partnership)|"
    r"the [a-z][a-z-]+ (group|practice|partnership|team|firm))|"
    r"(has|have) (been )?(worked|practised|practiced|specialised|specialized) "
    r"(at|in|with)))", re.I)

# Post-nominals. One on a line is usually the business talking ("all our vets
# are MRCVS registered"); two or more is a named individual's qualifications,
# which is a biography by another route. "John Kidman BVSc MANZCVS(Small Animal
# Dentistry) MRCVS" was quoted as the answer to which animals a practice
# treats, because the credential contained the words "Small Animal".
QUAL = re.compile(
    r"\b(mrcvs|bvsc|bvetmed|bvm&s|certavp|manzcvs|bds|gdc|llb|llm|tep|"
    r"fcilex|cilex|mrics|aca|acca)\b", re.I)


def is_credentials(line):
    """Two or more post-nominals on one line is somebody's qualifications.

    Word boundaries matter more here than anywhere else in this file. Without
    them "tep" matches inside "stepped" and "aca" inside "vacant", and every
    other sentence on the site becomes a credential string.
    """
    return len(QUAL.findall(line)) >= 2


# Text decoded with the wrong codec. Reading it aloud produces noise, and
# quoting it in a report makes the report look broken.
MOJIBAKE = re.compile(r"[âÂ]€|Ã[©¨¶±]|�")

# Navigation, calls to action and page furniture. Read back to somebody as a
# list of services these are humiliating: "we offer Home, About Us, and
# Cambridgeshire".
NAV = re.compile(
    r"^(home|about( us)?|contact( us)?|blog|news|team|our team|meet the team|"
    r"menu|search|book( a| an| now| online)?|find (us|your [a-z]+)|"
    r"our (practices|offices|branches)|locations?|careers|jobs|privacy|"
    r"cookies|terms|sitemap|reviews|testimonials|gallery|faqs?|prices?|fees|"
    r"pricing|register|login|call us|get in touch|enquire|more|read more|"
    r"next|previous|skip to (main )?content|toggle|close|open|trustpilot|"
    r"google|facebook|instagram|linkedin|twitter|offers?|information)\b", re.I)


def to_lines(doc):
    """Block-level text split, with table rows kept whole."""
    h = _DROP.sub(" ", doc or "")
    h = _COMMENT.sub(" ", h)
    h = _CELL.sub(" · ", h)
    h = _BLOCK.sub("\n", h)
    out = []
    for line in _TAG.sub(" ", h).split("\n"):
        # Unescape before matching, not after: "Saturday &amp; Sunday" is
        # otherwise spoken and printed as "Saturday amp Sunday".
        line = re.sub(r"\s+", " ", html.unescape(line)).strip(" ·\t")
        if line:
            out.append(line)
    return out


def to_text(doc):
    return " ".join(to_lines(doc))


def sentences(text, lo=25, hi=260):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text)
            if lo <= len(s.strip()) <= hi]


def is_own_voice(line):
    """Can this line be quoted back as something the business states?

    False for customer reviews, individual biographies and mis-decoded text.
    The test is not whether a line is positive or relevant; it is whether the
    business is the one saying it.
    """
    return not (REVIEW.search(line) or BIO.search(line)
                or MOJIBAKE.search(line) or is_credentials(line))


def clean_lines(doc):
    """Lines the business itself wrote, with furniture removed."""
    return [l for l in to_lines(doc) if is_own_voice(l) and not NAV.match(l)]


def opening_hours(doc):
    """Verbatim opening-hours lines, or an empty list.

    Verbatim on purpose. A parser has to guess at "Mon-Thu 8.30am til 5, Fri
    closes 4" and will then be confidently wrong, where a human or a language
    model reads it correctly. Store what the business wrote.
    """
    found = []
    for line in to_lines(doc):
        if len(line) < 120 and HOURS_LINE.search(line) and is_own_voice(line):
            if line not in found:
                found.append(line)
    return found[:12]
