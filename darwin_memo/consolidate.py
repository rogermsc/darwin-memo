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


# How much provenance agreement a merge requires. "off" is the published
# behaviour and merges on similarity alone. The other two exist because
# limitations.tex names "a merge that refuses to pool entries across
# trust boundaries" as the obvious fix for consolidation laundering and
# had not evaluated one; see docs/benchmarks.md for what each is worth.
SOURCE_POLICIES = ("off", "shared", "identical")


def consolidate(
    store: MemoryStore,
    cycle: int,
    threshold: float = DEFAULT_MERGE_THRESHOLD,
    exclude: frozenset[str] | set[str] = frozenset(),
    source_policy: str = "off",
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

    ``source_policy`` requires provenance agreement on top of
    similarity. ``"shared"`` needs one source common to the whole
    cluster, which is the natural reading of a trust boundary and is
    weaker than it sounds: an encoder that writes cross-document
    entries has already crossed the boundary before consolidation sees
    anything. ``"identical"`` needs the cluster to agree on the whole
    source set, which is what actually refuses a merge between a
    single-document entry and a cross-document one. The common set is
    narrowed as members join rather than tested pairwise against the
    anchor, so A-B and A-C cannot transitively pool B with C.

    ``"off"`` is the published behaviour and merges on similarity alone.
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

    if source_policy not in SOURCE_POLICIES:
        raise ValueError(
            f"unknown source_policy: {source_policy!r}, want one of {SOURCE_POLICIES}"
        )

    for anchor in alive:
        if anchor.id in consumed:
            continue
        cluster = [anchor]
        common = set(anchor.sources)
        for other in alive:
            if other.id == anchor.id or other.id in consumed:
                continue
            agreed = _agree(common, other.sources, source_policy)
            if agreed is None:
                continue
            if store.similarity(anchor, other) >= threshold:
                cluster.append(other)
                consumed.add(other.id)
                common = agreed
        if len(cluster) == 1:
            continue

        merged = _merge(cluster, cycle, max_energy=store.max_energy)
        for member in cluster:
            store.bury(member.id)
        consumed.add(anchor.id)
        store.add(merged)
        merges += 1

    return merges


def _agree(common: set[str], sources: list[str], policy: str) -> set[str] | None:
    """The cluster's surviving common provenance, or None to refuse.

    An entry with no sources at all is refused by both policies rather
    than treated as universally compatible: unknown provenance is the
    case a trust boundary exists for, and letting it merge with anything
    would make the strictest setting the loosest one on exactly the
    entries nobody can vouch for.
    """
    if policy == "off":
        return common
    other = set(sources)
    if not common or not other:
        return None
    if policy == "identical":
        return common if common == other else None
    shared = common & other
    return shared or None


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
