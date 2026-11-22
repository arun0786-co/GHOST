"""cutting text into searchable pieces, and finding the open tasks in it."""

from __future__ import annotations

import re
from dataclasses import dataclass

CHUNK_CHARS = 1200

HEADING = re.compile(r"(#{1,6})\s+(.+?)\s*#*\s*")
FENCE = re.compile(r"\s{0,3}(```|~~~)")
# "- [ ] call the bank", "1. [ ] ...". done items ("[x]") are not tasks.
CHECKBOX = re.compile(r"\s*(?:[-*+]|\d+[.)])\s+\[ \]\s+(\S.*)")
# "TODO: ...", "FIXME ...", "TODO(name): ...". upper case only, so words like
# "todo_list" in code do not count.
MARKER = re.compile(r"\b(?:TODO|FIXME)\b(?:\([^)]*\))?[:\s]\s*(\S.*)")
# comment closers left at the end of a TODO line.
CLOSERS = re.compile(r"\s*(?:\*/|-->|%>|#\}|\}\})\s*$")


@dataclass
class Chunk:
    line: int  # first line, counted from 1
    heading: str  # the markdown heading this piece sits under, or ""
    text: str


@dataclass
class Task:
    line: int
    text: str


def split(text: str, markdown: bool, size: int = CHUNK_CHARS) -> list[Chunk]:
    """pieces of about `size` characters, cut at headings and else at blank lines."""
    chunks: list[Chunk] = []
    lines: list[str] = []
    start, length, heading, fenced = 1, 0, "", False

    def flush() -> None:
        nonlocal lines, length
        body = "\n".join(lines).strip()
        if body:
            chunks.append(Chunk(start, heading, body))
        lines, length = [], 0

    for number, line in enumerate(text.split("\n"), 1):
        if markdown and FENCE.match(line):
            fenced = not fenced
        elif markdown and not fenced:
            match = HEADING.fullmatch(line)
            if match:
                flush()
                heading = match.group(2)
        if not lines:
            if not line.strip():
                continue
            start = number
        lines.append(line)
        length += len(line) + 1
        # wait for a blank line to cut at, but not forever
        if length >= size and (not line.strip() or length >= size * 3 // 2):
            flush()
    flush()
    return chunks


def tasks(text: str, markdown: bool) -> list[Task]:
    """open checkboxes and TODO / FIXME lines, outside markdown code blocks."""
    found = []
    fenced = False
    for number, line in enumerate(text.split("\n"), 1):
        if markdown and FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = CHECKBOX.fullmatch(line) or MARKER.search(line)
        if match:
            item = CLOSERS.sub("", match.group(1)).strip()
            if item:
                found.append(Task(number, item[:200]))
    return found
