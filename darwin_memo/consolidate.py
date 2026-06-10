"""Negative-Space Learning: consolidation and pruning.

The survival paper observes that improvement shows up less as invention
of new strategies and more as "continual reallocation of probability
mass over an evolving behavioral repertoire": effective behaviors get
reinforced and cluster, ineffective ones fade. Applied to memory, that
becomes a periodic pass that merges clusters of semantically overlapping
survivors into single consolidated entries (their energy pools, their
lineage is recorded) while dead entries have already been pruned by
upkeep. Population shrinks, capability per entry rises.
"""

from __future__ import annotations

from .store import MemoryStore
from .types import EntryKind, MemoryEntry


def consolidate(store: MemoryStore, cycle: int, threshold: float = 0.55) -> int:
    """Merge clusters of similar alive entries. Returns merges performed."""
    alive = sorted(store.alive(), key=lambda e: e.energy, reverse=True)
    consumed: set[str] = set()
    merges = 0

    for anchor in alive:
        if anchor.id in consumed:
            continue
        cluster = [anchor]
        for other in alive:
            if other.id == anchor.id or other.id in consumed:
                continue
            if store.similarity(anchor, other) >= threshold:
                cluster.append(other)
                consumed.add(other.id)
        if len(cluster) == 1:
            continue

        merged = _merge(cluster, cycle, max_energy=store.max_energy)
        for member in cluster:
            store.bury(member.id)
        consumed.add(anchor.id)
        store.add(merged)
        merges += 1

    return merges


def _merge(cluster: list[MemoryEntry], cycle: int, max_energy: float) -> MemoryEntry:
    """The cluster's energy pools into one entry; nothing is created or lost."""
    anchor = cluster[0]
    answers = list(dict.fromkeys(m.answer for m in cluster))
    sources = list(dict.fromkeys(s for m in cluster for s in m.sources))
    return MemoryEntry(
        question=anchor.question,
        answer=" ".join(answers[:3]),
        kind=EntryKind.CONSOLIDATED,
        sources=sources,
        energy=min(max_energy, sum(m.energy for m in cluster)),
        born_cycle=cycle,
        uses=sum(m.uses for m in cluster),
        lineage=[m.id for m in cluster],
    )
