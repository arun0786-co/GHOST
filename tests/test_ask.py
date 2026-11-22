import unittest
from datetime import datetime

from ghost import ask


class PromptTests(unittest.TestCase):
    def test_keywords_drop_question_words(self):
        self.assertEqual(ask.keywords("When is the rent due? When?"), ["rent", "due"])
        self.assertEqual(ask.keywords("what is it"), ["what", "is", "it"])

    def test_prompt_has_the_date_the_passages_and_the_question(self):
        found = [ask.Passage(1, "/n/lease.md", 3, 0, "Rent is due on the 5th.")]
        system, user = ask.prompt("when is the rent due?", found, now=datetime(2026, 10, 27))
        self.assertIn("Today is Tuesday 27 October 2026", system["content"])
        self.assertIn("only the numbered passages", system["content"])
        self.assertIn("[1] /n/lease.md:3 (changed 1970-01-01)\nRent is due on the 5th.", user["content"])
        self.assertTrue(user["content"].endswith("Question: when is the rent due?"))

    def test_cited(self):
        found = [ask.Passage(n, f"/{n}.md", 1, 0, "x") for n in (1, 2, 3)]
        self.assertEqual([p.number for p in ask.cited("yes [2][3]", found)], [2, 3])
        self.assertEqual([p.number for p in ask.cited("yes [1, 3]", found)], [1, 3])
        self.assertEqual([p.number for p in ask.cited("no citations", found)], [1, 2, 3])
        self.assertEqual([p.number for p in ask.cited("made up [9]", found)], [1, 2, 3])
