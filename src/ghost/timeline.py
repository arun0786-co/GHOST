"""ghost timeline: the events that indexing and notes leave, by day, with a
burst of changes in one folder folded into one line."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from .util import day_label

FILE_KINDS = frozenset({"created", "edited", "deleted"})


@dataclass
class Line:
    at: float
    kind: str
    text: str
    folder: str = ""
    more: int = 0  # folded events: same kind, same folder, right after each other


def describe(row: Mapping) -> tuple[str, str]:
    """what to show for one event, and the folder it happened in."""
    if row["kind"] == "commit":
        return f"{row['source']}: {row['detail']}", ""
    if row["kind"] not in FILE_KINDS:
        return row["detail"], ""
    shown = f"{row['source']}/{os.path.relpath(row['path'], row['root'])}"
    return shown, os.path.dirname(shown)


def by_day(rows: Iterable[Mapping]) -> list[tuple[str, list[Line]]]:
    """newest first rows -> [(day label, lines)], newest first."""
    days: list[tuple[str, list[Line]]] = []
    current = None
    for row in rows:
        day = datetime.fromtimestamp(row["at"]).date()
        if day != current:
            current = day
            days.append((day_label(row["at"]), []))
        lines = days[-1][1]
        text, folder = describe(row)
        last = lines[-1] if lines else None
        if last and row["kind"] in FILE_KINDS and last.kind == row["kind"] and last.folder == folder:
            last.more += 1
        else:
            lines.append(Line(row["at"], row["kind"], text, folder))
    return days
