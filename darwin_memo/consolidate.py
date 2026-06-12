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

# The near-duplicate similarity floor shared by consolidation merges,
# SurvivalConfig.merge_threshold, and conflict surfacing in retrieval:
# one constant so "near duplicate" cannot drift between the path that
# merges entries and the path that flags them as overlapping advice.
# Over cosine retrievers raise it toward EMBEDDING_MERGE_THRESHOLD.
DEFAULT_MERGE_THRESHOLD = 0.55


def consolidate(
    store: MemoryStore,
    cycle: int,
    threshold: float = DEFAULT_MERGE_THRESHOLD,
    exclude: frozenset[str] | set[str] = frozenset(),
) -> int:
    """Merge clusters of similar alive entries. Returns merges performed.

    Entries in ``exclude`` never merge: the Ledger excludes entries with
    unsettled outcomes so a pending verdict's provenance ids stay valid.
    Pinned entries never merge either, as anchor or member: a merge
    would bury the pinned id and pool its text into an unpinned heir,
    which is exactly the removal pinning exists to forbid.

    Probationary and juvenile entries are excluded for the same shape
    of reason: a merge would launder the lifecycle. The CONSOLIDATED
    heir starts with probation and juvenile at zero, so a poisoned
    import that near-duplicates a strong local entry (the attacker
    controls the text) would pool into an heir that carries the poison
    answer, full deciding rights, and the cluster's energy, skipping
    every settlement probation exists to demand (docs/threat-model.md).
    They merge like anyone else once they graduate.
    """
    alive = sorted(
        (
            e
            for e in store.alive()
            if e.id not in exclude
            and not e.pinned
            and e.probation <= 0
            and e.juvenile <= 0
        ),
        key=lambda e: e.energy,
        reverse=True,
    )
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
        # The merged entry carries its newest member's timestamp, not a
        # fresh one: the content was recorded then, and stamping merge
        # time would make stale advice look current on every consult
        # surface. Empty (age unknown) when no member has a timestamp.
        recorded_ts=max(m.recorded_ts for m in cluster),
        uses=sum(m.uses for m in cluster),
        lineage=[m.id for m in cluster],
    )
