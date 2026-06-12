"""Temporal awareness for retrieval surfaces.

Survival selection culls entries only after they cause damage, so a
stale-but-once-correct entry keeps earning until the world changes
enough to hurt. This module adds the time dimension to what gets
surfaced, never to what gets paid: everything here is a pure rendering
or ranking concern, and none of it reads or writes energy.

Three pieces:

- :func:`age_annotation` renders an entry's age (UTC timestamp when
  recorded, born tick, last settlement tick) so any text surface can
  carry it. Entries persisted before ``recorded_ts`` existed render as
  "age unknown" rather than faking a date.
- :func:`recency_weight` is the optional half-life decay for ranking
  scores. Off unless a caller passes a half-life, and balances and
  credit assignment never see it either way.
- :func:`conflict_clusters` groups near-duplicate retrieval hits with
  the same similarity machinery and threshold semantics consolidation
  uses, so overlapping advice surfaces dated and newest first instead
  of being silently resolved by rank order. Mechanical throughout: no
  LLM judges anything here.

:func:`render_consult` is the single choke point that turns retrieval
hits into the text a consult surface shows, so the CLI, the ledger,
and the MCP server cannot drift apart in how they date their answers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .types import MemoryEntry

SimilarityFn = Callable[[MemoryEntry, MemoryEntry], float]

CONFLICT_LABEL = "conflicting/overlapping advice, newest first"
CONFLICT_HEADER = CONFLICT_LABEL + ":"


def age_annotation(entry: MemoryEntry) -> str:
    """One bracketed age line for surfaced entry text.

    Carries the three temporal facts an agent needs to discount stale
    advice: the UTC moment the entry was recorded, the tick it was
    born, and the tick that last settled an outcome onto it. Entries
    without a recorded timestamp say "age unknown" instead of
    inventing one.
    """
    recorded = f"recorded {entry.recorded_ts}" if entry.recorded_ts else "age unknown"
    if entry.last_used_cycle >= 0:
        settled = f"last settled tick {entry.last_used_cycle}"
    else:
        settled = "never settled"
    return f"[{recorded}; born tick {entry.born_cycle}; {settled}]"


def newest_first(entries: Sequence[MemoryEntry]) -> list[MemoryEntry]:
    """Mechanical recency order: recorded timestamp, then born tick.

    ISO-8601 UTC strings sort lexicographically, so no parsing is
    needed. Entries without a timestamp sort oldest, the honest reading
    of "age unknown".
    """
    return sorted(entries, key=lambda e: (e.recorded_ts, e.born_cycle), reverse=True)


def recency_weight(entry: MemoryEntry, now_cycle: int, half_life: float) -> float:
    """Half-life decay over ticks since the entry last settled.

    A pure ranking multiplier: 1.0 at age zero, 0.5 one half-life
    later. Age counts from the last settlement tick (the born tick if
    nothing ever settled), because a settlement is the last moment the
    world confirmed the entry. Balances and survival economics never
    see this number. A non-positive ``half_life`` raises ``ValueError``:
    there is no honest decay rate at or below zero.
    """
    if half_life <= 0:
        raise ValueError(f"half_life must be positive, got {half_life}")
    last_confirmed = (
        entry.last_used_cycle if entry.last_used_cycle >= 0 else entry.born_cycle
    )
    age = now_cycle - last_confirmed
    if age <= 0:
        return 1.0
    return float(0.5 ** (age / half_life))


def conflict_clusters(
    entries: Sequence[MemoryEntry],
    similarity: SimilarityFn,
    threshold: float,
) -> list[list[MemoryEntry]]:
    """Group near-duplicate entries, newest first within each group.

    The same anchor-based clustering shape as
    :func:`darwin_memo.consolidate.consolidate` and the same threshold
    semantics, reused here so "near duplicate" cannot mean two
    different things in one package. Only groups of two or more come
    back: a lone entry has nothing to conflict with.
    """
    clusters: list[list[MemoryEntry]] = []
    consumed: set[str] = set()
    for i, anchor in enumerate(entries):
        if anchor.id in consumed:
            continue
        cluster = [anchor]
        for other in entries[i + 1 :]:
            if other.id in consumed:
                continue
            if similarity(anchor, other) >= threshold:
                cluster.append(other)
                consumed.add(other.id)
        if len(cluster) > 1:
            clusters.append(newest_first(cluster))
    return clusters


def render_consult(
    hits: Sequence[tuple[MemoryEntry, float]],
    similarity: SimilarityFn,
    threshold: float,
) -> str:
    """Turn retrieval hits into the dated text a consult surface shows.

    A single clear winner surfaces as its answer plus an age line. When
    other hits overlap the winner above the near-duplicate threshold,
    nothing is silently preferred: the whole group surfaces, each entry
    with its dates, newest first. Provenance and credit assignment are
    untouched; only the displayed text changes.
    """
    if not hits:
        return ""
    entries = [entry for entry, _ in hits]
    top = entries[0]
    group = next(
        (
            cluster
            for cluster in conflict_clusters(entries, similarity, threshold)
            if any(e.id == top.id for e in cluster)
        ),
        None,
    )
    if group is None:
        return f"{top.answer}\n{age_annotation(top)}"
    lines = [CONFLICT_HEADER]
    lines.extend(f"- {e.answer} {age_annotation(e)}" for e in group)
    return "\n".join(lines)
