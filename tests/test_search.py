import unittest

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
