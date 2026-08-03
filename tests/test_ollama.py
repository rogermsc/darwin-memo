"""Ollama client and embedder against a stdlib fake server. No network."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from darwin_memo import (
    EmbeddingRetriever,
    MemoryEntry,
    MemoryStore,
    OllamaClient,
    OllamaEmbedder,
    ollama_available,
)
from darwin_memo.llm import ollama_model_digest


class FakeOllama(BaseHTTPRequestHandler):
    requests: ClassVar[list[tuple[str, dict[str, Any]]]] = []
    legacy_embeddings = False

    def do_GET(self):
        if self.path == "/api/tags":
            # Ollama reports a bare pull as ":latest"; the fake said
            # "llama3.2" and hid a real lookup miss for years.
            self._reply(
                {"models": [{"name": "llama3.2:latest", "digest": "sha256:feedc0de"}]}
            )
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        FakeOllama.requests.append((self.path, payload))
        if self.path == "/api/chat":
            prompt = payload["messages"][-1]["content"]
            self._reply(
                {"message": {"role": "assistant", "content": f"echo: {prompt[:40]}"}}
            )
        elif self.path == "/api/embed" and not FakeOllama.legacy_embeddings:
            self._reply({"embeddings": [[0.6, 0.8, 0.0]]})
        elif self.path == "/api/embeddings" and FakeOllama.legacy_embeddings:
            self._reply({"embedding": [0.0, 0.6, 0.8]})
        else:
            self.send_error(404)

    def _reply(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture
def fake_ollama():
    FakeOllama.requests = []
    FakeOllama.legacy_embeddings = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_ollama_available(fake_ollama):
    assert ollama_available(fake_ollama)
    assert not ollama_available("http://127.0.0.1:9", timeout=0.2)


def test_client_complete_sends_chat_shape(fake_ollama):
    client = OllamaClient(model="llama3.2", base_url=fake_ollama, temperature=0.0)
    answer = client.complete("Is it safe?", system="Be terse.")
    assert answer.startswith("echo: Is it safe?")

    path, payload = FakeOllama.requests[-1]
    assert path == "/api/chat"
    assert payload["model"] == "llama3.2"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.0
    # The generation cap is load-bearing: without it a looping model
    # generates until the context fills and presents as a timeout.
    assert payload["options"]["num_predict"] == 1024
    assert payload["messages"][0] == {"role": "system", "content": "Be terse."}


def test_client_omits_think_by_default(fake_ollama):
    """Servers reject the think field on models without the thinking
    capability, so it must only be sent when explicitly set."""
    OllamaClient(model="llama3.2", base_url=fake_ollama).complete("hi")
    _, payload = FakeOllama.requests[-1]
    assert "think" not in payload


def test_client_sends_think_when_set(fake_ollama):
    OllamaClient(model="qwen3:4b", base_url=fake_ollama, think=False).complete("hi")
    _, payload = FakeOllama.requests[-1]
    assert payload["think"] is False


def test_model_digest_lookup(fake_ollama):
    # A bare name must resolve against the ":latest" the server reports,
    # or the manifest records null for a model that is pulled and running.
    assert ollama_model_digest("llama3.2", base_url=fake_ollama) == "sha256:feedc0de"
    assert (
        ollama_model_digest("llama3.2:latest", base_url=fake_ollama)
        == "sha256:feedc0de"
    )
    # An explicit tag stays explicit: it must not fall back to :latest.
    assert ollama_model_digest("llama3.2:3b", base_url=fake_ollama) is None
    assert ollama_model_digest("absent:1b", base_url=fake_ollama) is None
    assert ollama_model_digest("llama3.2", "http://127.0.0.1:9", timeout=0.2) is None


def test_embedder_current_endpoint(fake_ollama):
    embedder = OllamaEmbedder(base_url=fake_ollama)
    assert embedder("database files") == [0.6, 0.8, 0.0]
    path, payload = FakeOllama.requests[-1]
    assert path == "/api/embed"
    assert payload["input"] == "database files"


def test_embedder_falls_back_to_legacy(fake_ollama):
    FakeOllama.legacy_embeddings = True
    embedder = OllamaEmbedder(base_url=fake_ollama)
    assert embedder("database files") == [0.0, 0.6, 0.8]
    assert FakeOllama.requests[-1][0] == "/api/embeddings"


def test_embedder_plugs_into_retriever(fake_ollama):
    store = MemoryStore(
        retriever=EmbeddingRetriever(OllamaEmbedder(base_url=fake_ollama))
    )
    store.add(MemoryEntry(question="What about databases?", answer="Retain them."))
    hits = store.retrieve("database question")
    assert hits and hits[0][0].answer == "Retain them."
