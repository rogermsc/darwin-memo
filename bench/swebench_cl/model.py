"""Model calls behind one OpenAI-compatible endpoint config.

The pilot runs against a local Ollama server today and a frontier
endpoint later, by changing nothing but the config: every server in
that family speaks ``POST {base_url}/chat/completions``. Transport is
stdlib urllib, matching the rest of the repo's zero-dependency stance.

Failures are loud (``EndpointError``), never empty strings: a swallowed
endpoint failure would read as the model producing no patch, and the
run record would then blame the model for an infrastructure problem.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from darwin_memo.llm import THINK_RE

DEFAULT_BASE_URL = "http://localhost:11434/v1"


class EndpointError(RuntimeError):
    """The endpoint failed, with the server's own message attached."""


@dataclass(frozen=True)
class EndpointConfig:
    """Everything that identifies a model endpoint, and nothing else.

    ``api_key`` is the literal key value (empty for local servers).
    Swapping Ollama for a frontier provider is a base_url, model, and
    api_key change; the harness code does not move.
    """

    base_url: str = DEFAULT_BASE_URL
    model: str = "llama3.2"
    api_key: str = ""
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout: float = 600.0
    retries: int = 3  # transient connection failures only; HTTP errors are real


class ChatEndpoint:
    """One blocking chat completion per call, OpenAI wire format."""

    def __init__(self, config: EndpointConfig) -> None:
        self.config = config

    def complete(self, prompt: str, system: str = "") -> str:
        config = self.config
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        request = urllib.request.Request(
            f"{config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        # Transient connection failures (timeouts, dropped sockets, 5xx)
        # are retried with backoff so one network blip cannot kill a long
        # multi-task run. A 4xx is a real error (bad params, auth) and is
        # raised immediately, never retried.
        attempts = max(1, config.retries)
        last_transient: Exception | None = None
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(
                    request, timeout=config.timeout
                ) as response:
                    return _content_of(
                        json.loads(response.read().decode("utf-8")), config
                    )
            except urllib.error.HTTPError as error:
                if error.code < 500:
                    body = error.read().decode("utf-8", errors="replace")
                    raise EndpointError(
                        f"endpoint returned HTTP {error.code} for model "
                        f"{config.model!r} at {config.base_url}: "
                        f"{body or error.reason}"
                    ) from error
                last_transient = error  # 5xx: server-side, retry
            except (urllib.error.URLError, TimeoutError) as error:
                last_transient = error
            if attempt < attempts - 1:
                time.sleep(2.0 * (attempt + 1))
        raise EndpointError(
            f"cannot reach endpoint {config.base_url} after {attempts} "
            f"attempts for model {config.model!r}: {last_transient}"
        ) from last_transient


def _content_of(result: Any, config: EndpointConfig) -> str:
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise EndpointError(
            f"unexpected response shape from {config.base_url} for model "
            f"{config.model!r}: {str(result)[:200]}"
        ) from error
    return str(content or "")


# A patch is either inside a ``` / ```diff fence or starts bare at a
# "diff --git" (or "--- a/") line. REFLECTION: ends it either way.
_FENCE_RE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL)
_BARE_DIFF_RE = re.compile(r"^(?:diff --git |--- a/)", re.MULTILINE)
_REFLECTION_RE = re.compile(r"^\s*REFLECTION:\s*(.+)$", re.MULTILINE)


def extract_patch(text: str) -> str:
    """Pull the unified diff out of a model response. Empty if none.

    Empty is a real result, not an error: the empty-patch path is part
    of the pipeline (it evaluates as unresolved with zero tests run on
    top of base), and the run record keeps the evidence.
    """
    text = THINK_RE.sub("", text)
    for match in _FENCE_RE.finditer(text):
        body = match.group(1).strip()
        if _BARE_DIFF_RE.search(body):
            return body
    bare = _BARE_DIFF_RE.search(text)
    if bare:
        tail = text[bare.start() :]
        reflection = _REFLECTION_RE.search(tail)
        if reflection:
            tail = tail[: reflection.start()]
        return tail.strip().removesuffix("```").strip()
    return ""


def extract_reflection(text: str) -> str:
    """The model's own one-line reflection, if it produced one."""
    text = THINK_RE.sub("", text)
    match = _REFLECTION_RE.search(text)
    return match.group(1).strip() if match else ""
