"""Synthetic corpus generation for the scaling probe."""

from __future__ import annotations

import random

from darwin_memo import EntryKind, MemoryEntry

_SERVICE_TEXT = (
    "billing ledger checkout inventory shipping auth profile search "
    "analytics export ingest notifier scheduler archiver indexer"
)
_SERVICES = _SERVICE_TEXT.split()
_RESOURCES = [
    "logs",
    "caches",
    "snapshots",
    "reports",
    "queues",
    "backups",
    "indexes",
    "manifests",
]
_POLICIES = (
    "may be deleted after {n} days",
    "must be retained for {n} years",
    "are rotated every {n} hours",
    "are owned by the {svc} team",
    "are mirrored to region-{n} nightly",
)


def synthetic_entries(n: int, seed: int) -> list[MemoryEntry]:
    """Deterministic templated QA pairs with realistic lexical overlap."""
    rng = random.Random(seed)
    entries: list[MemoryEntry] = []
    for i in range(n):
        svc = rng.choice(_SERVICES)
        resource = rng.choice(_RESOURCES)
        policy = rng.choice(_POLICIES).format(n=rng.randint(2, 90), svc=svc)
        entries.append(
            MemoryEntry(
                question=f"What is the policy for {svc} {resource} (item {i})?",
                answer=f"The {svc} {resource} {policy}.",
                kind=EntryKind.EXPLICIT,
                sources=[f"synthetic-{seed}"],
            )
        )
    return entries


def synthetic_queries(n: int, seed: int) -> list[str]:
    rng = random.Random(seed + 99)
    return [
        f"What is the policy for {rng.choice(_SERVICES)} {rng.choice(_RESOURCES)}?"
        for _ in range(n)
    ]
