"""which files ghost reads in a source, and the plain text it takes from them.

ghost reads text files only. it skips hidden files and folders, files that
usually hold keys or passwords, dependency and build folders, symlinks,
binary files and anything over the size limit. a .ghostignore file in the
source, and `skip` in config.toml, can skip more.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterator

from .util import GhostError, display_path

TEXT_TYPES = frozenset(
    """
    .md .markdown .mdx .txt .text .org .rst .tex .adoc .bib .srt .vtt
    .py .ipynb .js .jsx .ts .tsx .mjs .cjs .vue .svelte .sh .bash .zsh .fish
    .rb .go .rs .java .kt .kts .swift .c .h .cc .cpp .hpp .m .mm .cs .php .lua
    .r .jl .scala .dart .ex .exs .erl .hs .ml .clj .sql
    .html .htm .css .scss .sass .less
    .json .toml .yaml .yml .ini .cfg .conf
    """.split()
)
TEXT_NAMES = frozenset({"Makefile", "Dockerfile", "Justfile", "Procfile", "README"})
MARKDOWN_TYPES = frozenset({".md", ".markdown", ".mdx"})

# big, generated, or not yours.
SKIP_DIRS = frozenset(
    {
        "node_modules", "bower_components", "vendor", "site-packages", "__pycache__",
        "venv", "dist", "build", "target", "Pods", "DerivedData", "Library",
    }
)

# files that usually hold keys or passwords, and generated files that only add noise.
SKIP_FILES = (
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx", "*.gpg",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "*.keychain*",
    "credentials", "credentials.*", "secrets.*", "*.secret",
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
    "*.min.js", "*.min.css", "*.map",
)
SKIP_FILES_RE = re.compile("|".join(fnmatch.translate(pattern) for pattern in SKIP_FILES))


@dataclass
class Rules:
    patterns: list[str] = field(default_factory=list)
    max_bytes: int = 1024 * 1024
    extra_types: frozenset[str] = frozenset()

    def skipped(self, name: str, rel: str) -> bool:
        """a .ghostignore or config pattern matches this file or folder."""
        for pattern in self.patterns:
            if "/" in pattern:
                if fnmatch.fnmatch(rel, pattern.strip("/")):
                    return True
            elif fnmatch.fnmatch(name, pattern):
                return True
        return False

    def wanted(self, name: str) -> bool:
        """a text file by its name or type, and not one ghost always skips."""
        suffix = os.path.splitext(name)[1].lower()
        if not (name in TEXT_NAMES or suffix in TEXT_TYPES or suffix in self.extra_types):
            return False
        return not SKIP_FILES_RE.match(name.lower())


def load_rules(root: str, skip: list[str], max_bytes: int, extra_types: list[str]) -> Rules:
    """the rules for one source: the config patterns plus its .ghostignore."""
    patterns = list(skip)
    path = os.path.join(root, ".ghostignore")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    except FileNotFoundError:
        pass
    except (OSError, UnicodeDecodeError) as exc:
        # indexing without it could pick up exactly what it was meant to keep out
        raise GhostError(f"cannot read {display_path(path)} ({exc}), so nothing was indexed from that source") from None
    return Rules(patterns, max_bytes, frozenset(extra_types))


@dataclass
class WalkReport:
    too_big: int = 0
    unreadable: list[str] = field(default_factory=list)  # folders that could not be listed


def walk(root: str, rules: Rules, report: WalkReport) -> Iterator[tuple[str, os.stat_result]]:
    """every file to read under root, as (path, stat), in a stable order."""
    stack = [(root, "")]
    while stack:
        folder, rel_folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda entry: entry.name)
        except OSError:
            report.unreadable.append(folder)
            continue
        folders = []
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                continue
            rel = f"{rel_folder}/{name}" if rel_folder else name
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if name not in SKIP_DIRS and not rules.skipped(name, rel):
                        folders.append((entry.path, rel))
                    continue
                if not entry.is_file(follow_symlinks=False) or not rules.wanted(name) or rules.skipped(name, rel):
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if info.st_size > rules.max_bytes:
                report.too_big += 1
                continue
            yield entry.path, info
        stack.extend(reversed(folders))


@dataclass
class Text:
    body: str
    markdown: bool  # headings and code fences mean something
    has_lines: bool  # line numbers match the file; not for converted html and notebooks


def read_text(path: str, data: bytes) -> Text | None:
    """the text of a file, or None when it looks binary."""
    if b"\x00" in data[:8192]:
        return None
    body = data.decode("utf-8", errors="replace").removeprefix("﻿")
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".ipynb":
        cells = notebook_text(body)
        if cells is not None:
            return Text(cells, markdown=True, has_lines=False)
    if suffix in (".html", ".htm"):
        return Text(html_text(body), markdown=True, has_lines=False)
    return Text(body, markdown=suffix in MARKDOWN_TYPES, has_lines=True)


def notebook_text(raw: str) -> str | None:
    """the markdown and code cells of a jupyter notebook, without outputs."""
    try:
        parts = []
        for cell in json.loads(raw)["cells"]:
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            source = source.strip()
            if source:
                parts.append(f"```\n{source}\n```" if cell.get("cell_type") == "code" else source)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return "\n\n".join(parts)


class _VisibleText(HTMLParser):
    HIDDEN = frozenset({"script", "style", "noscript", "template", "svg"})
    BLOCKS = frozenset(
        {
            "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header",
            "footer", "blockquote", "pre", "title", "hr", "dd", "dt",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    @staticmethod
    def heading_level(tag: str) -> int:
        return int(tag[1]) if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456" else 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.HIDDEN:
            self.hidden += 1
        elif self.heading_level(tag):
            self.parts.append("\n\n" + "#" * self.heading_level(tag) + " ")
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif tag in self.BLOCKS or self.heading_level(tag):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def html_text(raw: str) -> str:
    """the visible text of a web page, its headings written as markdown headings."""
    parser = _VisibleText()
    parser.feed(raw)
    parser.close()
    lines: list[str] = []
    for line in "".join(parser.parts).split("\n"):
        line = " ".join(line.split())
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()
