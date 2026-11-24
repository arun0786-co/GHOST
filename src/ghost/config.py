"""where ghost keeps what it knows (~/.ghost, or GHOST_HOME) and the settings in config.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .util import GhostError, display_path

DEFAULT_CONFIG = """\
# ghost settings. everything ghost knows is in this folder: delete the folder
# and ghost forgets all of it. your own files are only read, never changed.

[model]
# a model server on this machine, for `ghost ask`. ghost never connects to
# another host. empty url = look for ollama (http://127.0.0.1:11434), then
# lm studio (http://127.0.0.1:1234), then llama.cpp (http://127.0.0.1:8080).
url = ""
# empty name = the first local model the server lists. ollama cloud models
# are never used.
name = ""
# seconds to wait for the model before giving up.
timeout = 300

[index]
# files bigger than this are skipped.
max_file_kb = 1024
# more file or folder names to skip in every source, as glob patterns. a
# pattern with a / is matched against the path inside the source instead.
skip = []
# more file types to read, for example [".csv", ".log"].
extra_types = []
"""


def ghost_home() -> Path:
    explicit = os.environ.get("GHOST_HOME")
    return Path(explicit).expanduser() if explicit else Path.home() / ".ghost"


@dataclass
class Config:
    home: Path
    model_url: str = ""
    model_name: str = ""
    model_timeout: float = 300.0
    max_file_kb: int = 1024
    skip: list[str] = field(default_factory=list)
    extra_types: list[str] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.home / "ghost.db"

    @property
    def notes_dir(self) -> Path:
        return self.home / "notes"


def load(home: Path | None = None) -> Config:
    config = Config(home=home or ghost_home())
    path = config.home / "config.toml"
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return config
    except tomllib.TOMLDecodeError as exc:
        raise GhostError(f"{display_path(path)} is not valid toml: {exc}") from None
    model, index = data.get("model", {}), data.get("index", {})
    if not isinstance(model, dict) or not isinstance(index, dict):
        raise GhostError(f"{display_path(path)}: [model] and [index] must be tables")
    try:
        config.model_url = str(model.get("url", ""))
        config.model_name = str(model.get("name", ""))
        config.model_timeout = float(model.get("timeout", 300))
        config.max_file_kb = int(index.get("max_file_kb", 1024))
        config.skip = [str(pattern) for pattern in index.get("skip", [])]
        config.extra_types = ["." + str(kind).lower().lstrip(".") for kind in index.get("extra_types", [])]
    except (TypeError, ValueError) as exc:
        raise GhostError(f"{display_path(path)}: {exc}") from None
    return config


def ensure_home(config: Config) -> None:
    """create the ghost folder, readable only by you, with a commented config.toml."""
    config.home.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = config.home / "config.toml"
    if not path.exists():
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        path.chmod(0o600)
