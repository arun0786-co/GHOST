import time
import unittest

from support import GhostTestCase

from ghost import search


class TermsTests(unittest.TestCase):
    def test_words_prefixes_and_phrases(self):
        self.assertEqual(search.terms('rent invoi* "due date" rent'), ['"rent"', '"invoi"*', '"due date"'])

    def test_punctuation_becomes_plain_words(self):
        self.assertEqual(
            search.terms('c++ (AND) "unclosed -x: NOT'),
            ['"c"', '"AND"', '"unclosed"', '"x"', '"NOT"'],
        )
        self.assertEqual(search.terms('*** "" ?'), [])


class SearchTests(GhostTestCase):
    def setUp(self):
        super().setUp()
        self.write(
            "docs/home/lease.md",
            "# Lease\n\nRent is due on the 5th of every month.\n\n"
            "## Repairs\n\nThe landlord fixes the heating.\n\n## Late rent\n\nLate rent costs a fee.\n",
        )
        self.write("docs/plans/ghost.md", "# Plans\n\nPricing: none yet, it is a personal tool.\n")
        self.write("docs/budget.md", "numbers for october\n")
        self.write("docs/random.md", "a long note about many things, the budget among them, and more words here\n")
        self.ok("add", str(self.home / "docs"))

    def test_every_word_has_to_match(self):
        out = self.ok("search", "landlord", "heating")
        self.assertIn("~/docs/home/lease.md:5", out)
        self.assertIn("The landlord fixes the heating", out)
        self.assertNotIn("ghost.md", out)

    def test_falls_back_to_any_word_and_says_so(self):
        out = self.ok("search", "landlord", "pricing")
        self.assertIn("no file has all of those words", out)
        self.assertIn("lease.md", out)
        self.assertIn("ghost.md", out)

    def test_one_result_per_file_with_a_count_of_the_rest(self):
        out = self.ok("search", "rent")
        self.assertEqual(out.count("lease.md"), 1)
        self.assertIn("1 more match in this file", out)

    def test_stemming_and_prefixes(self):
        self.assertIn("lease.md", self.ok("search", "fixing"))
        self.assertIn("ghost.md", self.ok("search", "pric*"))

    def test_the_file_name_counts(self):
        out = self.ok("search", "budget")
        self.assertLess(out.index("budget.md"), out.index("random.md"))

    def test_source_and_since_filters(self):
        self.write("other/rent.md", "rent again\n", mtime=time.time() - 40 * 86400)
        self.ok("add", str(self.home / "other"))
        self.assertIn("other/rent.md", self.ok("search", "rent"))
        self.assertNotIn("other/rent.md", self.ok("search", "rent", "--source", "docs"))
        self.assertNotIn("other/rent.md", self.ok("search", "rent", "--since", "30d"))
        self.assertIn("no source called nope", self.fails("search", "rent", "--source", "nope"))
        self.assertIn("cannot read", self.fails("search", "rent", "--since", "soon"))

    def test_no_matches_and_odd_input(self):
        self.assertIn("no matches", self.fails("search", "zebra"))
        code, out, err = self.ghost("search", 'c++ (AND) "unclosed -x: NOT')
        self.assertNotIn("error", out + err)
        self.assertIn("nothing to search for", self.fails("search", "***"))

    def test_limit(self):
        for i in range(5):
            self.write(f"docs/many/{i}.md", "shared word\n")
        self.ok("index")
        out = self.ok("search", "shared", "-n", "2")
        self.assertEqual(out.count("/many/"), 2)
        self.assertIn("1 or more", self.fails("search", "shared", "-n", "0"))
