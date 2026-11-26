import os
import shutil
import subprocess
import unittest
from unittest import mock

from support import GhostTestCase, fake

from ghost import gitlog
from ghost.store import Store


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class GitSourceTests(GhostTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.home / "my app"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Sam Doe")
        self.git("config", "user.email", "sam@example.com")

    def git(self, *args, **env):
        done = subprocess.run(["git", "-C", str(self.repo), *args], env={**os.environ, **env}, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def commit(self, message, when="2026-10-20T12:00:00"):
        self.git("commit", "-q", "--allow-empty", "-m", message, GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when)
        return self.git("rev-parse", "HEAD")

    def add(self):
        return self.ok("add", "--git", str(self.repo))

    def store(self):
        store = Store(self.ghost_home / "ghost.db")
        self.addCleanup(store.close)
        return store

    def test_messages_are_searched_and_on_the_timeline(self):
        sha = self.commit("fix the parser\n\nquotes inside quotes broke it\n\n- [ ] not a task")
        self.commit("write docs", "2026-10-21T12:00:00")
        self.assertIn("my-app-git: 2 new", self.add())
        out = self.ok("search", "quotes", "broke")
        self.assertIn(f"~/my app@{sha[:12]}", out)
        self.assertIn(sha[:12], self.ok("search", sha[:12]))
        self.assertIn("by Sam Doe", self.ok("ask", "--no-model", "who fixed the parser"))
        day = self.ok("timeline", "--day", "2026-10-20")
        self.assertRegex(day, r"12:00  commit   my-app-git: fix the parser")
        self.assertNotIn("write docs", day)
        self.assertIn("no open tasks", self.ok("todo"))
        self.assertIn("2 commits, indexed", self.ghost("doctor")[1])

    def test_only_new_commits_are_added(self):
        self.commit("one")
        self.add()
        self.commit("two")
        self.assertIn("1 new, 1 unchanged", self.ok("index"))
        self.assertEqual(self.store().totals()["events"], 2)

    def test_rewritten_commits_are_forgotten(self):
        self.commit("keep")
        self.commit("typpo")
        self.add()
        self.git("commit", "-q", "--amend", "--allow-empty", "-m", "typo")
        self.assertIn("1 new, 1 deleted, 1 unchanged", self.ok("index"))
        self.assertEqual(self.ghost("search", "typpo")[0], 1)
        self.assertNotIn("typpo", self.ok("timeline", "--since", "2026-01-01"))

    def test_all_local_branches_and_a_detached_head(self):
        self.commit("base")
        self.git("switch", "-q", "-c", "side")
        self.commit("on side")
        self.git("switch", "-q", "--detach", "main")
        self.commit("on nothing")
        self.assertEqual({c.subject for c in gitlog.commits(str(self.repo))}, {"base", "on side", "on nothing"})

    def test_an_empty_repository_then_its_first_commit(self):
        self.assertIn("no files to index", self.add())
        self.commit("first")
        self.assertIn("1 new", self.ok("index"))

    def test_when_git_fails_the_index_is_kept(self):
        self.commit("precious")
        self.add()
        (self.repo / ".git").rename(self.home / "moved")
        self.assertIn("git failed in ~/my app", self.fails("index"))
        self.assertIn("precious", self.ok("search", "precious"))

    def test_secrets_never_reach_the_database(self):
        secret = fake("AKIA", "Z" * 16)
        self.commit(f"deploy with {secret}")
        self.assertIn("blanked 1 secret-like string", self.add())
        stored = b"".join(p.read_bytes() for p in self.ghost_home.glob("ghost.db*"))
        self.assertNotIn(secret.encode(), stored)

    def test_files_and_history_of_one_folder_can_both_be_sources(self):
        self.commit("one")
        self.write("my app/a.md", "x")
        self.ok("add", str(self.repo))
        self.assertNotIn("overlaps", self.add())
        self.assertIn("already a source, called my-app-git", self.fails("add", "--git", str(self.repo), "--name", "x"))

    def test_a_subfolder_means_the_whole_repository(self):
        self.commit("one")
        self.write("my app/sub/a.md", "x")
        self.assertIn("added my-app-git: ~/my app", self.ok("add", "--git", str(self.repo / "sub")))

    def test_a_plain_folder_is_refused(self):
        self.write("docs/a.md", "x")
        self.assertIn("git failed in ~/docs", self.fails("add", "--git", str(self.home / "docs")))
        self.assertIn("no sources yet", self.ok("sources"))

    def test_git_not_installed(self):
        with mock.patch.object(gitlog.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIn("git is not installed", self.fails("add", "--git", str(self.repo)))

    def test_the_repository_is_not_changed(self):
        self.commit("one")
        before = self.tree(self.repo)
        self.add()
        self.ok("index")
        self.assertEqual(self.tree(self.repo), before)

    def test_a_signed_commit_does_not_run_the_signature_program(self):
        # log.showSignature makes git log run gpg.program, which the repository itself can set
        head = self.commit("one")
        ran = self.home / "ran"
        script = self.write("gpg.sh", f"#!/bin/sh\ntouch '{ran}'\n")
        script.chmod(0o755)
        self.git("config", "gpg.program", str(script))
        self.git("config", "log.showSignature", "true")
        raw = self.git("cat-file", "commit", head)
        header, message = raw.split("\n\n", 1)
        signature = "gpgsig -----BEGIN PGP SIGNATURE-----\n \n abcd\n -----END PGP SIGNATURE-----"
        signed = self.write("signed", f"{header}\n{signature}\n\n{message}\n")
        sha = self.git("hash-object", "-t", "commit", "-w", str(signed))
        self.git("update-ref", "refs/heads/main", sha)
        self.git("log", "-1")
        self.assertTrue(ran.exists(), "plain git log should have run it")
        ran.unlink()
        self.add()
        self.assertFalse(ran.exists())

    def test_a_partial_clone_does_not_fetch(self):
        self.commit("one")
        seen = self.home / "fetched"
        helper = self.write("upload.sh", f"#!/bin/sh\ntouch '{seen}'\nexit 1\n")
        helper.chmod(0o755)
        self.git("config", "core.repositoryformatversion", "1")
        self.git("config", "extensions.partialClone", "origin")
        self.git("config", "remote.origin.url", str(self.home / "elsewhere"))
        self.git("config", "remote.origin.promisor", "true")
        self.git("config", "remote.origin.uploadpack", f"'{helper}'")
        (self.repo / ".git" / "refs" / "heads" / "gone").write_text("1" * 40 + "\n")
        self.ghost("add", "--git", str(self.repo))
        self.assertFalse(seen.exists())

    def test_git_variables_do_not_point_elsewhere(self):
        self.commit("one")
        with mock.patch.dict(os.environ, {"GIT_DIR": str(self.home / "nowhere")}):
            self.assertEqual([c.subject for c in gitlog.commits(str(self.repo))], ["one"])
