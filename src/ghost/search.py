"""ghost search: what you type becomes an fts5 query of quoted words, so
punctuation cannot break it. every word has to match; when no file has them
all, files with any of them are shown instead."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .store import Source, Store
from .util import GhostError

TOKEN = re.compile(r'"([^"]*)"|(\w+)(\*?)')


@dataclass
class Hit:
    path: str
    line: int
    source: str
    root: str
    mtime: float
    snippet: str
    text: str
    heading: str
    more: int  # other matching pieces in the same file


def terms(query: str) -> list[str]:
    """words, prefixes (word*) and "quoted phrases", as fts5 strings."""
    found = []
    for phrase, word, star in TOKEN.findall(query):
        if word:
            found.append(f'"{word}"{star}')
        else:
            words = re.findall(r"\w+", phrase)
            if words:
                found.append('"' + " ".join(words) + '"')
    return list(dict.fromkeys(found))


def hits(
    store: Store,
    match: str,
    limit: int,
    source: Source | None = None,
    since: float | None = None,
    per_doc: int = 1,
) -> list[Hit]:
    found = []
    for row in store.search(match, limit, source, since, per_doc):
        snippet, text, heading = store.piece(match, row["id"])
        found.append(
            Hit(row["path"], row["line"], row["source"], row["root"], row["mtime"], snippet, text, heading, row["hits"] - 1)
        )
    return found


def search(
    store: Store,
    query: str,
    limit: int = 10,
    source: Source | None = None,
    since: float | None = None,
) -> tuple[list[Hit], bool]:
    """the best matching files, and whether only some of the words matched."""
    parts = terms(query)
    if not parts:
        raise GhostError("nothing to search for")
    found = hits(store, " ".join(parts), limit, source, since)
    if found or len(parts) == 1:
        return found, False
    return hits(store, " OR ".join(parts), limit, source, since), True
