"""ghost remember: notes are plain markdown, one file a day in ~/.ghost/notes.

open them in any editor to change or delete them. ghost reads them back like
any other source.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from .util import GhostError

DAY_FILE = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md"


def append(folder: Path, text: str, todo: bool = False, when: float | None = None) -> Path:
    """add a note, or an open task with todo=True, to that day's file."""
    text = " ".join(text.split())
    if not text:
        raise GhostError("the note is empty")
    stamp = datetime.fromtimestamp(time.time() if when is None else when)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / f"{stamp:%Y-%m-%d}.md"
    if path.exists():
        current = path.read_bytes()
        prefix = "\n" if current and not current.endswith(b"\n") else ""
    else:
        prefix = f"# {stamp:%Y-%m-%d}\n\n"
    entry = f"- [ ] {text}" if todo else f"- {stamp:%H:%M} {text}"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{prefix}{entry}\n")
    return path


def recent(folder: Path, limit: int = 20) -> list[tuple[str, str]]:
    """the newest list items in the daily files, as (day, text), newest first."""
    found: list[tuple[str, str]] = []
    for path in sorted(folder.glob(DAY_FILE), reverse=True):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if line.startswith(("- ", "* ")):
                found.append((path.stem, line[2:].strip()))
                if len(found) >= limit:
                    return found
    return found
