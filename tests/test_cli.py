import os

from support import GhostTestCase

from ghost import __version__


class AddTests(GhostTestCase):
    def test_add_indexes_and_lists_the_folder(self):
        self.write("My Notes/a.md", "- [ ] one task\n")
        out = self.ok("add", str(self.home / "My Notes"))
        self.assertIn("added My-Notes: ~/My Notes", out)
        self.assertIn("My-Notes: 1 new", out)
        listed = self.ok("sources")
        self.assertIn("My-Notes", listed)
        self.assertRegex(listed, r"My-Notes\s+1\s+1\s+just now\s+~/My Notes")

    def test_add_refuses_bad_input(self):
        self.write("docs/a.md", "x")
        self.write("file.md", "x")
        self.assertIn("is not a folder", self.fails("add", str(self.home / "file.md")))
        self.assertIn("is not a folder", self.fails("add", str(self.home / "missing")))
        self.assertIn("only have letters", self.fails("add", str(self.home / "docs"), "--name", "a b"))
        self.ok("add", str(self.home / "docs"))
        self.assertIn("already a source, called docs", self.fails("add", str(self.home / "docs"), "--name", "other"))
        self.write("x/docs/b.md", "x")
        self.assertIn("pick another name", self.fails("add", str(self.home / "x" / "docs")))
        self.ghost_home.mkdir(exist_ok=True)
        self.assertIn("ghost's own folder", self.fails("add", str(self.ghost_home)))

    def test_overlapping_sources_are_pointed_out(self):
        self.write("work/project/a.md", "x")
        self.ok("add", str(self.home / "work"))
        self.assertIn("overlaps with work", self.ok("add", str(self.home / "work" / "project")))

    def test_add_without_indexing(self):
        self.write("docs/a.md", "x")
        self.assertIn("ghost index docs", self.ok("add", str(self.home / "docs"), "--no-index"))
        self.assertIn("never", self.ok("sources"))
        self.assertIn("docs: 1 new", self.ok("index", "docs"))


class CommandTests(GhostTestCase):
    def test_before_anything_is_indexed(self):
        for argv in (("search", "x"), ("ask", "x"), ("todo",), ("timeline",), ("remove", "x")):
            with self.subTest(argv=argv):
                self.assertIn("nothing indexed yet", self.fails(*argv))
        self.assertIn("no sources yet", self.ok("sources"))
        self.assertIn("nothing to index yet", self.ok("index"))

    def test_index_reports_changes(self):
        self.write("docs/a.md", "alpha")
        self.write("docs/b.md", "beta")
        self.ok("add", str(self.home / "docs"))
        self.assertIn("docs: 2 unchanged", self.ok("index"))
        self.write("docs/a.md", "alpha again!")
        (self.home / "docs" / "b.md").unlink()
        self.write("docs/c.md", "gamma")
        self.assertIn("docs: 1 new, 1 changed, 1 deleted", self.ok("index"))
        self.assertIn("no source called nope", self.fails("index", "nope"))

    def test_one_broken_source_does_not_stop_the_others(self):
        self.write("good/a.md", "alpha")
        self.write("bad/b.md", "beta")
        self.write("bad/.ghostignore", data=b"\xff\xfe not text")
        self.ok("add", str(self.home / "good"))
        code, out, err = self.ghost("add", str(self.home / "bad"))
        self.assertEqual(code, 1)
        self.assertIn("bad: cannot read ~/bad/.ghostignore", err)
        code, out, err = self.ghost("index")
        self.assertEqual(code, 1)
        self.assertIn("good: 1 unchanged", out)
        self.assertIn("so nothing was indexed from that source", err)
        self.assertNotIn("beta", self.ok("search", "alpha"))

    def test_remove_forgets_but_never_touches_files(self):
        self.write("docs/a.md", "alpha")
        self.ok("add", str(self.home / "docs"))
        before = self.tree(self.home / "docs")
        self.assertIn("nothing in ~/docs was touched", self.ok("remove", "docs"))
        self.assertEqual(self.tree(self.home / "docs"), before)
        self.assertIn("no sources yet", self.ok("sources"))
        self.assertIn("no matches", self.fails("search", "alpha"))

    def test_todo_groups_tasks_by_file(self):
        self.write("docs/a.md", "# A\n- [ ] first thing\n- [x] done\n- [ ] second thing\n")
        self.write("docs/b.py", "x = 1  # TODO: tidy this\n")
        self.ok("add", str(self.home / "docs"))
        out = self.ok("todo")
        self.assertIn("~/docs/a.md", out)
        self.assertIn("      2  first thing", out)
        self.assertIn("      4  second thing", out)
        self.assertIn("tidy this", out)
        self.assertNotIn("done", out)
        self.assertIn("3 open tasks in 2 files", out)
        self.assertNotIn("tidy", self.ok("todo", "thing"))
        self.assertIn("showing the first 1", self.ok("todo", "-n", "1"))
        self.assertIn("no open tasks", self.ok("todo", "zebra"))

    def test_bad_config_is_reported(self):
        self.write_config("[model\nurl = 1")
        self.assertIn("config.toml is not valid toml", self.fails("sources"))
        self.write_config("[index]\nmax_file_kb = 'big'\n")
        self.assertIn("config.toml", self.fails("sources"))

    def test_config_skip_and_extra_types(self):
        self.write_config('[index]\nskip = ["drafts"]\nextra_types = ["csv"]\n')
        self.write("docs/drafts/a.md", "secret plans")
        self.write("docs/numbers.csv", "month,rent\noct,1200\n")
        self.ok("add", str(self.home / "docs"))
        self.assertIn("no matches", self.fails("search", "plans"))
        self.assertIn("numbers.csv", self.ok("search", "rent"))

    def test_version_and_help(self):
        self.assertIn(__version__, self.ghost("--version")[1])
        self.assertIn("timeline", self.ok())


class DoctorTests(GhostTestCase):
    def test_doctor_writes_nothing(self):
        out = self.ok("doctor")
        self.assertIn("does not exist yet", out)
        self.assertIn("no model server", out)
        self.assertFalse(self.ghost_home.exists())

        self.write("docs/a.md", "- [ ] a task")
        self.ok("add", str(self.home / "docs"))
        before = self.tree(self.ghost_home)
        out = self.ok("doctor")
        self.assertIn("readable only by you", out)
        self.assertIn("index: 1 file, 1 open task", out)
        self.assertIn("docs (~/docs): 1 file, 1 open task, indexed just now", out)
        self.assertEqual(self.tree(self.ghost_home), before)

    def test_doctor_points_out_problems(self):
        self.write("docs/a.md", "x")
        self.ok("add", str(self.home / "docs"))
        os.chmod(self.ghost_home, 0o755)
        (self.home / "docs" / "a.md").unlink()
        (self.home / "docs").rmdir()
        out = self.ok("doctor")
        self.assertIn("can be read by other users", out)
        self.assertIn("docs (~/docs) is missing", out)

    def test_doctor_finds_a_local_model_and_refuses_a_remote_one(self):
        server = self.fake_model(models=("qwen3:8b",))
        self.write_config(f'[model]\nurl = "{server.url}"\n')
        self.assertIn(f"model qwen3:8b on the ollama at {server.url}", self.ok("doctor"))
        self.write_config('[model]\nurl = "http://example.com"\n')
        self.assertIn("FAIL  the model url http://example.com is not on this machine", self.fails("doctor"))

    def test_doctor_does_not_count_cloud_models(self):
        cloud = {"name": "gemma4:cloud", "remote_model": "gemma4", "remote_host": "https://ollama.com:443"}
        server = self.fake_model(models=(cloud,))
        self.write_config(f'[model]\nurl = "{server.url}"\n')
        self.assertIn("has no local models yet", self.ok("doctor"))
        self.write_config(f'[model]\nurl = "{server.url}"\nname = "gemma4:cloud"\n')
        self.assertIn("FAIL  gemma4:cloud is an ollama cloud model", self.fails("doctor"))
