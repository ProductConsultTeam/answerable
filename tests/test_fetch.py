# -*- coding: utf-8 -*-
import unittest

from answerable import fetch


class Guards(unittest.TestCase):
    def test_private_and_metadata_addresses_are_refused(self):
        # Without this the crawler is a confused deputy: a caller supplies a
        # link-local or private URL and we fetch internal resources on their
        # behalf and hand back the contents.
        for url in ("http://127.0.0.1/", "http://localhost/",
                    "http://169.254.169.254/latest/meta-data/",
                    "http://192.168.1.1/", "http://10.0.0.1/"):
            self.assertRaises(fetch.Blocked, fetch.get, url)

    def test_only_http_and_https_are_fetched(self):
        for url in ("file:///etc/passwd", "ftp://example.com/",
                    "gopher://example.com/"):
            self.assertRaises(fetch.Blocked, fetch.get, url)


class Resolution(unittest.TestCase):
    """A name that will not resolve is not a name we are refusing.

    Auditing 972 law firm websites in one run, every lookup from firm 500
    onward failed because a local resolver gave up under sustained load. All
    of them were reported as "refusing non-public address", so the run
    concluded that half the legal profession hosts its website on a private
    IP. The verdict was wrong, the reason given was wrong, and it was wrong in
    the direction that makes a tool look confident.
    """

    def test_a_name_that_does_not_exist_is_unresolved_not_blocked(self):
        try:
            fetch.get("http://this-name-does-not-exist-8f2a1c.invalid/")
        except fetch.Unresolved:
            pass
        except fetch.Blocked as e:
            self.fail("reported as a security refusal: %s" % e)

    def test_unresolved_is_not_a_kind_of_blocked(self):
        # Callers catch Blocked to mean "we refused this on purpose". If
        # Unresolved inherited from it, every DNS wobble would be laundered
        # back into a refusal by the first except clause up the stack.
        self.assertFalse(issubclass(fetch.Unresolved, fetch.Blocked))

    def test_private_addresses_are_still_refused(self):
        for url in ("http://127.0.0.1/", "http://169.254.169.254/",
                    "http://10.0.0.1/"):
            self.assertRaises(fetch.Blocked, fetch.get, url)

    def test_a_nat64_address_is_as_public_as_the_v4_inside_it(self):
        # 64:ff9b::<v4> is RFC 6052, handed out by IPv6-only networks so a
        # v4-only host stays reachable. ipaddress calls the whole /96
        # reserved. 411 of 972 law firm sites were refused over this.
        import ipaddress
        pub = ipaddress.ip_address("64:ff9b::b9c7:dc6f")     # 185.199.220.111
        self.assertTrue(fetch._usable(pub))
        priv = ipaddress.ip_address("64:ff9b::c0a8:0101")    # 192.168.1.1
        self.assertFalse(fetch._usable(priv))

    def test_one_public_address_is_enough(self):
        # Real hosts are dual stack. Refusing because one record out of six
        # looks internal refuses most of the internet.
        import ipaddress
        self.assertTrue(fetch._usable(ipaddress.ip_address("185.199.220.111")))
        self.assertFalse(fetch._usable(ipaddress.ip_address("192.168.1.1")))
        self.assertFalse(fetch._usable(ipaddress.ip_address("169.254.169.254")))

    def test_resolve_gives_up_rather_than_hanging(self):
        self.assertIsNone(fetch._resolve("nope-8f2a1c.invalid", attempts=1))


class Parked(unittest.TestCase):
    def test_a_holding_page_is_not_a_website(self):
        for text in ("This domain is parked by GoDaddy",
                     "Coming soon",
                     "Our website is being updated"):
            self.assertTrue(fetch.looks_parked(text), text)

    def test_a_real_page_is_not_parked(self):
        # Length is half the test: a long page containing the words "coming
        # soon" about a new service is a real page.
        real = ("We are a family dental practice in Cambridge. " * 80 +
                "Our new hygienist service is coming soon.")
        self.assertFalse(fetch.looks_parked(real))


class Decoding(unittest.TestCase):
    def test_meta_charset_is_used_when_the_header_is_silent(self):
        raw = b'<meta charset="iso-8859-1"><p>caf\xe9</p>'
        out = fetch._decode(raw, {"Content-Type": "text/html"})
        self.assertIn("café", out)

    def test_a_bad_charset_name_does_not_crash_the_run(self):
        raw = b"<meta charset=nonsense><p>hello</p>"
        self.assertIn("hello", fetch._decode(raw, {}))


if __name__ == "__main__":
    unittest.main()
