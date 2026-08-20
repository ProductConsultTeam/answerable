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
