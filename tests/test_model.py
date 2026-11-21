import os
import unittest
from unittest import mock

from support import GhostTestCase

from ghost import model
from ghost.util import GhostError


class LocalOnlyTests(unittest.TestCase):
    def test_loopback_hosts_only(self):
        for url in ("http://127.0.0.1:11434", "http://localhost:1234/v1", "http://[::1]:8080", "https://127.0.0.2"):
            with self.subTest(url=url):
                self.assertTrue(model.is_local(url))
        for url in (
            "http://example.com",
            "http://127.0.0.1.example.com",
            "http://127.0.0.1@example.com",
            "http://example.com#@127.0.0.1",
            "http://10.0.0.5:11434",
            "http://0.0.0.0:11434",
            "ftp://127.0.0.1",
            "file:///etc/passwd",
            "127.0.0.1:11434",
            "http://[::1",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(model.is_local(url))

    def test_a_remote_url_is_refused_before_any_connection(self):
        with mock.patch.object(model._OPENER, "open", side_effect=AssertionError("connected")):
            with self.assertRaises(GhostError) as caught:
                model.find("http://example.com:11434")
            self.assertIn("not on this machine", str(caught.exception))
            with self.assertRaises(GhostError):
                model._open("http://example.com/api/chat", {}, 1)

    def test_pick(self):
        self.assertEqual(model.pick(["llama3.2:latest", "qwen3:8b"]), "llama3.2:latest")
        self.assertEqual(model.pick(["llama3.2:latest", "qwen3:8b"], "qwen3"), "qwen3:8b")
        self.assertEqual(model.pick(["llama3.2:latest"], "qwen3:8b"), "qwen3:8b")
        self.assertEqual(model.pick([]), "")


class ThinkFilterTests(unittest.TestCase):
    def run_filter(self, pieces):
        visible = model.ThinkFilter()
        return "".join(visible.feed(p) for p in pieces) + visible.flush()

    def test_think_blocks_are_dropped_even_when_split(self):
        self.assertEqual(self.run_filter(["<think>hmm</think>answer"]), "answer")
        self.assertEqual(self.run_filter(["<thi", "nk>let me see", "</th", "ink>The", " rent [1]"]), "The rent [1]")
        self.assertEqual(self.run_filter(["a < b and ", "<", "t"]), "a < b and <t")
        self.assertEqual(self.run_filter(["<think>never closed"]), "")
        self.assertEqual(self.run_filter(["plain"]), "plain")


class ServerTests(GhostTestCase):
    messages = [{"role": "user", "content": "when is the rent due?"}]

    def test_finds_and_streams_from_ollama(self):
        server = self.fake_model(api="ollama", answer="<think>checking</think>Rent is due on the 5th [1].")
        found = model.find(server.url)
        self.assertEqual((found.api, found.name), ("ollama", "tiny:latest"))
        pieces = []
        answer = model.chat(found, self.messages, 5, pieces.append)
        self.assertEqual(answer, "Rent is due on the 5th [1].")
        self.assertGreater(len(pieces), 2)
        body = server.chats()[0]
        self.assertEqual((body["model"], body["stream"], body["messages"]), ("tiny:latest", True, self.messages))

    def test_finds_and_streams_from_an_openai_style_server(self):
        server = self.fake_model(api="openai", answer="It is due on the 5th [1].", models=("local-model",))
        found = model.find(server.url + "/v1/", "local-model")
        self.assertEqual((found.api, found.url, found.name), ("openai", server.url, "local-model"))
        self.assertEqual(model.chat(found, self.messages, 5), "It is due on the 5th [1].")
        self.assertEqual(server.chats()[0]["model"], "local-model")

    def test_the_usual_ports_are_tried_in_order(self):
        server = self.fake_model(api="ollama")
        with mock.patch.object(model, "CANDIDATES", ("http://127.0.0.1:9", server.url)):
            self.assertEqual(model.find().url, server.url)
        with mock.patch.object(model, "CANDIDATES", ("http://127.0.0.1:9",)):
            self.assertIsNone(model.find())

    def test_proxy_settings_are_ignored(self):
        server = self.fake_model()
        proxies = {"HTTP_PROXY": "http://10.255.255.1:3128", "http_proxy": "http://10.255.255.1:3128", "ALL_PROXY": "http://10.255.255.1:3128"}
        with mock.patch.dict(os.environ, proxies):
            self.assertEqual(model.chat(model.find(server.url), self.messages, 5), "rent is due on the 5th [1]")

    def test_redirects_are_refused(self):
        server = self.fake_model(redirect="http://example.com/steal")
        with self.assertRaises(GhostError) as caught:
            model.chat(model.Model("ollama", server.url, "tiny"), self.messages, 5)
        self.assertIn("refused a redirect", str(caught.exception))

    def test_server_errors_are_shown(self):
        server = self.fake_model(status=404, error='model "huge" not found, try pulling it first')
        with self.assertRaises(GhostError) as caught:
            model.chat(model.Model("ollama", server.url, "huge"), self.messages, 5)
        self.assertIn('404: model "huge" not found', str(caught.exception))

    def test_a_server_without_models(self):
        server = self.fake_model(models=())
        found = model.find(server.url)
        self.assertEqual(found.name, "")
        with self.assertRaises(GhostError):
            model.chat(found, self.messages, 5)
