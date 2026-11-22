"""ghost doctor: read-only checks of python, sqlite, the ghost folder, every
source and the local model. it never writes anything."""

from __future__ import annotations

import os
import platform
import sqlite3
import sys
from typing import Callable

from . import model
from .config import Config
from .store import Source, Store
from .util import GhostError, ago, display_path, human_size, plural

OK, WARN, FAIL = "ok", "warn", "FAIL"


def has_fts5() -> bool:
    db = sqlite3.connect(":memory:")
    try:
        db.execute("create virtual table probe using fts5(text)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        db.close()


def run(config: Config) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    def add(level: str, message: str) -> None:
        results.append((level, message))

    add(OK if sys.version_info >= (3, 11) else FAIL, f"python {platform.python_version()}")
    if has_fts5():
        add(OK, f"sqlite {sqlite3.sqlite_version} with full-text search")
    else:
        add(FAIL, f"sqlite {sqlite3.sqlite_version} has no fts5, which search needs. use a python from python.org or homebrew")

    home = config.home
    if not home.is_dir():
        add(WARN, f"{display_path(home)} does not exist yet. ghost add FOLDER or ghost remember TEXT creates it")
    else:
        mode = home.stat().st_mode & 0o777
        if mode & 0o077:
            add(WARN, f"{display_path(home)} can be read by other users of this computer (mode {mode:o}). chmod 700 {display_path(home)}")
        else:
            add(OK, f"{display_path(home)} is readable only by you")
        check_index(config, add)

    check_model(config, add)
    return results


def check_index(config: Config, add: Callable[[str, str], None]) -> None:
    if not config.db_path.exists():
        add(WARN, "nothing indexed yet. ghost add FOLDER")
        return
    try:
        store = Store(config.db_path, read_only=True)
    except GhostError as exc:
        add(FAIL, str(exc))
        return
    with store:
        totals, counts = store.totals(), store.counts()
        size = config.db_path.stat().st_size
        line = (
            f"index: {plural(totals['files'], 'file')}, {plural(totals['tasks'], 'open task')}, "
            f"{plural(totals['events'], 'timeline event')}, {human_size(size)}"
        )
        if totals["redacted"]:
            line += f", {plural(totals['redacted'], 'secret-like string')} blanked"
        add(OK, line)
        sources = store.sources()
        if not sources:
            add(WARN, "no sources. ghost add FOLDER")
        for source in sources:
            check_source(source, counts.get(source.id, (0, 0)), add)


def check_source(source: Source, counts: tuple[int, int], add: Callable[[str, str], None]) -> None:
    label = f"{source.name} ({display_path(source.path)})"
    if not os.path.isdir(source.path):
        add(WARN, f"{label} is missing. an unplugged drive? its index stays until ghost remove {source.name}")
        return
    try:
        with os.scandir(source.path) as it:
            next(it, None)
    except PermissionError:
        add(WARN, f"{label} cannot be read. on macOS, allow your terminal in System Settings > Privacy & Security > Files & Folders")
        return
    if source.indexed_at is None:
        add(WARN, f"{label} is not indexed yet. ghost index {source.name}")
        return
    files, tasks = counts
    add(OK, f"{label}: {plural(files, 'file')}, {plural(tasks, 'open task')}, indexed {ago(source.indexed_at)}")


def check_model(config: Config, add: Callable[[str, str], None]) -> None:
    try:
        found = model.find(config.model_url, config.model_name)
    except GhostError as exc:
        add(FAIL, str(exc))
        return
    if found is None:
        where = config.model_url or "127.0.0.1:11434 (ollama), :1234 (lm studio) or :8080 (llama.cpp)"
        add(WARN, f"no model server at {where}. search, todo and timeline work without one; ghost ask needs one, for example ollama (https://ollama.com) and a model pulled with it")
    elif not found.name:
        add(WARN, f"the {model.API_NAMES[found.api]} at {found.url} has no models yet")
    else:
        add(OK, f"model {found.name} on the {model.API_NAMES[found.api]} at {found.url}")
