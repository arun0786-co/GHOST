from datetime import datetime

from support import GhostTestCase

from ghost import notes
from ghost.util import GhostError


def at(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


class NoteFileTests(GhostTestCase):
    def test_a_file_a_day_with_a_heading(self):
        folder = self.home / "n"
        notes.append(folder, "parking:   level 3,\n spot 42", when=at("2026-10-27 09:05"))
        notes.append(folder, "call the bank", todo=True, when=at("2026-10-27 18:30"))
        notes.append(folder, "new day", when=at("2026-10-28 08:00"))
        self.assertEqual(
            (folder / "2026-10-27.md").read_text(),
            "# 2026-10-27\n\n- 09:05 parking: level 3, spot 42\n- [ ] call the bank\n",
        )
        self.assertEqual((folder / "2026-10-28.md").read_text(), "# 2026-10-28\n\n- 08:00 new day\n")

    def test_appends_after_a_hand_edit_without_a_final_newline(self):
        folder = self.home / "n"
        folder.mkdir()
        (folder / "2026-10-27.md").write_text("# my own heading\nsome text")
        notes.append(folder, "more", when=at("2026-10-27 10:00"))
        self.assertEqual((folder / "2026-10-27.md").read_text(), "# my own heading\nsome text\n- 10:00 more\n")

    def test_empty_notes_are_refused(self):
        with self.assertRaises(GhostError):
            notes.append(self.home / "n", "  \n ")

    def test_recent_is_newest_first_and_ignores_other_files(self):
        folder = self.home / "n"
        notes.append(folder, "first", when=at("2026-10-26 09:00"))
        notes.append(folder, "second", when=at("2026-10-27 09:00"))
        notes.append(folder, "third", when=at("2026-10-27 10:00"))
        (folder / "ideas.md").write_text("- not a daily note\n")
        self.assertEqual(
            notes.recent(folder),
            [("2026-10-27", "10:00 third"), ("2026-10-27", "09:00 second"), ("2026-10-26", "09:00 first")],
        )
        self.assertEqual(len(notes.recent(folder, limit=2)), 2)
        self.assertEqual(notes.recent(self.home / "missing"), [])
