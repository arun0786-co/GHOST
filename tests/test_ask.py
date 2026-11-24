import unittest
from datetime import datetime

from support import GhostTestCase

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
        self.assertIn("plain text, without markdown", system["content"])
        self.assertIn("[1] /n/lease.md:3 (changed 1970-01-01)\nRent is due on the 5th.", user["content"])
        self.assertTrue(user["content"].endswith("Question: when is the rent due?"))

    def test_cited(self):
        found = [ask.Passage(n, f"/{n}.md", 1, 0, "x") for n in (1, 2, 3)]
        self.assertEqual([p.number for p in ask.cited("yes [2][3]", found)], [2, 3])
        self.assertEqual([p.number for p in ask.cited("yes [1, 3]", found)], [1, 3])
        self.assertEqual([p.number for p in ask.cited("no citations", found)], [1, 2, 3])
        self.assertEqual([p.number for p in ask.cited("made up [9]", found)], [1, 2, 3])


class AskTests(GhostTestCase):
    def setUp(self):
        super().setUp()
        self.write("docs/lease.md", "# Lease\n\nRent is due on the 5th of every month.\n\n## Fees\n\nLate rent costs a fee.\n")
        self.write("docs/car.md", "The car insurance renews in March.\n")
        self.ok("add", str(self.home / "docs"))

    def test_passages_are_capped_per_file_and_numbered(self):
        from ghost import config as config_mod
        from ghost.store import Store

        store = Store(config_mod.load().db_path)
        self.addCleanup(store.close)
        found = ask.passages(store, "when is the rent due, and the insurance?")
        self.assertEqual([p.number for p in found], list(range(1, len(found) + 1)))
        self.assertEqual(sum(1 for p in found if p.path.endswith("lease.md")), 2)
        self.assertTrue(any(p.path.endswith("car.md") for p in found))

    def test_without_a_model_the_passages_are_shown(self):
        out = self.ok("ask", "when", "is", "the", "rent", "due?")
        self.assertIn("no model server found on this machine", out)
        self.assertIn("[1] ~/docs/lease.md:1", out)
        self.assertIn("Rent is due on the 5th", out)
        out = self.ok("ask", "--no-model", "when is the rent due")
        self.assertNotIn("no model server", out)
        self.assertIn("Rent is due on the 5th", out)

    def test_with_a_local_model(self):
        server = self.fake_model(answer="\n\nRent is due on the 5th [1].")
        self.write_config(f'[model]\nurl = "{server.url}"\n')
        out = self.ok("ask", "when is the rent due?")
        self.assertTrue(out.startswith("Rent is due on the 5th [1]."))
        self.assertIn("[1] ~/docs/lease.md:1", out)
        self.assertNotIn("[2]", out)
        sent = server.chats()[0]["messages"][1]["content"]
        self.assertIn("Rent is due on the 5th of every month.", sent)
        self.assertIn("Question: when is the rent due?", sent)

    def test_a_cloud_model_is_never_sent_the_passages(self):
        cloud = {"name": "gemma4:cloud", "remote_model": "gemma4", "remote_host": "https://ollama.com:443"}
        server = self.fake_model(models=(cloud,))
        self.write_config(f'[model]\nurl = "{server.url}"\n')
        self.assertIn("has no local models", self.ok("ask", "when is the rent due?"))
        self.assertIn("gemma4:cloud is an ollama cloud model", self.fails("ask", "--model", "gemma4:cloud", "when is the rent due?"))
        self.assertEqual(server.chats(), [])

    def test_nothing_matches(self):
        self.assertIn("nothing in your sources matches", self.fails("ask", "zebras?"))

    def test_a_remote_model_url_is_an_error(self):
        self.write_config('[model]\nurl = "http://example.com:11434"\n')
        self.assertIn("not on this machine", self.fails("ask", "rent?"))
