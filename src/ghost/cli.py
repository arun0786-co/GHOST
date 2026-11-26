"""ghost command line."""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

from . import __version__, ask, doctor, gitlog, indexer, model, notes, search, timeline
from . import config as config_mod
from .config import Config
from .redact import redact
from .store import MARK_END, MARK_START, Source, Store
from .util import GhostError, ago, clock, display_path, parse_day, parse_since, plural

NAME = re.compile(r"[\w.-]+")
BOLD, DIM, RESET = "\x1b[1m", "\x1b[2m", "\x1b[0m"


def color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


def paint(text: str, style: str) -> str:
    return f"{style}{text}{RESET}" if color() else text


def marked(snippet: str) -> str:
    """a snippet on one line, the matched words in bold when the terminal can show it."""
    flat = " ".join(snippet.split())
    if color():
        return flat.replace(MARK_START, BOLD).replace(MARK_END, RESET)
    return flat.replace(MARK_START, "").replace(MARK_END, "")


def indented(text: str, limit: int) -> str:
    cut = text[:limit].rstrip() + (" ..." if len(text) > limit else "")
    return "\n".join("    " + line for line in cut.splitlines() if line.strip())


def table(rows: list[tuple[str, ...]], right: frozenset[int] = frozenset()) -> list[str]:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return [
        "  ".join(cell.rjust(width) if i in right else cell.ljust(width) for i, (cell, width) in enumerate(zip(row, widths))).rstrip()
        for row in rows
    ]


def positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number of 1 or more")
    return value


def open_store(config: Config) -> Store:
    config_mod.ensure_home(config)
    return Store(config.db_path)


def existing_store(config: Config) -> Store:
    if not config.db_path.exists():
        raise GhostError("nothing indexed yet. add a folder with: ghost add FOLDER")
    return Store(config.db_path)


def named_source(store: Store, name: str | None) -> Source | None:
    if not name:
        return None
    source = store.source(name)
    if source is None:
        raise GhostError(f"no source called {name}. ghost sources lists them")
    return source


def describe(report: indexer.Report) -> list[str]:
    if report.missing:
        return [f"{report.source}: the folder is missing, so its index was kept as it was"]
    counts = [
        f"{n} {word}"
        for n, word in ((report.new, "new"), (report.changed, "changed"), (report.deleted, "deleted"), (report.unchanged, "unchanged"))
        if n
    ]
    lines = [f"{report.source}: {', '.join(counts) or 'no files to index'} ({report.seconds:.1f}s)"]
    skipped = [
        f"{n} {why}"
        for n, why in (
            (report.binary, "binary"),
            (report.too_big, "over the size limit"),
            (report.unreadable_files, "unreadable"),
            (report.dropped, "no longer indexed"),
        )
        if n
    ]
    if skipped:
        lines.append("  skipped files: " + ", ".join(skipped))
    if report.redacted:
        lines.append(f"  blanked {plural(report.redacted, 'secret-like string')} in the index. your files are unchanged")
    if report.unreadable:
        lines.append(
            f"  could not open {plural(len(report.unreadable), 'folder')}, for example "
            f"{display_path(report.unreadable[0])}. what was indexed from there is kept"
        )
        if sys.platform == "darwin":
            lines.append("  on macOS, allow your terminal in System Settings > Privacy & Security > Files & Folders")
    return lines


def run_index(store: Store, config: Config, sources: Sequence[Source]) -> int:
    """index each source in turn. one that fails is reported and the rest still run."""
    live = sys.stderr.isatty()
    code = 0

    def progress(report: indexer.Report, looked: int) -> None:
        sys.stderr.write(f"\r{report.source}: looked at {looked} files")
        sys.stderr.flush()

    for source in sources:
        try:
            report = indexer.index_source(store, source, config, progress if live else None)
        except GhostError as exc:
            print(f"ghost: error: {source.name}: {exc}", file=sys.stderr)
            code = exc.code
            continue
        finally:
            if live:
                sys.stderr.write("\r\x1b[K")
        for line in describe(report):
            print(line)
    return code


class AnswerPrinter:
    """prints a streamed answer as it comes, without the blank lines models often start with."""

    def __init__(self) -> None:
        self.started = False

    def __call__(self, text: str) -> None:
        if not self.started:
            text = text.lstrip()
            if not text:
                return
            self.started = True
        sys.stdout.write(text)
        sys.stdout.flush()


# commands


def cmd_doctor(args: argparse.Namespace, config: Config) -> int:
    results = doctor.run(config)
    for level, message in results:
        print(f"{level:<4}  {message}")
    return 1 if any(level == doctor.FAIL for level, _ in results) else 0


def cmd_add(args: argparse.Namespace, config: Config) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        raise GhostError(f"{display_path(path)} is not a folder")
    home = config.home.expanduser().resolve()
    if path == home or home in path.parents:
        raise GhostError(f"{display_path(path)} is ghost's own folder")
    if args.git:
        path = Path(gitlog.top(str(path))).resolve()
    name = args.name or (re.sub(r"[^\w.-]+", "-", path.name).strip("-") or "folder") + ("-git" if args.git else "")
    if not NAME.fullmatch(name):
        raise GhostError("a source name can only have letters, digits, '.', '-' and '_'")
    with open_store(config) as store:
        sources = store.sources()
        for other in sources:
            if Path(other.path) == path and (other.kind == "git") == args.git:
                raise GhostError(f"{display_path(path)} is already a source, called {other.name}")
            if other.name == name:
                raise GhostError(f"there is already a source called {name} ({display_path(other.path)}). pick another name with --name")
        source = store.add_source(name, "git" if args.git else "folder", str(path))
        print(f"added {name}: {display_path(path)}")
        for other in sources:
            if args.git or other.kind == "git":
                continue
            if Path(other.path) in path.parents or path in Path(other.path).parents:
                print(f"  it overlaps with {other.name} ({display_path(other.path)}), so some files are indexed twice")
        if args.no_index:
            print(f"index it with: ghost index {name}")
            return 0
        return run_index(store, config, [source])


def cmd_sources(args: argparse.Namespace, config: Config) -> int:
    sources: list[Source] = []
    counts: dict[int, tuple[int, int]] = {}
    if config.db_path.exists():
        with Store(config.db_path) as store:
            sources, counts = store.sources(), store.counts()
    if not sources:
        print("no sources yet. add a folder with: ghost add FOLDER")
        return 0
    rows = [("name", "files", "tasks", "indexed", "path")]
    for source in sources:
        files, tasks = counts.get(source.id, (0, 0))
        indexed = ago(source.indexed_at) if source.indexed_at else "never"
        rows.append((source.name, str(files), str(tasks), indexed, display_path(source.path)))
    for line in table(rows, right=frozenset({1, 2})):
        print(line)
    return 0


def cmd_remove(args: argparse.Namespace, config: Config) -> int:
    with existing_store(config) as store:
        source = named_source(store, args.name)
        assert source is not None
        store.remove_source(source)
    print(f"removed {source.name}: its index, tasks and timeline are gone. nothing in {display_path(source.path)} was touched")
    return 0


def cmd_index(args: argparse.Namespace, config: Config) -> int:
    with open_store(config) as store:
        sources = indexer.pick_sources(store, args.names)
        if not sources:
            print("nothing to index yet. add a folder with: ghost add FOLDER")
            return 0
        return run_index(store, config, sources)


def cmd_search(args: argparse.Namespace, config: Config) -> int:
    since = parse_since(args.since) if args.since else None
    with existing_store(config) as store:
        found, loose = search.search(store, " ".join(args.words), args.limit, named_source(store, args.source), since)
    if not found:
        print("no matches")
        return 1
    if loose:
        print("no file has all of those words. these have some of them:\n")
    for hit in found:
        where = display_path(hit.path) + (f":{hit.line}" if hit.line else "")
        about = f"{hit.source}, changed {ago(hit.mtime)}"
        if hit.more:
            about += f", {plural(hit.more, 'more match', 'more matches')} in this file"
        print(f"{paint(where, BOLD)}  {paint(about, DIM)}")
        print(f"    {marked(hit.snippet)}")
    return 0


def cmd_ask(args: argparse.Namespace, config: Config) -> int:
    question = " ".join(args.question).strip()
    with existing_store(config) as store:
        found = ask.passages(store, question, named_source(store, args.source))
    if not found:
        print("nothing in your sources matches that question. for questions about when things happened, try ghost timeline")
        return 1
    server = None if args.no_model else model.find(config.model_url, args.model or config.model_name)
    if server is None or not server.name:
        if not args.no_model:
            reason = (
                "no model server found on this machine"
                if server is None
                else f"the {model.API_NAMES[server.api]} at {server.url} has no local models"
            )
            print(f"{reason} (ghost doctor says more), so here are the passages that match best:\n")
        for passage in found:
            print(paint(f"[{passage.number}] {passage.where}", BOLD))
            print(indented(passage.text, 600))
        return 0
    printer = AnswerPrinter()
    answer = model.chat(server, ask.prompt(question, found), config.model_timeout, printer)
    print("\n" if printer.started else "the model gave an empty answer\n")
    for passage in ask.cited(answer, found):
        print(paint(f"[{passage.number}] {passage.where}", DIM))
    return 0


def cmd_remember(args: argparse.Namespace, config: Config) -> int:
    text = " ".join(" ".join(args.text).split())
    with open_store(config) as store:
        path = notes.append(config.notes_dir, text, todo=args.todo)
        source = store.notes_source()
        if source is None:
            name = "notes" if store.source("notes") is None else "ghost-notes"
            source = store.add_source(name, "notes", str(config.notes_dir))
        store.add_event(time.time(), "task" if args.todo else "note", source, str(path), redact(text)[0])
        store.commit()
        indexer.index_source(store, source, config)
    print(f"saved to {display_path(path)}")
    return 0


def cmd_notes(args: argparse.Namespace, config: Config) -> int:
    items = notes.recent(config.notes_dir, args.limit)
    if not items:
        print("no notes yet. add one with: ghost remember TEXT")
        return 0
    for day, text in items:
        print(f"{paint(day, DIM)}  {text}")
    print(f"\nnotes are in {display_path(config.notes_dir)}, one file a day. edit or delete them there")
    return 0


def cmd_todo(args: argparse.Namespace, config: Config) -> int:
    with existing_store(config) as store:
        rows = store.tasks(named_source(store, args.source), args.words)
    if not rows:
        print("no open tasks found")
        return 0
    shown = rows[: args.limit]
    current = None
    for row in shown:
        if row["path"] != current:
            if current is not None:
                print()
            current = row["path"]
            print(f"{paint(display_path(current), BOLD)}  {paint('changed ' + ago(row['mtime']), DIM)}")
        line = str(row["line"]) if row["line"] else ""
        print(f"  {line:>5}  {row['text']}")
    files = len({row["path"] for row in rows})
    summary = f"\n{plural(len(rows), 'open task')} in {plural(files, 'file')}"
    if len(shown) < len(rows):
        summary += f", showing the first {len(shown)} (-n for more)"
    print(summary)
    return 0


def cmd_timeline(args: argparse.Namespace, config: Config) -> int:
    if args.day:
        start, end = parse_day(args.day)
    else:
        start, end = parse_since(args.since), None
    with existing_store(config) as store:
        rows = store.events(start, end, named_source(store, args.source))
    days = timeline.by_day(rows)
    if not days:
        print("nothing on the timeline for that time. ghost sees file changes when ghost index runs")
        return 0
    printed = 0
    for number, (day, lines) in enumerate(days):
        if printed == args.limit:
            print("\nolder events are hidden (-n for more)")
            break
        print(("\n" if number else "") + paint(day, BOLD))
        for line in lines:
            if printed == args.limit:
                print("\nolder events are hidden (-n for more)")
                return 0
            extra = f"  (+{line.more} more in {line.folder})" if line.more else ""
            print(f"  {clock(line.at)}  {line.kind:<8} {line.text}{extra}")
            printed += 1
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace, Config], int]] = {
    "doctor": cmd_doctor,
    "add": cmd_add,
    "sources": cmd_sources,
    "remove": cmd_remove,
    "index": cmd_index,
    "search": cmd_search,
    "ask": cmd_ask,
    "remember": cmd_remember,
    "notes": cmd_notes,
    "todo": cmd_todo,
    "timeline": cmd_timeline,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghost",
        description=(
            "GHOST (General-purpose Human-Owned Offline System Twin): search, questions, open tasks "
            "and a timeline over your own files and notes. nothing leaves this machine."
        ),
    )
    parser.add_argument("--version", action="version", version=f"ghost {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("doctor", help="what works on this machine (read only)")

    p = sub.add_parser("add", help="add a folder and index it")
    p.add_argument("path")
    p.add_argument("--name", help="what to call it (default: the folder's name)")
    p.add_argument("--git", action="store_true", help="the commit messages of the git repository there, instead of its files")
    p.add_argument("--no-index", action="store_true", help="add it now, index it later")

    sub.add_parser("sources", help="the folders ghost reads")

    p = sub.add_parser("remove", help="forget a source and its index (its files are not touched)")
    p.add_argument("name")

    p = sub.add_parser("index", help="pick up new, changed and deleted files")
    p.add_argument("names", nargs="*", metavar="NAME", help="only these sources")

    p = sub.add_parser("search", help="search your files and notes")
    p.add_argument("words", nargs="+", metavar="WORD", help='words, prefixes like "invoi*", or "a phrase"')
    p.add_argument("-n", "--limit", type=positive, default=10, help="how many files to show (default 10)")
    p.add_argument("--source", help="only this source")
    p.add_argument("--since", help="only files changed since: 3d, 2w, yesterday, 2026-10-01")

    p = sub.add_parser("ask", help="answer a question from your files, with a model on this machine")
    p.add_argument("question", nargs="+")
    p.add_argument("--source", help="only this source")
    p.add_argument("--model", help="which model on the local server")
    p.add_argument("--no-model", action="store_true", help="only show the passages that match")

    p = sub.add_parser("remember", help="save a note, or an open task with --todo")
    p.add_argument("text", nargs="+")
    p.add_argument("--todo", action="store_true", help="save it as an open task")

    p = sub.add_parser("notes", help="your latest notes")
    p.add_argument("-n", "--limit", type=positive, default=20)

    p = sub.add_parser("todo", help="open tasks from your files and notes")
    p.add_argument("words", nargs="*", metavar="WORD", help="only tasks with all these words")
    p.add_argument("--source", help="only this source")
    p.add_argument("-n", "--limit", type=positive, default=100)

    p = sub.add_parser("timeline", help="what changed when")
    p.add_argument("--since", default="7d", help="how far back: 12h, 3d, 2w, monday, 2026-10-01 (default 7d)")
    p.add_argument("--day", help="one day instead: today, yesterday, tuesday, 2026-10-20")
    p.add_argument("--source", help="only this source")
    p.add_argument("-n", "--limit", type=positive, default=100, help="how many lines (default 100)")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        raise SystemExit(0)
    try:
        code = COMMANDS[args.command](args, config_mod.load())
    except GhostError as exc:
        print(f"ghost: error: {exc}", file=sys.stderr)
        code = exc.code
    except KeyboardInterrupt:
        print("ghost: interrupted", file=sys.stderr)
        code = 130
    except BrokenPipeError:
        # the reader went away (ghost search ... | head); stop quietly
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        code = 141
    raise SystemExit(code)
