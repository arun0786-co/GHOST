"""blanking out secret-shaped strings before anything is stored.

a safety net, not a guarantee: it catches the common key and token formats
and `password = ...` style lines whose value looks random. your files are
never changed; only the copy in the index is blanked, so secrets do not show
up in search results or reach a model.
"""

from __future__ import annotations

import re

MASK = "[redacted]"

PATTERNS = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # aws access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),  # github
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),  # gitlab
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),  # most model apis
    re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"),  # stripe
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),  # slack
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),  # google
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),  # hugging face
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # jwt
]

# the name stays, the value goes, if the value looks like a key rather than a word or code.
ASSIGNMENT = re.compile(
    r"""(?ix)
    (\b(?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)\w*
     ["']?\s*[:=]\s*["']?)
    ([^\s"'`,;]{8,})
    """
)


def looks_random(value: str) -> bool:
    """letters and digits mixed, and no brackets or $ that would mean code."""
    if any(c in value for c in "()[]{}<>$"):
        return False
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value)


def redact(text: str) -> tuple[str, int]:
    """the text with secret-shaped strings replaced by [redacted], and how many there were."""
    count = 0
    for pattern in PATTERNS:
        text, found = pattern.subn(MASK, text)
        count += found

    def hide(match: re.Match) -> str:
        nonlocal count
        if not looks_random(match.group(2)):
            return match.group(0)
        count += 1
        return match.group(1) + MASK

    return ASSIGNMENT.sub(hide, text), count
