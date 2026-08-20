# -*- coding: utf-8 -*-
"""Every test here is a bug that reached production once."""
import unittest

from answerable import extract


class Days(unittest.TestCase):
    def test_wednesday_and_saturday_reach_their_full_spelling(self):
        # The original stem list was wed(?:day|s)? and sat(?:day|s)?, which
        # never match "Wednesday" or "Saturday". Two practices had exactly
        # those rows dropped, so the audit would have reported a business shut
        # on a day it opens.
        for day in ("Wednesday", "Saturday", "Monday", "Tuesday", "Thursday",
                    "Friday", "Sunday", "Weds", "Tues", "Thurs", "Sat", "Sun"):
            html = "<p>%s 9:00 - 17:00</p>" % day
            self.assertTrue(extract.opening_hours(html),
                            "%s produced no hours line" % day)

    def test_day_stems_do_not_match_inside_words(self):
        # Without a leading word boundary, "mon" matches inside "Monument" and
        # "testimonials", and "sat" inside "saturation".
        for noise in ("Monument House 9:00 - 17:00",
                      "testimonials 9:00 - 17:00",
                      "colour saturation 9:00 - 17:00"):
            self.assertEqual(extract.opening_hours("<p>%s</p>" % noise), [])

    def test_closed_is_an_answer(self):
        self.assertTrue(extract.opening_hours("<p>Sunday: Closed</p>"))


class Tables(unittest.TestCase):
    def test_table_row_stays_on_one_line(self):
        # Breaking on </td> puts the day and the time on separate lines, and a
        # pattern needing both then matches neither.
        html = "<table><tr><td>Monday</td><td>08:30 - 17:30</td></tr></table>"
        self.assertTrue(extract.opening_hours(html))

    def test_cells_are_separated_not_glued(self):
        html = "<tr><td>Fees</td><td>from 45</td></tr>"
        self.assertIn("Fees", extract.to_text(html))
        self.assertNotIn("Feesfrom", extract.to_text(html))


class Junk(unittest.TestCase):
    def test_comment_tail_does_not_survive_as_content(self):
        # The tail of an HTML comment outlives tag stripping and arrives
        # looking like a line of content. "-->" once appeared in a list of
        # dental treatments.
        html = "<p>Implants</p><!-- <p>Draft copy</p> --><p>Whitening</p>"
        lines = extract.to_lines(html)
        self.assertNotIn("-->", " ".join(lines))
        self.assertNotIn("Draft copy", " ".join(lines))

    def test_scripts_and_styles_are_dropped(self):
        html = "<style>.a{color:red}</style><script>var x=1;</script><p>Hello</p>"
        self.assertEqual(extract.to_lines(html), ["Hello"])

    def test_entities_are_decoded_before_matching(self):
        # "Saturday &amp; Sunday" was otherwise printed and read aloud as
        # "Saturday amp Sunday".
        self.assertIn("&", extract.to_text("<p>Saturday &amp; Sunday</p>"))


class OwnVoice(unittest.TestCase):
    def test_reviews_are_not_the_business_speaking(self):
        # This one is the whole reason the filter exists: it was captured as a
        # practice emergency policy and would have had an agent badmouthing a
        # named competitor to a caller.
        reviews = [
            "I moved over to Quality Dental after having a bad experience "
            "with Worthing Dental",
            "Would recommend to anyone, friendly staff and very thorough",
            "Thank you so much for seeing me at short notice",
            "5 stars, great experience",
        ]
        for r in reviews:
            self.assertFalse(extract.is_own_voice(r), r)

    def test_biography_is_not_policy(self):
        # "Since qualifying, he has worked in both NHS and private practices"
        # is a career history. Reading it as an answer to "do you take NHS
        # patients" is a confident wrong answer.
        bios = [
            "Since qualifying, he has worked in both NHS and private practices",
            "She has a special interest in nervous patients",
            "He provides implants and cosmetic dentistry",
        ]
        for b in bios:
            self.assertFalse(extract.is_own_voice(b), b)

    def test_the_business_speaking_survives(self):
        keep = [
            "We are currently accepting new NHS patients",
            "Emergency appointments are available every weekday",
            "Free parking is available at the rear of the practice",
        ]
        for k in keep:
            self.assertTrue(extract.is_own_voice(k), k)

    def test_mojibake_is_rejected(self):
        self.assertFalse(extract.is_own_voice("We are open Monday â€“ Friday"))

    def test_navigation_is_not_content(self):
        html = "<li>Home</li><li>About Us</li><li>We fit dental implants</li>"
        self.assertEqual(extract.clean_lines(html), ["We fit dental implants"])


if __name__ == "__main__":
    unittest.main()
