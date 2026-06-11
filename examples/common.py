"""Shared helpers for the examples: load the corpus, pick an encoder."""

from __future__ import annotations

import os

from darwin_memo import (
    Document,
    LocalEncoder,
    MemoryStore,
    ReflectionEncoder,
    demo_corpus,
)


def load_corpus() -> list[Document]:
    # One canonical corpus, shipped as package data: the CLI demo and the
    # benchmarks read the exact same files, so they can never drift.
    return demo_corpus()


def build_encoder():
    """Prefer Claude, then a local Ollama model, then the offline encoder."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from darwin_memo.llm import AnthropicClient

            print("Encoder: ReflectionEncoder (Claude)")
            return ReflectionEncoder(AnthropicClient())
        except ImportError:
            print("anthropic package missing, trying local options")
    if os.environ.get("DARWIN_MEMO_OLLAMA"):
        from darwin_memo.llm import OllamaClient, ollama_available

        if ollama_available():
            model = os.environ.get("DARWIN_MEMO_OLLAMA_MODEL", "llama3.2")
            print(f"Encoder: ReflectionEncoder (Ollama, {model})")
            return ReflectionEncoder(OllamaClient(model=model))
        print("DARWIN_MEMO_OLLAMA set but no server detected on :11434")
    print("Encoder: LocalEncoder (offline, rule-based)")
    return LocalEncoder()


def build_store() -> MemoryStore:
    store = MemoryStore(upkeep=0.05)
    for entry in build_encoder().encode(load_corpus()):
        store.add(entry)
    return store
