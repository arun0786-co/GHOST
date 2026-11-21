import json
import os

from support import GhostTestCase

from ghost import files
from ghost.util import GhostError


class WalkTests(GhostTestCase):
    def walked(self, root, rules=None):
        report = files.WalkReport()
        rules = rules or files.load_rules(str(root), [], 1024 * 1024, [])
        found = [os.path.relpath(path, root) for path, _ in files.walk(str(root), rules, report)]
        return found, report

    def test_reads_text_files_in_a_stable_order_and_skips_the_rest(self):
        for rel in (
            "b.md", "a.txt", "sub/c.py", "sub/deeper/d.json", "Makefile",
            "photo.jpg", "app.min.js", "package-lock.json", "id_rsa", "server.pem", "secrets.yaml",
            ".hidden.md", ".git/config.md", "node_modules/x/readme.md", "build/out.md", "Library/x.md",
        ):
            self.write(f"src/{rel}", "text")
        os.symlink(self.home / "src" / "a.txt", self.home / "src" / "link.md")
        os.symlink(self.home / "src" / "sub", self.home / "src" / "linked-folder")
        found, _ = self.walked(self.home / "src")
        self.assertEqual(found, ["Makefile", "a.txt", "b.md", "sub/c.py", "sub/deeper/d.json"])

    def test_ghostignore_and_config_patterns(self):
        for rel in ("keep.md", "private/diary.md", "journal/2019/jan.md", "journal/2024/jan.md", "drafts/x.md", "notes.tmp.md"):
            self.write(f"src/{rel}", "text")
        self.write("src/.ghostignore", "# comments and blank lines are fine\nprivate\n\njournal/2019\n")
        rules = files.load_rules(str(self.home / "src"), ["*.tmp.md"], 1 << 20, [])
        found, _ = self.walked(self.home / "src", rules)
        self.assertEqual(sorted(found), ["drafts/x.md", "journal/2024/jan.md", "keep.md"])

    def test_size_limit_and_extra_types(self):
        self.write("src/big.md", "x" * 3000)
        self.write("src/small.md", "x")
        self.write("src/data.csv", "a,b")
        self.write("src/other.csv", "a,b")
        rules = files.load_rules(str(self.home / "src"), [], 2000, [".csv"])
        found, report = self.walked(self.home / "src", rules)
        self.assertEqual(found, ["data.csv", "other.csv", "small.md"])
        self.assertEqual(report.too_big, 1)
        found, _ = self.walked(self.home / "src")
        self.assertNotIn("data.csv", found)

    def test_unreadable_folders_are_reported(self):
        if os.geteuid() == 0:
            self.skipTest("root can read everything")
        self.write("src/ok.md", "x")
        self.write("src/locked/x.md", "x")
        locked = self.home / "src" / "locked"
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        found, report = self.walked(self.home / "src")
        self.assertEqual(found, ["ok.md"])
        self.assertEqual(report.unreadable, [str(locked)])

    def test_an_unreadable_ghostignore_stops_indexing_that_source(self):
        self.write("src/.ghostignore", data=b"\xff\xfe not text")
        with self.assertRaises(GhostError) as caught:
            files.load_rules(str(self.home / "src"), [], 1 << 20, [])
        self.assertIn("nothing was indexed", str(caught.exception))


class ReadTextTests(GhostTestCase):
    def test_binary_files_are_refused(self):
        self.assertIsNone(files.read_text("x.md", b"text\x00more"))

    def test_bom_and_line_endings(self):
        text = files.read_text("x.txt", "﻿one\r\ntwo\rthree".encode())
        self.assertEqual(text.body, "one\ntwo\nthree")
        self.assertFalse(text.markdown)
        self.assertTrue(text.has_lines)
        self.assertTrue(files.read_text("x.md", b"# hi").markdown)

    def test_notebooks_keep_cells_without_outputs(self):
        notebook = {
            "cells": [
                {"cell_type": "markdown", "source": ["# Results\n", "loss went down"]},
                {"cell_type": "code", "source": "# TODO: try a lower lr\nfit()", "outputs": [{"text": "OUTPUT NOISE"}]},
                {"cell_type": "code", "source": ""},
            ]
        }
        text = files.read_text("run.ipynb", json.dumps(notebook).encode())
        self.assertEqual(text.body, "# Results\nloss went down\n\n```\n# TODO: try a lower lr\nfit()\n```")
        self.assertTrue(text.markdown)
        self.assertFalse(text.has_lines)

    def test_a_broken_notebook_is_read_as_plain_text(self):
        text = files.read_text("run.ipynb", b"{not json")
        self.assertEqual(text.body, "{not json")
        self.assertTrue(text.has_lines)

    def test_html_keeps_visible_text_and_headings(self):
        page = (
            "<html><head><title>Trip</title><style>p {color: red}</style></head><body>"
            "<h1>Lisbon</h1><p>Flight at 9 &amp; hotel booked.</p><script>var x = 1;</script>"
            "<h2>Packing</h2><ul><li>passport</li><li>charger</li></ul></body></html>"
        )
        text = files.read_text("trip.html", page.encode())
        self.assertEqual(text.body, "Trip\n\n# Lisbon\n\nFlight at 9 & hotel booked.\n\n## Packing\n\npassport\n\ncharger")
        self.assertTrue(text.markdown)
        self.assertNotIn("color", text.body)
        self.assertNotIn("var x", text.body)
