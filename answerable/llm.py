# -*- coding: utf-8 -*-
"""The optional second pass, over OpenRouter.

Two things live here and they are different jobs, easily confused.

`checker()` returns the callable score.score() takes: read this extract, does it
answer this question, yes or no. It is a reader, not a knower. It is never
asked what a business's opening hours are, only whether the text in front of it
states them, because a model asked to recall gladly invents.

`is_safe()` is a guardrail classifier, and it belongs on visitor input rather
than on site text. nvidia/nemotron-3.5-content-safety returns a safety verdict,
not prose: asking it a question returns an empty string. It is here for the
hosted version, where a stranger can type into a box.
"""
import json
import os
import re
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1/chat/completions"

# Free at the time of writing, and non-reasoning matters: the reasoning models
# on the free tier narrate ("User wants a one word answer...") and that leaks
# into the reply where a yes or no was expected.
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
SAFETY_MODEL = "nvidia/nemotron-3.5-content-safety"

SYSTEM = (
    "You decide whether a piece of website text answers a question. "
    "Reply with exactly one word: YES or NO. "
    "Answer YES only if the text states the answer. "
    "Do not answer from your own knowledge of the business. "
    "Do not infer. If the text merely mentions the topic without "
    "settling the question, answer NO."
)


class LLMError(Exception):
    pass


def _post(key, payload, timeout=45):
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://productconsult.com",
            "X-Title": "answerable",
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise LLMError("openrouter %s: %s" % (e.code, body))
    except (urllib.error.URLError, OSError) as e:
        raise LLMError("openrouter unreachable: %s" % e)


def ask(question, extract, key=None, model=DEFAULT_MODEL, timeout=45):
    """One YES/NO reading. Raises LLMError rather than guessing."""
    key = key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("no OPENROUTER_API_KEY set")

    data = _post(key, {
        "model": model,
        "temperature": 0,
        "max_tokens": 4,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                "QUESTION: %s\n\nWEBSITE TEXT:\n%s\n\nYES or NO?"
                % (question, extract)},
        ],
    }, timeout)

    try:
        reply = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("unexpected response shape: %s" % json.dumps(data)[:300])

    # Substring, not equality. Free models append punctuation, quote marks and
    # the occasional cheerful sentence however firmly the prompt says one word.
    return bool(re.search(r"\byes\b", (reply or ""), re.I))


def checker(key=None, model=DEFAULT_MODEL, timeout=45):
    """A callable(question, extract) -> bool for score.score().

    It raises on failure and score() catches, which is deliberate: a failed
    call must leave the question recorded as unconfirmed rather than answered,
    and a silent False here would be indistinguishable from a real "no".
    """
    def check(question, extract):
        return ask(question, extract, key=key, model=model, timeout=timeout)
    return check


def is_safe(text, key=None, timeout=20):
    """Guardrail for visitor-supplied text on any public deployment.

    Returns True when the classifier says safe, and True when it cannot be
    reached: this is a filter in front of a website auditor, and failing closed
    would mean an outage in the safety model takes the whole tool down.
    Anything where that trade is wrong needs its own check, not this one.
    """
    key = key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return True
    try:
        data = _post(key, {
            "model": SAFETY_MODEL,
            "temperature": 0,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": text[:4000]}],
        }, timeout)
        reply = (data["choices"][0]["message"]["content"] or "").lower()
    except (LLMError, KeyError, IndexError, TypeError):
        return True
    return "unsafe" not in reply
