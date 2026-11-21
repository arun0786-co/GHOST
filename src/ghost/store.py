"""the database: one sqlite file, ~/.ghost/ghost.db.

it is an index of your sources, so `ghost index` can rebuild nearly all of it.
the exception is the timeline: past changes and deleted files are only
remembered here.

methods that change documents or events do not commit; the caller does, so a
whole batch of files lands at once or not at all.
"""

from __future__ import annotations

import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .util import GhostError, display_path

SCHEMA_VERSION = 1

# snippet() wraps matched words in these. the command line turns them into
# bold text or drops them.
MARK_START, MARK_END = "\x02", "\x03"

# bm25 weights for the text, heading and place (path inside the source) columns.
WEIGHTS = "1.0, 2.0, 2.0"

SCHEMA = """
create table sources (
    id integer primary key,
    name text not null unique,
    kind text not null,                 -- folder | notes
    path text not null,
    added_at real not null,
    indexed_at real
);

create table documents (
    id integer primary key,
    source_id integer not null references sources(id) on delete cascade,
    path text not null,
    size integer not null,
    mtime real not null,
    indexed_at real not null,
    redacted integer not null default 0,
    unique (source_id, path)
);

-- one row per piece of a document. its words are in chunks_fts, same rowid.
create table chunks (
    id integer primary key,
    doc_id integer not null references documents(id) on delete cascade,
    line integer not null               -- first line in the file, 0 when unknown
);
create index chunks_doc on chunks(doc_id);

create virtual table chunks_fts using fts5(
    text, heading, place,
    tokenize = 'porter unicode61 remove_diacritics 2'
);

-- also runs for rows removed by the cascades above.
create trigger chunks_gone after delete on chunks begin
    delete from chunks_fts where rowid = old.id;
end;

create table tasks (
    id integer primary key,
    doc_id integer not null references documents(id) on delete cascade,
    line integer not null,
    text text not null
);
create index tasks_doc on tasks(doc_id);

-- the timeline. `at` is when it happened: file times, or when ghost noticed.
create table events (
    id integer primary key,
    at real not null,
    kind text not null,                 -- created | edited | deleted | note | task
    source_id integer not null references sources(id) on delete cascade,
    path text not null,
    detail text not null default ''
);
create index events_at on events(at);
create index events_source on events(source_id);
"""


@dataclass
class Source:
    id: int
    name: str
    kind: str
    path: str
    added_at: float
    indexed_at: float | None


class Store:
    def __init__(self, path: Path, read_only: bool = False):
        self.path = path
        try:
            if read_only:
                self.db = sqlite3.connect(f"file:{urllib.parse.quote(str(path))}?mode=ro", uri=True, timeout=10)
            else:
                existed = path.exists()
                self.db = sqlite3.connect(path, timeout=10)
                if not existed:
                    path.chmod(0o600)
            self.db.row_factory = sqlite3.Row
            # the default rollback journal, not wal: the index stays one file, and a
            # read-only open (ghost doctor) changes nothing on disk
            self.db.execute("pragma foreign_keys = on")
            self._check_schema(read_only)
        except sqlite3.DatabaseError as exc:
            raise GhostError(f"cannot open {display_path(path)}: {exc}") from None

    def _check_schema(self, read_only: bool) -> None:
        version = self.db.execute("pragma user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise GhostError(f"{display_path(self.path)} was written by a newer ghost (schema {version}, this one knows {SCHEMA_VERSION})")
        if version == SCHEMA_VERSION:
            return
        if read_only:
            raise GhostError(f"{display_path(self.path)} is not set up yet")
        try:
            self.db.executescript(f"begin;\n{SCHEMA}\npragma user_version = {SCHEMA_VERSION};\ncommit;")
        except sqlite3.OperationalError as exc:
            if self.db.in_transaction:
                self.db.rollback()
            if "fts5" in str(exc):
                raise GhostError("this python's sqlite has no fts5, which ghost needs for search") from None
            raise

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()

    # sources

    def sources(self) -> list[Source]:
        return [Source(**dict(row)) for row in self.db.execute("select * from sources order by name")]

    def source(self, name: str) -> Source | None:
        row = self.db.execute("select * from sources where name = ?", (name,)).fetchone()
        return Source(**dict(row)) if row else None

    def notes_source(self) -> Source | None:
        row = self.db.execute("select * from sources where kind = 'notes'").fetchone()
        return Source(**dict(row)) if row else None

    def add_source(self, name: str, kind: str, path: str) -> Source:
        with self.db:
            self.db.execute(
                "insert into sources (name, kind, path, added_at) values (?, ?, ?, ?)",
                (name, kind, path, time.time()),
            )
        source = self.source(name)
        assert source is not None
        return source

    def remove_source(self, source: Source) -> None:
        """the source and everything indexed from it: documents, pieces, tasks and timeline."""
        with self.db:
            self.db.execute("delete from sources where id = ?", (source.id,))

    def mark_indexed(self, source: Source, when: float) -> None:
        self.db.execute("update sources set indexed_at = ? where id = ?", (when, source.id))
        source.indexed_at = when

    # documents

    def documents(self, source: Source) -> dict[str, tuple[int, int, float]]:
        """path -> (id, size, mtime) for every indexed file of a source."""
        rows = self.db.execute("select id, path, size, mtime from documents where source_id = ?", (source.id,))
        return {row["path"]: (row["id"], row["size"], row["mtime"]) for row in rows}

    def put_document(
        self,
        source: Source,
        path: str,
        size: int,
        mtime: float,
        pieces: Iterable[tuple[int, str, str, str]],
        tasks: Iterable[tuple[int, str]],
        redacted: int,
        when: float,
    ) -> int:
        """store one file's pieces (line, heading, place, text) and tasks (line, text), replacing old ones."""
        row = self.db.execute("select id from documents where source_id = ? and path = ?", (source.id, path)).fetchone()
        if row:
            doc_id = row[0]
            self.db.execute(
                "update documents set size = ?, mtime = ?, indexed_at = ?, redacted = ? where id = ?",
                (size, mtime, when, redacted, doc_id),
            )
            self.db.execute("delete from chunks where doc_id = ?", (doc_id,))
            self.db.execute("delete from tasks where doc_id = ?", (doc_id,))
        else:
            doc_id = self.db.execute(
                "insert into documents (source_id, path, size, mtime, indexed_at, redacted) values (?, ?, ?, ?, ?, ?)",
                (source.id, path, size, mtime, when, redacted),
            ).lastrowid
        for line, heading, place, text in pieces:
            chunk_id = self.db.execute("insert into chunks (doc_id, line) values (?, ?)", (doc_id, line)).lastrowid
            self.db.execute(
                "insert into chunks_fts (rowid, text, heading, place) values (?, ?, ?, ?)",
                (chunk_id, text, heading, place),
            )
        self.db.executemany(
            "insert into tasks (doc_id, line, text) values (?, ?, ?)",
            [(doc_id, line, text) for line, text in tasks],
        )
        return doc_id

    def delete_document(self, doc_id: int) -> None:
        self.db.execute("delete from documents where id = ?", (doc_id,))

    def add_event(self, at: float, kind: str, source: Source, path: str, detail: str = "") -> None:
        self.db.execute(
            "insert into events (at, kind, source_id, path, detail) values (?, ?, ?, ?, ?)",
            (at, kind, source.id, path, detail),
        )

    # reading

    def search(
        self,
        match: str,
        limit: int,
        source: Source | None = None,
        since: float | None = None,
        per_doc: int = 1,
    ) -> list[sqlite3.Row]:
        """the best pieces for an fts5 query, at most per_doc from each file.

        bm25() cannot be used inside a window function, so the ranking is
        materialized first and the per-file numbering runs over it.
        """
        filters, params = "", [match]
        if source is not None:
            filters += " and d.source_id = ?"
            params.append(source.id)
        if since is not None:
            filters += " and d.mtime >= ?"
            params.append(since)
        sql = f"""
            with ranked as materialized (
                select c.id, c.doc_id, c.line, d.path, d.mtime, s.name as source, s.path as root,
                       bm25(chunks_fts, {WEIGHTS}) as rank
                from chunks_fts
                join chunks c on c.id = chunks_fts.rowid
                join documents d on d.id = c.doc_id
                join sources s on s.id = d.source_id
                where chunks_fts match ?{filters}
            )
            select * from (
                select *, row_number() over (partition by doc_id order by rank) as nth,
                       count(*) over (partition by doc_id) as hits
                from ranked
            )
            where nth <= ?
            order by rank
            limit ?
        """
        try:
            return self.db.execute(sql, [*params, per_doc, limit]).fetchall()
        except sqlite3.OperationalError as exc:
            raise GhostError(f"cannot search for {match}: {exc}") from None

    def piece(self, match: str, chunk_id: int, words: int = 16) -> tuple[str, str, str]:
        """(snippet, text, heading) of one piece, with the words of the query marked."""
        row = self.db.execute(
            "select snippet(chunks_fts, 0, ?, ?, ' ... ', ?), text, heading from chunks_fts "
            "where chunks_fts match ? and rowid = ?",
            (MARK_START, MARK_END, words, match, chunk_id),
        ).fetchone()
        return (row[0], row[1], row[2]) if row else ("", "", "")

    def tasks(self, source: Source | None = None, words: Sequence[str] = ()) -> list[sqlite3.Row]:
        """open tasks that contain all the words, files changed most recently first."""
        sql = """
            select t.line, t.text, d.path, d.mtime, s.name as source, s.path as root
            from tasks t
            join documents d on d.id = t.doc_id
            join sources s on s.id = d.source_id
            where 1 = 1
        """
        params: list = []
        if source is not None:
            sql += " and s.id = ?"
            params.append(source.id)
        for word in words:
            escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " and t.text like ? escape '\\'"
            params.append(f"%{escaped}%")
        sql += " order by d.mtime desc, d.path, t.line"
        return self.db.execute(sql, params).fetchall()

    def events(
        self,
        start: float,
        end: float | None = None,
        source: Source | None = None,
        limit: int = 5000,
    ) -> list[sqlite3.Row]:
        """timeline events from start (to end), newest first."""
        sql = """
            select e.at, e.kind, e.path, e.detail, s.name as source, s.path as root
            from events e join sources s on s.id = e.source_id
            where e.at >= ?
        """
        params: list = [start]
        if end is not None:
            sql += " and e.at < ?"
            params.append(end)
        if source is not None:
            sql += " and e.source_id = ?"
            params.append(source.id)
        sql += " order by e.at desc, e.id desc limit ?"
        params.append(limit)
        return self.db.execute(sql, params).fetchall()

    def counts(self) -> dict[int, tuple[int, int]]:
        """source id -> (indexed files, open tasks)."""
        files = {row[0]: row[1] for row in self.db.execute("select source_id, count(*) from documents group by source_id")}
        tasks = {
            row[0]: row[1]
            for row in self.db.execute(
                "select d.source_id, count(*) from tasks t join documents d on d.id = t.doc_id group by d.source_id"
            )
        }
        return {sid: (files.get(sid, 0), tasks.get(sid, 0)) for sid in files.keys() | tasks.keys()}

    def totals(self) -> dict[str, int]:
        def one(sql: str) -> int:
            return self.db.execute(sql).fetchone()[0]

        return {
            "files": one("select count(*) from documents"),
            "pieces": one("select count(*) from chunks"),
            "tasks": one("select count(*) from tasks"),
            "events": one("select count(*) from events"),
            "redacted": one("select coalesce(sum(redacted), 0) from documents"),
        }
