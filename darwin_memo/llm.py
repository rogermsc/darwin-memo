"""Pluggable LLM clients.

The core library never requires an LLM. Encoding and the query protocol
both have rule-based local modes so every example runs offline with zero
API keys. When a client is provided, the same steps use the model instead,
which is the configuration you want for real corpora.

Both papers keep the main model frozen and so does this package: clients
are called over plain completion APIs, no weights or logprobs needed,
which is what makes the approach work with closed models. The Ollama
client and embedder speak the native localhost API over stdlib urllib,
so the fully local stack adds no dependencies at all.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str, system: str = "") -> str: ...


_DEFAULT_SYSTEM = "You are a precise knowledge-engineering assistant."


class AnthropicClient:
    """Claude over the Anthropic API (``pip install darwin-memo[anthropic]``)."""

    def __init__(self, model: str | None = None, max_tokens: int = 1024) -> None:
        import anthropic

        self._client = anthropic.Anthropic()
        self.model = model or os.environ.get("DARWIN_MEMO_MODEL", "claude-sonnet-4-6")
        self.max_tokens = max_tokens

    def complete(self, prompt: str, system: str = "") -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system or _DEFAULT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in message.content if block.type == "text")


class OpenAICompatClient:
    """Any OpenAI-compatible endpoint, including local servers like Ollama or vLLM."""

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        max_tokens: int = 1024,
    ) -> None:
        import openai

        self._client = openai.OpenAI(base_url=base_url)
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, prompt: str, system: str = "") -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system or _DEFAULT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        return str(response.choices[0].message.content or "")


DEFAULT_OLLAMA_URL = "http://localhost:11434"


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"unexpected response shape from {url}")
    return result


def ollama_available(base_url: str = DEFAULT_OLLAMA_URL, timeout: float = 2.0) -> bool:
    """Is an Ollama server listening? Used for graceful auto-detection."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


class OllamaClient:
    """Local models through Ollama's native API. Zero dependencies.

    Needs a running Ollama server (https://ollama.com) and nothing else:
    the transport is stdlib urllib against localhost. Temperature
    defaults to 0 because the survival loop wants the most repeatable
    answers a sampled model can give (local sampling is still not
    byte-deterministic; keep LLM arms out of determinism checks).
    """

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = DEFAULT_OLLAMA_URL,
        temperature: float = 0.0,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    def complete(self, prompt: str, system: str = "") -> str:
        result = _post_json(
            f"{self.base_url}/api/chat",
            {
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system or _DEFAULT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": self.temperature},
            },
            timeout=self.timeout,
        )
        message = result.get("message", {})
        return str(message.get("content", "")) if isinstance(message, dict) else ""


class OllamaEmbedder:
    """Local embeddings through Ollama, plugs into ``EmbeddingRetriever``.

    Real synonym recall with zero cloud and zero dependencies. Vectors
    persist inside ``memory.json`` like any other embedding source.
    Tries the current ``/api/embed`` endpoint first and falls back to
    the legacy ``/api/embeddings`` shape for older servers.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __call__(self, text: str) -> list[float]:
        try:
            result = _post_json(
                f"{self.base_url}/api/embed",
                {"model": self.model, "input": text},
                timeout=self.timeout,
            )
            embeddings = result.get("embeddings")
            if embeddings:
                return [float(x) for x in embeddings[0]]
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        result = _post_json(
            f"{self.base_url}/api/embeddings",
            {"model": self.model, "prompt": text},
            timeout=self.timeout,
        )
        return [float(x) for x in result.get("embedding", [])]


def parse_json_array(text: str) -> list[Any]:
    """Pull the first JSON array out of a model response, tolerating fences."""
    text = re.sub(r"```(?:json)?", "", text)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []
