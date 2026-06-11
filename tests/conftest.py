"""Shared test fixtures: one store factory instead of six hand-rolled copies."""

from __future__ import annotations

import pytest

from darwin_memo import MemoryEntry, MemoryStore, Retriever

FLAG_ENTRIES = [
    (
        "Is the schema helper load-bearing?",
        "The schema helper is load-bearing and must be kept.",
        ["runbook"],
    ),
    (
        "What about stale feature flags?",
        "Stale feature flags are redundant and safe to remove.",
        ["runbook"],
    ),
]


@pytest.fixture
def store_factory():
    """Build a seeded store; entries default to the flag/schema pair."""

    def build(
        entries: list[tuple[str, str, list[str]]] | None = None,
        upkeep: float = 0.05,
        retriever: Retriever | None = None,
        **store_kwargs: float,
    ) -> MemoryStore:
        store = MemoryStore(upkeep=upkeep, retriever=retriever, **store_kwargs)
        for question, answer, sources in entries or FLAG_ENTRIES:
            store.add(
                MemoryEntry(question=question, answer=answer, sources=list(sources))
            )
        return store

    return build
