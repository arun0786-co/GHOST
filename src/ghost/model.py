"""talking to a model server on this machine: ollama, or anything with an
openai-style api (lm studio, llama.cpp, mlx and others).

requests only ever go to a loopback address. proxies are switched off and
redirects are refused, so nothing can be passed on to another host.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterator

from .util import GhostError

# ollama, lm studio, llama.cpp server
CANDIDATES = ("http://127.0.0.1:11434", "http://127.0.0.1:1234", "http://127.0.0.1:8080")
PROBE_TIMEOUT = 1.5
API_NAMES = {"ollama": "ollama", "openai": "openai-style server"}


@dataclass
class Model:
    api: str  # "ollama" or "openai"
    url: str  # base url, without /v1
    name: str  # "" when the server has no models


def is_local(url: str) -> bool:
    """true only for http(s) urls whose host is localhost or a loopback address."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"refused a redirect to {newurl}", headers, fp)


# an empty ProxyHandler replaces the one that would read proxy settings from the environment.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirects())


def _open(url: str, body: dict | None, timeout: float):
    if not is_local(url):
        raise GhostError(f"refusing to connect to {url}: ghost only talks to this machine")
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="GET" if data is None else "POST")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    return _OPENER.open(request, timeout=timeout)


def _get_json(url: str, timeout: float = PROBE_TIMEOUT):
    try:
        with _open(url, None, timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        exc.close()
        return None
    except (OSError, ValueError, http.client.HTTPException):
        return None


def pick(names: list[str], wanted: str = "") -> str:
    """the wanted model ('llama3.2' also finds 'llama3.2:latest'), else the first one listed."""
    names = [name for name in names if name]
    if wanted:
        for name in names:
            if name == wanted or name.split(":")[0] == wanted:
                return name
        return wanted
    return names[0] if names else ""


def probe(base: str, wanted: str = "") -> Model | None:
    """which kind of server answers at base, and the model to use there."""
    base = base.rstrip("/").removesuffix("/v1")
    tags = _get_json(base + "/api/tags")
    if isinstance(tags, dict) and isinstance(tags.get("models"), list):
        return Model("ollama", base, pick([m.get("name", "") for m in tags["models"] if isinstance(m, dict)], wanted))
    listed = _get_json(base + "/v1/models")
    if isinstance(listed, dict) and isinstance(listed.get("data"), list):
        return Model("openai", base, pick([m.get("id", "") for m in listed["data"] if isinstance(m, dict)], wanted))
    return None


def find(url: str = "", wanted: str = "") -> Model | None:
    """the configured server, or the first of the usual local ports that answers."""
    for base in [url] if url else CANDIDATES:
        if not is_local(base):
            raise GhostError(f"the model url {base} is not on this machine. ghost only talks to localhost")
        model = probe(base, wanted)
        if model:
            return model
    return None


class ThinkFilter:
    """drops the <think>...</think> block that reasoning models write before
    the answer, also when a tag arrives split across two pieces."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.buffer = ""
        self.inside = False

    def feed(self, text: str) -> str:
        self.buffer += text
        shown = []
        while self.buffer:
            if self.inside:
                end = self.buffer.find(self.CLOSE)
                if end < 0:
                    self.buffer = self.buffer[-(len(self.CLOSE) - 1):]
                    break
                self.buffer = self.buffer[end + len(self.CLOSE):]
                self.inside = False
            else:
                start = self.buffer.find(self.OPEN)
                if start < 0:
                    keep = _partial_tag(self.buffer, self.OPEN)
                    shown.append(self.buffer[: len(self.buffer) - keep])
                    self.buffer = self.buffer[len(self.buffer) - keep:]
                    break
                shown.append(self.buffer[:start])
                self.buffer = self.buffer[start + len(self.OPEN):]
                self.inside = True
        return "".join(shown)

    def flush(self) -> str:
        rest = "" if self.inside else self.buffer
        self.buffer = ""
        return rest


def _partial_tag(text: str, tag: str) -> int:
    """how many characters at the end of text could be the start of tag."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0


def _ollama_pieces(response) -> Iterator[str]:
    for line in response:
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("error"):
            raise GhostError(f"the model server said: {event['error']}")
        yield (event.get("message") or {}).get("content") or ""
        if event.get("done"):
            return


def _openai_pieces(response) -> Iterator[str]:
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        event = json.loads(data)
        if event.get("error"):
            raise GhostError(f"the model server said: {event['error']}")
        for choice in event.get("choices") or []:
            yield (choice.get("delta") or {}).get("content") or ""


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        error = json.loads(exc.read().decode("utf-8", "replace")).get("error")
        if isinstance(error, dict):
            error = error.get("message")
        if error:
            return str(error)
    except (OSError, ValueError, AttributeError):
        pass
    return str(exc.reason)


def chat(
    model: Model,
    messages: list[dict],
    timeout: float,
    on_text: Callable[[str], None] | None = None,
) -> str:
    """the model's answer. on_text gets each piece as it arrives."""
    if not model.name:
        raise GhostError(f"the {API_NAMES[model.api]} at {model.url} has no models to use")
    if model.api == "ollama":
        url, read = model.url + "/api/chat", _ollama_pieces
        body = {"model": model.name, "messages": messages, "stream": True, "options": {"temperature": 0.2, "num_ctx": 8192}}
    else:
        url, read = model.url + "/v1/chat/completions", _openai_pieces
        body = {"model": model.name, "messages": messages, "stream": True, "temperature": 0.2}
    answer: list[str] = []
    visible = ThinkFilter()

    def emit(text: str) -> None:
        if text:
            answer.append(text)
            if on_text:
                on_text(text)

    try:
        with _open(url, body, timeout) as response:
            for piece in read(response):
                emit(visible.feed(piece))
        emit(visible.flush())
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        exc.close()
        raise GhostError(f"the model server said {exc.code}: {detail}") from None
    except (OSError, http.client.HTTPException) as exc:
        raise GhostError(f"lost the model server at {model.url}: {exc}") from None
    except ValueError:
        raise GhostError(f"the model server at {model.url} sent something that is not json") from None
    return "".join(answer).strip()
