# -*- coding: utf-8 -*-
import unittest

from answerable import bank as banks, score

BANK = {
    "name": "test",
    "questions": [
        {"key": "hours", "kind": "hours", "question": "When are you open?"},
        {"key": "prices", "question": "What does it cost?",
         "pattern": r"(£\s?\d|\bour prices\b)"},
        {"key": "parking", "question": "Where do I park?",
         "pattern": r"\bparking\b"},
    ],
}


def site(lines=(), hours=(), reachable=True, why=""):
    return {"lines": list(lines), "hours": list(hours),
            "reachable": reachable, "why": why}


class Verdicts(unittest.TestCase):
    def test_a_matched_line_is_kept_as_evidence(self):
        v = score.score(site(lines=["Free parking at the rear"]), BANK)
        parking = [x for x in v if x.key == "parking"][0]
        self.assertEqual(parking.status, score.ANSWERED)
        self.assertEqual(parking.evidence, "Free parking at the rear")

    def test_hours_come_from_the_extractor_not_the_patterns(self):
        v = score.score(site(hours=["Monday 9-5"]), BANK)
        hours = [x for x in v if x.key == "hours"][0]
        self.assertEqual(hours.status, score.ANSWERED)

    def test_mentioning_a_topic_is_not_answering_it(self):
        v = score.score(site(lines=["Affordable dentistry for all the family"]),
                        BANK)
        prices = [x for x in v if x.key == "prices"][0]
        self.assertEqual(prices.status, score.MISSING)


class Evidence(unittest.TestCase):
    def test_the_snippet_contains_what_matched(self):
        # A long paragraph whose match sits near the end read, truncated from
        # the left, as evidence for something else entirely.
        line = ("We are a family practice and have been part of this town for "
                "many years, with a waiting room that we hope feels calm. " * 3
                + "Free parking is available at the rear.")
        v = score.score(site(lines=[line]), BANK)
        parking = [x for x in v if x.key == "parking"][0]
        self.assertIn("parking", parking.evidence.lower())
        self.assertLess(len(parking.evidence), len(line))

    def test_a_short_line_is_quoted_whole(self):
        v = score.score(site(lines=["Free parking at the rear"]), BANK)
        parking = [x for x in v if x.key == "parking"][0]
        self.assertEqual(parking.evidence, "Free parking at the rear")


class Unreadable(unittest.TestCase):
    def test_an_unread_site_scores_nothing_rather_than_zero(self):
        # 432 of the 1,606 law firm sites this came from, 27%, refused
        # automated access even after a retry with a browser user agent.
        # Reporting them as answering nothing would be a claim about those
        # businesses, when the only fact available is about our access.
        v = score.score(site(reachable=False, why="blocked"), BANK)
        self.assertTrue(all(x.status == score.UNREADABLE for x in v))
        s = score.summarise(v)
        self.assertIsNone(s["score"])
        self.assertEqual(s["missing"], 0)

    def test_a_read_site_gets_a_number(self):
        v = score.score(site(lines=["Free parking"], hours=["Mon 9-5"]), BANK)
        self.assertEqual(score.summarise(v)["score"], 2)


class ModelPass(unittest.TestCase):
    def test_the_model_only_sees_unsettled_questions(self):
        asked = []

        def model(question, extract):
            asked.append(question)
            return False

        score.score(site(lines=["Free parking"], hours=["Mon 9-5"]), BANK,
                    model=model)
        self.assertEqual(asked, ["What does it cost?"])

    def test_a_model_failure_does_not_become_a_claim(self):
        def model(question, extract):
            raise RuntimeError("openrouter down")

        v = score.score(site(lines=["Free parking"]), BANK, model=model)
        prices = [x for x in v if x.key == "prices"][0]
        self.assertEqual(prices.status, score.MISSING)
        self.assertIn("unavailable", prices.why)


class Banks(unittest.TestCase):
    def test_every_shipped_bank_loads_and_compiles(self):
        for name in banks.available():
            bank = banks.load(name)
            self.assertTrue(bank.get("questions"), name)
            keys = [q["key"] for q in bank["questions"]]
            self.assertEqual(len(keys), len(set(keys)), name)

    def test_every_question_is_decidable(self):
        # Either a pattern decides it or the hours extractor does. A question
        # with neither is silently unanswerable and would be reported as a gap
        # on every site ever audited.
        for name in banks.available():
            bank = banks.load(name)
            for q in bank["questions"]:
                self.assertTrue(q.get("pattern") or q.get("kind") == "hours",
                                "%s/%s" % (name, q["key"]))


class Patterns(unittest.TestCase):
    """The judgement calls, spelled out. These are the ones worth arguing with."""

    def check(self, bank_name, key, positives, negatives):
        bank = banks.load(bank_name)
        q = [x for x in bank["questions"] if x["key"] == key][0]
        for line in positives:
            v = score.score(site(lines=[line]), {"questions": [q]})[0]
            self.assertEqual(v.status, score.ANSWERED, "%s: %s" % (key, line))
        for line in negatives:
            v = score.score(site(lines=[line]), {"questions": [q]})[0]
            self.assertEqual(v.status, score.MISSING, "%s: %s" % (key, line))

    def test_new_patients_needs_a_statement_not_the_word(self):
        # Every dental page ever written contains the word "patients". The
        # question is settled only by a statement about accepting them.
        self.check("dental", "new_patients",
                   ["New patients are welcome",
                    "We are not currently accepting new patients",
                    "There is a waiting list for NHS places",
                    "Register as a new patient online"],
                   ["Our patients tell us they feel at ease",
                    "Patient care is at the heart of what we do"])

    def test_prices_needs_a_figure_or_a_price_list(self):
        self.check("dental", "prices",
                   ["Examination £45", "Our fees start from £30",
                    "Download our price list"],
                   ["Affordable dentistry for the whole family",
                    "Great value treatment"])

    def test_free_first_consultation_is_a_specific_claim(self):
        self.check("legal", "free_first",
                   ["We offer a free initial consultation",
                    "The first half hour is free with no obligation"],
                   ["We offer a consultation at our standard hourly rate",
                    "Free parking is available for clients"])

    def test_a_page_heading_is_not_an_answer_about_who_acts_for_you(self):
        # "Legal Services From Our Solicitors" scored a point on a real firm
        # before this was tightened. It is a banner, not an answer.
        self.check("legal", "who",
                   ["Meet our team", "Our solicitors are all STEP qualified",
                    "Head of Family"],
                   ["Legal Services From Our Solicitors",
                    "Our partners in the local community"])

    def test_a_form_label_is_not_an_answer_about_remote_working(self):
        # "If you prefer not to be contacted by telephone, leave this section
        # blank" matched the old pattern. It is a contact form, not a policy.
        self.check("legal", "remote",
                   ["We offer appointments by video or telephone",
                    "Home visits can be arranged"],
                   ["If you prefer not to be contacted by telephone, "
                    "leave this section blank"])

    def test_a_passing_mention_of_the_team_is_not_a_roster(self):
        # "There's nothing we love more than sharing the stories of our vets"
        # scored the team question on a real practice site. Same class of bug
        # as the legal `who` banner.
        self.check("veterinary", "team",
                   ["Meet our team", "Our vets are all RCVS registered",
                    "Our clinical director has been here since 2004"],
                   ["There is nothing we love more than sharing the stories "
                    "of our vets, our pets and the people who bring them in"])

    def test_the_same_holds_for_a_dental_roster(self):
        self.check("dental", "team",
                   ["Meet our team", "Our dentists hold GDC registration"],
                   ["We are proud of our clinicians and the care they give"])

    def test_out_of_hours_is_the_question_a_worried_owner_asks(self):
        self.check("veterinary", "emergency",
                   ["Our out of hours service is provided by Vets Now",
                    "For emergency care outside opening times call 01223 000000"],
                   ["We offer routine consultations and vaccinations"])


if __name__ == "__main__":
    unittest.main()
