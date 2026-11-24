"""shared test setup: a temporary home with a space in its path, GHOST_HOME
inside it, and a guard that fails any test that connects anywhere but this
machine. fake model servers run on 127.0.0.1.

nothing here touches the real ~/.ghost.
"""

from __future__ import annotations

import contextlib
import http.server
import io
import ipaddress
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from ghost import model

_real_connect = socket.socket.connect


def _local_only(sock: socket.socket, address) -> None:
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        host = str(address[0]).split("%")[0]
        try:
            local = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local:
            raise AssertionError(f"a test tried to connect to {address}")
    return _real_connect(sock, address)


def fake(*parts: str) -> str:
    """secret-shaped strings are put together at run time, so no file holds one."""
    return "".join(parts)


class GhostTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="ghost test ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / "home dir"
        self.home.mkdir()
        self.ghost_home = self.home / ".ghost"
        env = {k: v for k, v in os.environ.items() if not k.startswith("GHOST_")}
        env.update(HOME=str(self.home), GHOST_HOME=str(self.ghost_home), NO_COLOR="1")
        for patcher in (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(socket.socket, "connect", _local_only),
            # never find a real model server on this machine; tests that want one start a FakeModel
            mock.patch.object(model, "CANDIDATES", ()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertEqual(Path.home(), self.home)

    # helpers

    def ghost(self, *argv: str) -> tuple[int, str, str]:
        from ghost import cli  # here, so tests of one module do not need the whole command line

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv: str) -> str:
        code, out, err = self.ghost(*argv)
        self.assertEqual(code, 0, f"ghost {' '.join(argv)} failed:\n{out}\n{err}")
        return out

    def fails(self, *argv: str) -> str:
        code, out, err = self.ghost(*argv)
        self.assertNotEqual(code, 0, f"ghost {' '.join(argv)} should have failed:\n{out}")
        return out + err

    def write(self, rel: str, text: str = "", mtime: float | None = None, data: bytes | None = None) -> Path:
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            path.write_bytes(data)
        else:
            path.write_text(text, encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def write_config(self, text: str) -> None:
        self.ghost_home.mkdir(parents=True, exist_ok=True)
        (self.ghost_home / "config.toml").write_text(text, encoding="utf-8")

    def tree(self, root: Path) -> dict[str, bytes]:
        """every file under root with its content, to show a command changed nothing."""
        if not root.exists():
            return {}
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}

    def fake_model(self, **options) -> "FakeModel":
        server = FakeModel(**options)
        self.addCleanup(server.close)
        return server


class FakeModel:
    """an ollama or openai-style server on 127.0.0.1. it streams a canned answer
    in small pieces and keeps every request it got."""

    def __init__(
        self,
        api: str = "ollama",
        answer: str = "rent is due on the 5th [1]",
        models: tuple[str, ...] = ("tiny:latest",),
        status: int = 200,
        error: str = "",
        redirect: str = "",
        show: dict | None = None,
    ):
        self.api, self.answer, self.models = api, answer, list(models)
        self.status, self.error, self.redirect = status, error, redirect
        # what /api/show says about the model. one with the thinking capability streams
        # reasoning in message.thinking unless the request says think: false
        self.show = show or {"capabilities": ["completion"]}
        self.requests: list[tuple[str, str, object]] = []
        fake_server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                fake_server.handle(self, None)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                fake_server.handle(self, json.loads(self.rfile.read(length) or b"null"))

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        # a short poll interval, so shutdown() in the cleanup returns quickly
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    @staticmethod
    def send(handler, status: int, body: bytes, kind: str = "application/json") -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", kind)
        handler.end_headers()
        handler.wfile.write(body)

    def handle(self, handler, body) -> None:
        self.requests.append((handler.command, handler.path, body))
        path = handler.path
        if self.redirect:
            handler.send_response(302)
            handler.send_header("Location", self.redirect)
            handler.end_headers()
            return
        if path == "/api/tags" and self.api == "ollama":
            return self.send(handler, 200, json.dumps({"models": [{"name": m} for m in self.models]}).encode())
        if path == "/api/show" and self.api == "ollama":
            return self.send(handler, 200, json.dumps(self.show).encode())
        if path == "/v1/models" and self.api == "openai":
            return self.send(handler, 200, json.dumps({"object": "list", "data": [{"id": m} for m in self.models]}).encode())
        if self.status != 200:
            return self.send(handler, self.status, json.dumps({"error": self.error}).encode())
        pieces = [self.answer[i : i + 4] for i in range(0, len(self.answer), 4)]
        if path == "/api/chat" and self.api == "ollama":
            lines = []
            if "thinking" in self.show.get("capabilities", []) and body.get("think") is not False:
                lines.append(json.dumps({"message": {"role": "assistant", "content": "", "thinking": "REASONING"}, "done": False}))
            lines += [json.dumps({"message": {"role": "assistant", "content": p}, "done": False}) for p in pieces]
            lines.append(json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}))
            return self.send(handler, 200, ("\n".join(lines) + "\n").encode(), "application/x-ndjson")
        if path == "/v1/chat/completions" and self.api == "openai":
            events = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n" for p in pieces]
            return self.send(handler, 200, ("".join(events) + "data: [DONE]\n\n").encode(), "text/event-stream")
        self.send(handler, 404, json.dumps({"error": "not found"}).encode())

    def chats(self) -> list[dict]:
        return [body for _, path, body in self.requests if path in ("/api/chat", "/v1/chat/completions")]
