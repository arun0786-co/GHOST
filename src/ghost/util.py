"""small helpers shared by the commands: errors, paths, sizes and times."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path


class GhostError(Exception):
    """an error shown to the user as one line, without a traceback."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def display_path(path: str | Path) -> str:
    """the path with the home folder written as ~."""
    text = str(path)
    home = str(Path.home())
    if text == home:
        return "~"
    if text.startswith(home + "/"):
        return "~" + text[len(home):]
    return text


def plural(count: int, word: str, many: str = "") -> str:
    return f"{count} {word if count == 1 else many or word + 's'}"


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def ago(then: float, now: float | None = None) -> str:
    """a short age: 'just now', '5m ago', '3h ago', '2d ago', or the date."""
    seconds = (time.time() if now is None else now) - then
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 60 * 86400:
        return f"{int(seconds // 86400)}d ago"
    return datetime.fromtimestamp(then).strftime("%Y-%m-%d")


def day_label(when: float) -> str:
    return datetime.fromtimestamp(when).strftime("%a %d %b %Y").lower()


def clock(when: float) -> str:
    return datetime.fromtimestamp(when).strftime("%H:%M")


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SPAN = re.compile(r"(\d+)\s*(m|min|h|d|w)")
SPAN_SECONDS = {"m": 60, "min": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
TIME_HELP = "use 30m, 12h, 3d, 2w, today, yesterday, a weekday or a date like 2026-10-01"


def parse_day(text: str, now: float | None = None) -> tuple[float, float]:
    """'today', 'yesterday', a weekday (the latest one) or 2026-10-20 -> start and end of that day."""
    value = text.strip().lower()
    today = datetime.fromtimestamp(time.time() if now is None else now).replace(hour=0, minute=0, second=0, microsecond=0)
    weekday = [i for i, name in enumerate(WEEKDAYS) if len(value) >= 3 and name.startswith(value)]
    if value == "today":
        start = today
    elif value == "yesterday":
        start = today - timedelta(days=1)
    elif weekday:
        start = today - timedelta(days=(today.weekday() - weekday[0]) % 7)
    else:
        try:
            start = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise GhostError(f"cannot read {text!r} as a day. {TIME_HELP}") from None
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def parse_since(text: str, now: float | None = None) -> float:
    """'3d', '12h', '2w' back from now, or the start of a day parse_day understands."""
    now = time.time() if now is None else now
    match = SPAN.fullmatch(text.strip().lower())
    if match:
        return now - int(match.group(1)) * SPAN_SECONDS[match.group(2)]
    try:
        return parse_day(text, now)[0]
    except GhostError:
        raise GhostError(f"cannot read {text!r} as a time. {TIME_HELP}") from None
