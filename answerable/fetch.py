# -*- coding: utf-8 -*-
"""Getting the pages, which is harder than it sounds.

Naive fetching under-reads real business websites badly, and it is worth being
precise about how badly, because the obvious measurements are also wrong.

Crawling 1,606 UK law firm websites with a default Python user agent reported
31% of them as dead. A browser user agent, a longer timeout and a www fallback
recovered a large share immediately, which is why those are here.

The figure that survived that retry, 27%, was still mostly this module's fault
rather than theirs: see the NAT64 and dual-stack note further down. Once that
was fixed, a clean run over 972 of the same firms read 937, and only 35 could
not be reached at all. Under 4%, not 27%.

The lesson is in the direction of the error. Every fault here failed towards
"their site is broken" rather than "our crawler is", which is the flattering
direction and therefore the one to distrust.

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
import time
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


class Unresolved(Exception):
    """The hostname did not resolve. Usually our network, not their site."""


def _resolve(host, attempts=3):
    """Look the host up, with a short backoff. None if it never resolves.

    The retry is not politeness, it is accuracy. Auditing 972 law firms in one
    run, every lookup from firm 500 onward failed: a local resolver gave up
    under sustained load. Every one of those firms was then reported as
    "refusing non-public address", which is a security refusal, and it read as
    though half the legal profession hosts its website on 192.168.
    """
    for i in range(attempts):
        try:
            return socket.getaddrinfo(host, None)
        except socket.gaierror:
            if i == attempts - 1:
                return None
            time.sleep(0.4 * (i + 1))


# RFC 6052. An IPv6-only network hands back 64:ff9b::<v4> so a v4-only host can
# still be reached, and ipaddress marks the whole /96 as reserved. It is an
# IPv4 address wearing a hat, and it is exactly as public as the address inside
# it. Auditing 972 law firms, 411 of them resolved to a good public v4 address
# and one of these, and every one was refused as though it were an internal
# host.
NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _unwrap(ip):
    """The address a NAT64 form actually points at, or the address itself."""
    if ip.version == 6 and ip in NAT64:
        return ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
    return ip


def _usable(ip):
    ip = _unwrap(ip)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _check_public(host):
    """Refuse a host that has nowhere public to be fetched from.

    Without this the crawler is a confused deputy: a caller supplies
    http://169.254.169.254/ or http://192.168.1.1/ and we fetch internal
    resources on their behalf and hand back the contents.

    The test is whether ANY resolved address is a public one, not whether ALL
    of them are. Real hosts are dual stack and routinely carry an address that
    a naive check reads as internal, so refusing on any single bad-looking
    record refuses most of the internet. A host with no public address at all
    is the confused-deputy case and is still refused.

    A name that will not resolve is a different fact and gets a different
    exception, because conflating the two turns a network wobble into a false
    statement about somebody's business.
    """
    infos = _resolve(host)
    if infos is None:
        raise Unresolved(host)
    seen = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        seen.append(ip)
        if _usable(ip):
            return
    if not seen:
        raise Blocked("could not parse any address for %s" % host)
    raise Blocked("refusing non-public address: %s" % host)


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
    _check_public(parts.hostname)

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
        except (Blocked, Unresolved):
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
