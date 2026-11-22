import unittest
from datetime import datetime, timedelta

from support import GhostTestCase

from ghost import timeline
from ghost.util import GhostError, parse_day, parse_since


def at(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


def row(when: str, kind: str, rel: str = "", detail: str = "") -> dict:
    return {"at": at(when), "kind": kind, "path": f"/src/{rel}", "detail": detail, "source": "code", "root": "/src"}


class ByDayTests(unittest.TestCase):
    def test_days_and_folded_bursts(self):
        rows = [
            row("2026-10-27 18:00", "edited", "app/a.py"),
            row("2026-10-27 17:59", "edited", "app/b.py"),
            row("2026-10-27 17:58", "edited", "app/c.py"),
            row("2026-10-27 17:00", "note", detail="lunch with Sam"),
            row("2026-10-27 16:00", "edited", "app/d.py"),
            row("2026-10-27 15:00", "created", "app/e.py"),
            row("2026-10-26 09:00", "edited", "app/f.py"),
        ]
        days = timeline.by_day(rows)
        self.assertEqual([day for day, _ in days], ["tue 27 oct 2026", "mon 26 oct 2026"])
        first = days[0][1]
        self.assertEqual(
            [(line.kind, line.text, line.more) for line in first],
            [("edited", "code/app/a.py", 2), ("note", "lunch with Sam", 0), ("edited", "code/app/d.py", 0), ("created", "code/app/e.py", 0)],
        )
        self.assertEqual(first[0].folder, "code/app")
        self.assertEqual([line.text for line in days[1][1]], ["code/app/f.py"])

    def test_notes_are_never_folded(self):
        rows = [row("2026-10-27 10:00", "note", detail="one"), row("2026-10-27 09:00", "note", detail="two")]
        self.assertEqual([line.text for line in timeline.by_day(rows)[0][1]], ["one", "two"])


class TimeParsingTests(unittest.TestCase):
    now = at("2026-10-27 15:30")  # a tuesday

    def test_spans(self):
        self.assertEqual(parse_since("3d", self.now), self.now - 3 * 86400)
        self.assertEqual(parse_since("12h", self.now), self.now - 12 * 3600)
        self.assertEqual(parse_since("2w", self.now), self.now - 14 * 86400)
        self.assertEqual(parse_since("30m", self.now), self.now - 1800)

    def test_days(self):
        self.assertEqual(parse_day("today", self.now), (at("2026-10-27 00:00"), at("2026-10-28 00:00")))
        self.assertEqual(parse_day("yesterday", self.now)[0], at("2026-10-26 00:00"))
        self.assertEqual(parse_day("monday", self.now)[0], at("2026-10-26 00:00"))
        self.assertEqual(parse_day("tue", self.now)[0], at("2026-10-27 00:00"))
        self.assertEqual(parse_day("wednesday", self.now)[0], at("2026-10-21 00:00"))
        self.assertEqual(parse_day("2026-10-01", self.now)[0], at("2026-10-01 00:00"))
        self.assertEqual(parse_since("yesterday", self.now), at("2026-10-26 00:00"))

    def test_nonsense_is_refused(self):
        for text in ("soon", "mo", "3 years", "2026-13-01"):
            with self.subTest(text=text), self.assertRaises(GhostError):
                parse_since(text, self.now)


class TimelineCommandTests(GhostTestCase):
    def test_changes_by_day(self):
        recent = (datetime.now() - timedelta(hours=1)).replace(second=0, microsecond=0)
        older = recent - timedelta(days=2)
        for name in ("a", "b", "c"):
            self.write(f"code/app/{name}.py", "x = 1\n", mtime=recent.timestamp())
        self.write("code/docs/plan.md", "plan\n", mtime=older.timestamp())
        self.ok("add", str(self.home / "code"))
        out = self.ok("timeline", "--since", "7d")
        self.assertIn(older.strftime("%a %d %b %Y").lower(), out)
        self.assertIn(recent.strftime("%H:%M"), out)
        self.assertIn("(+2 more in code/app)", out)
        self.assertIn("code/docs/plan.md", out)

        one_day = self.ok("timeline", "--day", older.strftime("%Y-%m-%d"))
        self.assertIn("plan.md", one_day)
        self.assertNotIn("code/app", one_day)

        self.assertIn("older events are hidden", self.ok("timeline", "-n", "1"))
        self.assertIn("nothing on the timeline", self.ok("timeline", "--since", "1m"))
