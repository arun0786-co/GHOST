"""indexing: bring the database up to date with the files in a source.

a file is read again only when its size or modification time changed. what
changed goes on the timeline: created and edited at the times the file system
reports, deleted at the time ghost noticed.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from . import chunks, files, gitlog
from .config import Config
from .redact import redact
from .store import Source, Store
from .util import GhostError

COMMIT_EVERY = 200
PROGRESS_EVERY = 500


@dataclass
class Report:
    source: str
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    deleted: int = 0  # gone from disk
    dropped: int = 0  # still on disk, but now skipped (binary, too big, ignored)
    binary: int = 0
    unreadable_files: int = 0
    too_big: int = 0
    redacted: int = 0
    unreadable: list[str] = field(default_factory=list)  # folders that could not be listed
    missing: bool = False
    seconds: float = 0.0

    @property
    def seen(self) -> int:
        return self.new + self.changed + self.unchanged


def index_source(
    store: Store,
    source: Source,
    config: Config,
    progress: Callable[[Report, int], None] | None = None,
    now: float | None = None,
) -> Report:
    started = time.monotonic()
    now = time.time() if now is None else now
    report = Report(source.name)
    if not os.path.isdir(source.path):
        # an unplugged drive should not wipe its index
        report.missing = True
        return report
    if source.kind == "git":
        gitlog.index(store, source, report, now)
        return report
    rules = files.load_rules(source.path, config.skip, config.max_file_kb * 1024, config.extra_types)
    walk = files.WalkReport()
    known = store.documents(source)
    kept: set[str] = set()
    timeline = source.kind != "notes"  # notes get their own events from `ghost remember`
    first_run = source.indexed_at is None
    looked = pending = 0
    try:
        for path, info in files.walk(source.path, rules, walk):
            looked += 1
            if progress and looked % PROGRESS_EVERY == 0:
                progress(report, looked)
            old = known.get(path)
            if old is not None and old[1] == info.st_size and old[2] == info.st_mtime:
                kept.add(path)
                report.unchanged += 1
                continue
            try:
                with open(path, "rb") as fh:
                    data = fh.read(rules.max_bytes)
            except OSError:
                report.unreadable_files += 1
                if old is not None:
                    kept.add(path)
                continue
            text = files.read_text(path, data)
            if text is None:
                report.binary += 1
                continue
            body, found = redact(text.body)
            place = os.path.relpath(path, source.path)
            pieces = [
                (piece.line if text.has_lines else 0, piece.heading, place, piece.text)
                for piece in chunks.split(body, text.markdown)
            ]
            todo = [(task.line if text.has_lines else 0, task.text) for task in chunks.tasks(body, text.markdown)]
            store.put_document(source, path, info.st_size, info.st_mtime, pieces, todo, found, now)
            kept.add(path)
            report.redacted += found
            if old is None:
                report.new += 1
            else:
                report.changed += 1
            if timeline:
                record_change(store, source, path, info, old is None, first_run)
            pending += 1
            if pending >= COMMIT_EVERY:
                store.commit()
                pending = 0

        report.too_big, report.unreadable = walk.too_big, walk.unreadable
        for path, (doc_id, _, _) in known.items():
            if path in kept or any(path.startswith(folder + os.sep) for folder in walk.unreadable):
                continue
            store.delete_document(doc_id)
            if is_gone(path):
                report.deleted += 1
                if timeline:
                    store.add_event(now, "deleted", source, path)
            else:
                report.dropped += 1
        store.mark_indexed(source, now)
        store.commit()
    except BaseException:
        store.rollback()
        raise
    report.seconds = time.monotonic() - started
    return report


def record_change(store: Store, source: Source, path: str, info: os.stat_result, new: bool, first_run: bool) -> None:
    """timeline events for a new or changed file, at the times the file system gives.

    on the first run a file without a birth time (most linux file systems)
    only says when it was last edited, not that it was created then.
    """
    born = getattr(info, "st_birthtime", None)
    if new and (born is not None or not first_run):
        created = born if born is not None else info.st_mtime
        store.add_event(created, "created", source, path)
        if info.st_mtime - created > 60:
            store.add_event(info.st_mtime, "edited", source, path)
    else:
        store.add_event(info.st_mtime, "edited", source, path)


def is_gone(path: str) -> bool:
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False
    return False


def pick_sources(store: Store, names: Sequence[str] = ()) -> list[Source]:
    """the sources with these names, or all of them."""
    sources = store.sources()
    if not names:
        return sources
    by_name = {source.name: source for source in sources}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise GhostError(f"no source called {', '.join(unknown)}. ghost sources lists them")
    return [by_name[name] for name in dict.fromkeys(names)]
