"""git history as a source: the commit messages of one repository.

only messages are read, never file contents or diffs. git runs with settings
that stop it from starting other programs, asking for a password or fetching
anything from a remote.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

from . import chunks
from .redact import redact
from .store import Source, Store
from .util import GhostError, display_path

TIMEOUT = 120
SHORT = 12  # how much of the commit id is kept


@dataclass
class Commit:
    sha: str
    at: float
    author: str
    message: str

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0]


def environment() -> dict[str, str]:
    """the environment without GIT_* (GIT_DIR would point git at another repository), and no network."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_ALLOW_PROTOCOL="none",  # no transport has this name, so every fetch is refused
        GIT_NO_LAZY_FETCH="1",  # partial clones
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return env


def run(path: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "--no-pager", "-C", path, *args],
            stdin=subprocess.DEVNULL, capture_output=True, env=environment(), timeout=TIMEOUT,
        )
    except FileNotFoundError:
        raise GhostError("git is not installed") from None
    except subprocess.TimeoutExpired:
        raise GhostError(f"git took more than {TIMEOUT}s in {display_path(path)}") from None


def checked(path: str, *args: str) -> str:
    done = run(path, *args)
    if done.returncode:
        lines = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise GhostError(f"git failed in {display_path(path)}: {lines[0] if lines else 'no reason given'}")
    return done.stdout.decode("utf-8", errors="replace")


def top(path: str) -> str:
    """the top folder of the repository that path is in."""
    return checked(path, "rev-parse", "--show-toplevel").removesuffix("\n")


def commits(path: str) -> list[Commit]:
    """every commit on a local branch or HEAD, newest first."""
    tips = ["--branches"]
    if run(path, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0:  # fails before the first commit
        tips.append("HEAD")
    out = checked(
        path, "log", "-z", "--no-patch", "--no-show-signature", "--no-color", "--encoding=UTF-8",
        "--format=tformat:%H%x00%ct%x00%an%x00%B", *tips, "--",
    )
    parts = out.split("\x00")
    return [
        Commit(parts[i], float(parts[i + 1]), parts[i + 2], parts[i + 3].strip())
        for i in range(0, len(parts) - 3, 4)
    ]


def index(store: Store, source: Source, report, now: float) -> None:
    """add new commits, forget the ones no branch has any more (amended, rebased).

    git has listed everything before the first change, so a failing git leaves
    the index as it was.
    """
    started = time.monotonic()
    known = store.documents(source)
    kept: set[str] = set()
    try:
        for commit in commits(source.path):
            sha = commit.sha[:SHORT]
            path = f"{source.path}@{sha}"
            kept.add(path)
            if path in known:
                report.unchanged += 1
                continue
            body, found = redact(commit.message)
            pieces = [(0, "", sha, piece.text) for piece in chunks.split(f"{body}\n\nby {commit.author}", False)]
            store.put_document(source, path, 0, commit.at, pieces, [], found, now)
            store.add_event(commit.at, "commit", source, path, redact(commit.subject)[0])
            report.new += 1
            report.redacted += found
        for path, (doc_id, _, _) in known.items():
            if path not in kept:
                store.delete_document(doc_id)
                store.delete_events(source, path)
                report.deleted += 1
        store.mark_indexed(source, now)
        store.commit()
    except BaseException:
        store.rollback()
        raise
    report.seconds = time.monotonic() - started
