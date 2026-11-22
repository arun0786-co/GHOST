import unittest

from ghost import chunks


class SplitTests(unittest.TestCase):
    def test_headings_start_pieces_and_name_them(self):
        text = "intro line\n\n# One\nfirst\n\n## Two ##\nsecond\n"
        pieces = chunks.split(text, markdown=True)
        self.assertEqual(
            [(p.line, p.heading, p.text) for p in pieces],
            [(1, "", "intro line"), (3, "One", "# One\nfirst"), (6, "Two", "## Two ##\nsecond")],
        )

    def test_hash_lines_in_code_and_plain_files_are_not_headings(self):
        text = "# Title\n```\n# not a heading\n```\n#hashtag\n"
        self.assertEqual([p.heading for p in chunks.split(text, markdown=True)], ["Title"])
        self.assertEqual([p.heading for p in chunks.split("# a comment\ncode()", markdown=False)], [""])

    def test_long_text_is_cut_at_blank_lines_near_the_size(self):
        text = "\n\n".join(f"paragraph {i} " + " ".join(["word"] * 48) for i in range(10))
        pieces = chunks.split(text, markdown=False, size=600)
        self.assertGreater(len(pieces), 2)
        for piece in pieces:
            self.assertLessEqual(len(piece.text), 900)
        self.assertEqual(" ".join(p.text for p in pieces).split(), text.split())
        lines = text.split("\n")
        for piece in pieces:
            self.assertEqual(lines[piece.line - 1], piece.text.split("\n")[0])

    def test_without_blank_lines_pieces_are_cut_anyway(self):
        text = "\n".join("line " * 20 for _ in range(100))
        pieces = chunks.split(text, markdown=False, size=1000)
        self.assertGreater(len(pieces), 5)
        self.assertTrue(all(len(p.text) <= 1600 for p in pieces))

    def test_blank_lines_at_the_start_do_not_shift_line_numbers(self):
        self.assertEqual(chunks.split("\n\n\nhello", markdown=False)[0].line, 4)
        self.assertEqual(chunks.split("   \n\n", markdown=False), [])


class TaskTests(unittest.TestCase):
    def test_open_checkboxes_and_markers(self):
        text = "\n".join(
            [
                "- [ ] call the bank",
                "- [x] done already",
                "* [ ] star item",
                "1. [ ] numbered",
                "  - [ ] nested",
                "# TODO: write tests",
                "x = 1  # FIXME broken on linux",
                "/* TODO(me): drop this */",
                "todo_list = []",
                "TODOS are not tasks",
                "TODO:",
            ]
        )
        self.assertEqual(
            [(t.line, t.text) for t in chunks.tasks(text, markdown=False)],
            [(1, "call the bank"), (3, "star item"), (4, "numbered"), (5, "nested"), (6, "write tests"), (7, "broken on linux"), (8, "drop this")],
        )

    def test_code_blocks_in_markdown_are_skipped(self):
        text = "```\n- [ ] example in a fence\nTODO: also an example\n```\n- [ ] real one\n"
        self.assertEqual([(t.line, t.text) for t in chunks.tasks(text, markdown=True)], [(5, "real one")])

    def test_comment_closers_are_dropped(self):
        self.assertEqual(chunks.tasks("<!-- TODO: fix the footer -->", markdown=True)[0].text, "fix the footer")

    def test_long_tasks_are_cut(self):
        self.assertEqual(len(chunks.tasks("- [ ] " + "x" * 500, markdown=True)[0].text), 200)
