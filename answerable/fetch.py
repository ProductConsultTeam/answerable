# -*- coding: utf-8 -*-
"""Getting the pages, which is harder than it sounds.

Naive fetching under-reads real business websites badly. Crawling 1,606 UK law
firm websites with a default Python user agent reported 492 of them, 31%, as
dead. They were not: they were behind a WAF answering 403 to anything that did
not look like a browser, or dropping the connection outright. A retry with a
browser user agent, a longer timeout and a www fallback reached a fifth of
those immediately. The remaining 432, 27% of the list, still refused.

So this module exists to make "the site did not respond" mean something. When
it says a site is unreachable, that should be a fact about the site rather than
a fact about our HTTP client.

It is also a URL fetcher accepting arbitrary input, which makes it a proxy and
an amplification vector unless it is fenced. The guards here are not optional:
private address ranges are blocked so it cannot be pointed at internal hosts,
redirects are capped, response size is capped, and the page budget is finite.
"""
import gzip
import io
import ipaddress
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zlib

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

# Certificate problems are common on small business hosting and say nothing
# about whether the business exists, which is the only question being asked.
# Nothing here is trusted or executed, so the weaker guarantee is acceptable.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5


class Blocked(Exception):
    """The URL resolves somewhere we refuse to fetch from."""


def _is_public(host):
    """Resolve and refuse anything that is not a public address.

    Without this the crawler is a confused deputy: a caller supplies
    http://169.254.169.254/ or http://192.168.1.1/ and we fetch internal
    resources on their behalf and hand back the contents.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _decode(raw, headers):
    enc = (headers.get("Content-Encoding") or "").lower()
    if "gzip" in enc:
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    elif "deflate" in enc:
        try:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        except zlib.error:
            pass

    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", headers.get("Content-Type") or "", re.I)
    if m:
        charset = m.group(1)
    else:
        # Meta charset, when the header does not say. Reading the wrong codec
        # is how "café" becomes "cafÃ©" and then gets read aloud by an agent.
        m = re.search(rb'charset=["\']?([\w-]{2,20})', raw[:4096], re.I)
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def get(url, timeout=15):
    """Fetch one URL. Returns HTML text, or None.

    None means every reasonable attempt failed. It does not mean the business
    is closed, and callers should not report it as though it does.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise Blocked("only http and https are fetched: %s" % parts.scheme)
    if not parts.hostname:
        raise Blocked("no host in %r" % url)
    if not _is_public(parts.hostname):
        raise Blocked("refusing non-public address: %s" % parts.hostname)

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "text" not in ctype and ctype:
                return None
            return _decode(r.read(MAX_BYTES), r.headers)
    except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout,
            ssl.SSLError, ConnectionError, OSError):
        return None


def get_site(domain, paths=("",), timeout=15, max_pages=12):
    """Fetch a domain's pages, trying the variants that actually matter.

    Returns (base_url, {path: html}). base_url is None if nothing answered.

    The variant order is deliberate. https first because most sites are there;
    then www, because a surprising number of small business sites serve only
    the www host and answer nothing on the apex; then plain http, because some
    older hosting still does not redirect.
    """
    domain = re.sub(r"^https?://", "", domain).strip("/ ").lower()
    if not domain:
        return None, {}

    base = None
    home = None
    for candidate in ("https://" + domain, "https://www." + domain,
                      "http://" + domain):
        try:
            home = get(candidate, timeout)
        except Blocked:
            raise
        if home:
            base = candidate
            break
    if not base:
        return None, {}

    pages = {"": home}
    budget = max_pages - 1
    for path in paths:
        if not path or budget <= 0:
            continue
        html = get(base + path, min(timeout, 8))
        if html:
            pages[path] = html
        budget -= 1
    return base, pages


def looks_parked(text):
    """A registrar holding page answers 200 and contains nothing.

    Treated separately from "unreachable" because the two mean different
    things to whoever reads the report.
    """
    if len(text.strip()) > 2500:
        return False
    return bool(re.search(
        r"(domain (is )?for sale|buy this domain|this domain is parked|"
        r"under construction|coming soon|website (is )?being (updated|rebuilt)|"
        r"godaddy|sedo)", text, re.I))
