"""ghost ask: find the passages that fit a question best and, when a model runs
on this machine, have it answer from those passages only, citing them."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from . import search
from .store import Source, Store
from .util import display_path

MAX_PASSAGES = 6
PER_FILE = 2
PASSAGE_CHARS = 1500
BUDGET_CHARS = 7000  # about 2000 tokens, so small local models stay quick

STOPWORDS = frozenset(
    """
    a about after again all also am an and any are as at be been before being but by can could did do
    does doing done for from get got had has have how i if in into is it its just like me my myself no
    not now of on once only or other our out over own same she should so some such tell than that the
    their them then there these they this those through to too under until up very was we were what
    when where which while who whom why will with would you your yours
    """.split()
)

SYSTEM = (
    "You answer questions about the user's own files and notes, using only the numbered passages "
    "you are given. Cite the passages you use like [1] or [2][3]. If the passages do not answer the "
    "question, say so plainly instead of guessing. Keep the answer short. Today is {today}."
)


@dataclass
class Passage:
    number: int
    path: str
    line: int
    mtime: float
    text: str

    @property
    def where(self) -> str:
        return display_path(self.path) + (f":{self.line}" if self.line else "")


def keywords(question: str) -> list[str]:
    words = re.findall(r"\w+", question.lower())
    kept = [word for word in words if word not in STOPWORDS and len(word) > 1]
    return list(dict.fromkeys(kept or words))


def passages(store: Store, question: str, source: Source | None = None) -> list[Passage]:
    """the best pieces for any of the question's words, at most PER_FILE from one file."""
    words = keywords(question)
    if not words:
        return []
    match = " OR ".join(f'"{word}"' for word in words)
    found: list[Passage] = []
    used = 0
    for hit in search.hits(store, match, MAX_PASSAGES * 2, source, per_doc=PER_FILE):
        text = hit.text[:PASSAGE_CHARS]
        if found and used + len(text) > BUDGET_CHARS:
            break
        found.append(Passage(len(found) + 1, hit.path, hit.line, hit.mtime, text))
        used += len(text)
        if len(found) == MAX_PASSAGES:
            break
    return found


def prompt(question: str, found: list[Passage], now: datetime | None = None) -> list[dict]:
    today = (now or datetime.now()).strftime("%A %d %B %Y")
    blocks = [
        f"[{p.number}] {p.where} (changed {datetime.fromtimestamp(p.mtime):%Y-%m-%d})\n{p.text}" for p in found
    ]
    user = "Passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
    return [{"role": "system", "content": SYSTEM.format(today=today)}, {"role": "user", "content": user}]


def cited(answer: str, found: list[Passage]) -> list[Passage]:
    """the passages the answer cites, or all of them when it cites none."""
    numbers = {int(n) for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", answer) for n in group.split(",")}
    chosen = [p for p in found if p.number in numbers]
    return chosen or found
