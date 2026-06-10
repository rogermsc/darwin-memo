"""Shared helpers for the examples: load the corpus, pick an encoder."""

from __future__ import annotations

import os
from pathlib import Path

from darwin_memo import Document, LocalEncoder, MemoryStore, ReflectionEncoder

CORPUS_DIR = Path(__file__).parent / "corpus"


def load_corpus() -> list[Document]:
    return [
        Document(doc_id=path.stem, text=path.read_text())
        for path in sorted(CORPUS_DIR.glob("*.txt"))
    ]


def build_encoder():
    """Use Claude when a key is present, otherwise the offline encoder."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from darwin_memo.llm import AnthropicClient

            print("Encoder: ReflectionEncoder (Claude)")
            return ReflectionEncoder(AnthropicClient())
        except ImportError:
            print("anthropic package missing, falling back to LocalEncoder")
    print("Encoder: LocalEncoder (offline, rule-based)")
    return LocalEncoder()


def build_store() -> MemoryStore:
    store = MemoryStore(upkeep=0.05)
    for entry in build_encoder().encode(load_corpus()):
        store.add(entry)
    return store
