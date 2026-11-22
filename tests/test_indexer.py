import os
import time
from types import SimpleNamespace

from support import GhostTestCase, fake

from ghost import config as config_mod
from ghost import indexer
from ghost.store import Store


class IndexTests(GhostTestCase):
    def setUp(self):
        super().setUp()
        self.config = config_mod.load()
        config_mod.ensure_home(self.config)
        self.store = Store(self.config.db_path)
        self.addCleanup(self.store.close)
        self.src = self.home / "notes"
        self.src.mkdir()
        self.source = self.store.add_source("notes", "folder", str(self.src))

    def index(self):
        return indexer.index_source(self.store, self.source, self.config)

    def events(self):
        return [(row["kind"], os.path.basename(row["path"])) for row in self.store.events(0)]

    def test_new_changed_unchanged_and_deleted_files(self):
        self.write("notes/a.md", "alpha", mtime=time.time() - 3600)
        self.write("notes/b.md", "beta")
        report = self.index()
        self.assertEqual((report.new, report.changed, report.unchanged), (2, 0, 0))
        self.assertEqual(self.index().unchanged, 2)

        self.write("notes/a.md", "alpha changed")
        (self.src / "b.md").unlink()
        report = self.index()
        self.assertEqual((report.new, report.changed, report.unchanged, report.deleted), (0, 1, 0, 1))
        self.assertIn(("deleted", "b.md"), self.events())
        self.assertEqual(list(self.store.documents(self.source)), [str(self.src / "a.md")])
        self.assertEqual(self.store.totals()["pieces"], 1)

    def test_a_file_that_is_now_skipped_leaves_the_index_without_a_deleted_event(self):
        self.write("notes/a.md", "alpha")
        self.index()
        self.write("notes/.ghostignore", "a.md\n")
        report = self.index()
        self.assertEqual((report.dropped, report.deleted), (1, 0))
        self.assertNotIn("deleted", [kind for kind, _ in self.events()])
        self.assertEqual(self.store.totals()["files"], 0)

    def test_a_missing_folder_keeps_its_index(self):
        self.write("notes/a.md", "alpha")
        self.index()
        self.src.rename(self.home / "elsewhere")
        report = self.index()
        self.assertTrue(report.missing)
        self.assertEqual(self.store.totals()["files"], 1)

    def test_files_in_an_unreadable_folder_are_kept(self):
        if os.geteuid() == 0:
            self.skipTest("root can read everything")
        self.write("notes/a.md", "alpha")
        self.write("notes/locked/b.md", "beta")
        self.index()
        locked = self.src / "locked"
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        report = self.index()
        self.assertEqual(report.unreadable, [str(locked)])
        self.assertEqual((report.deleted, report.dropped), (0, 0))
        self.assertEqual(self.store.totals()["files"], 2)

    def test_binary_files_are_skipped(self):
        self.write("notes/weird.md", data=b"\x00\x01\x02")
        report = self.index()
        self.assertEqual((report.new, report.binary), (0, 1))

    def test_secrets_never_reach_the_database(self):
        secret = fake("AKIA", "Z" * 16)
        self.write("notes/aws.md", f"# keys\nthe deploy key is {secret}\n")
        report = self.index()
        self.assertEqual(report.redacted, 1)
        self.store.close()
        stored = b"".join(p.read_bytes() for p in self.ghost_home.glob("ghost.db*"))
        self.assertNotIn(secret.encode(), stored)
        self.assertIn(b"[redacted]", stored)

    def test_first_run_events_use_the_file_times(self):
        then = time.time() - 5 * 86400
        self.write("notes/old.md", "old", mtime=then)
        self.index()
        rows = self.store.events(0)
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0]["kind"], ("created", "edited"))  # created where the file system keeps birth times
        self.assertAlmostEqual(rows[0]["at"], then, delta=1)

    def test_notes_sources_get_no_file_events(self):
        notes = self.store.add_source("mine", "notes", str(self.ghost_home / "notes"))
        self.write(".ghost/notes/2026-10-27.md", "- 10:00 hi")
        indexer.index_source(self.store, notes, self.config)
        self.assertEqual(self.store.events(0), [])
        self.assertEqual(self.store.totals()["files"], 1)

    def test_removing_a_source_removes_everything_from_it(self):
        self.write("notes/a.md", "alpha\n- [ ] a task\n")
        self.index()
        self.store.remove_source(self.source)
        self.assertEqual(self.store.totals(), {"files": 0, "pieces": 0, "tasks": 0, "events": 0, "redacted": 0})
        self.assertEqual(self.store.db.execute("select count(*) from chunks_fts").fetchone()[0], 0)
        self.assertTrue((self.src / "a.md").exists())


class RecordChangeTests(GhostTestCase):
    class Recorder:
        def __init__(self):
            self.events = []

        def add_event(self, at, kind, source, path, detail=""):
            self.events.append((kind, at))

    def record(self, info, new, first_run):
        store = self.Recorder()
        indexer.record_change(store, None, "/x", info, new, first_run)
        return store.events

    def test_birth_time_gives_a_created_event(self):
        self.assertEqual(
            self.record(SimpleNamespace(st_mtime=1000.0, st_birthtime=500.0), True, True),
            [("created", 500.0), ("edited", 1000.0)],
        )
        self.assertEqual(self.record(SimpleNamespace(st_mtime=1000.0, st_birthtime=990.0), True, True), [("created", 990.0)])

    def test_without_birth_time_the_first_run_only_knows_the_last_edit(self):
        self.assertEqual(self.record(SimpleNamespace(st_mtime=1000.0), True, True), [("edited", 1000.0)])
        self.assertEqual(self.record(SimpleNamespace(st_mtime=1000.0), True, False), [("created", 1000.0)])

    def test_a_changed_file_is_edited(self):
        self.assertEqual(self.record(SimpleNamespace(st_mtime=1000.0, st_birthtime=5.0), False, False), [("edited", 1000.0)])
