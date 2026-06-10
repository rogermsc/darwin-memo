"""Pluggable LLM clients.

The core library never requires an LLM. Encoding and the query protocol
both have rule-based local modes so every example runs offline with zero
API keys. When a client is provided, the same steps use the model instead,
which is the configuration you want for real corpora.

Both papers keep the main model frozen and so does this package: clients
are called over plain completion APIs, no weights or logprobs needed,
which is what makes the approach work with closed models.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str, system: str = "") -> str: ...


class AnthropicClient:
    """Claude over the Anthropic API. Requires ``pip install darwin-memo[anthropic]``."""

    def __init__(self, model: str | None = None, max_tokens: int = 1024) -> None:
        import anthropic

        self._client = anthropic.Anthropic()
        self.model = model or os.environ.get("DARWIN_MEMO_MODEL", "claude-sonnet-4-6")
        self.max_tokens = max_tokens

    def complete(self, prompt: str, system: str = "") -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system or "You are a precise knowledge-engineering assistant.",
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
                {"role": "system", "content": system or "You are a precise knowledge-engineering assistant."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""


def parse_json_array(text: str) -> list:
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
