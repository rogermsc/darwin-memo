"""Core data types shared across the package."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    """UTC now in ISO-8601 at second precision, the one timestamp format
    used package-wide (entry birth stamps, ledger history, event log)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EntryKind(str, Enum):
    """How a memory entry came to exist.

    The first five kinds mirror the MeMo reflection-QA synthesis steps.
    EXPERIENCE entries are written from successful trajectories, the
    memory-layer analog of the survival paper's fine-tuning on surviving
    behaviors. CONSOLIDATED entries are produced by Negative-Space
    consolidation merges.
    """

    EXPLICIT = "explicit"
    INFERRED = "inferred"
    ENTITY = "entity"
    CROSS_DOC = "cross_doc"
    EXPERIENCE = "experience"
    CONSOLIDATED = "consolidated"


@dataclass
class MemoryEntry:
    """A single unit of memory, stored as a self-contained QA pair.

    Energy is the survival currency: every cycle charges upkeep, and the
    only way to earn energy back is to contribute to a task whose outcome
    persists in the environment. There is no quality score and no judge.

    ``recorded_ts`` is the UTC wall-clock moment the entry was created,
    so every surface that shows the entry can show its age. Entries
    persisted before the field existed load as the empty string and
    render as "age unknown": faking a timestamp at load time would be
    exactly the time-blindness this field exists to fix.
    """

    question: str
    answer: str
    kind: EntryKind = EntryKind.EXPLICIT
    sources: list[str] = field(default_factory=list)
    energy: float = 1.0
    born_cycle: int = 0
    recorded_ts: str = field(default_factory=utc_now_iso)
    last_used_cycle: int = -1
    uses: int = 0
    lineage: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def alive(self) -> bool:
        return self.energy > 1e-9

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["kind"] = self.kind.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MemoryEntry:
        d = dict(d)
        d["kind"] = EntryKind(d["kind"])
        # Files saved before recorded_ts existed carry no timestamp; the
        # honest default is "age unknown" (empty), never load time.
        d.setdefault("recorded_ts", "")
        return cls(**d)


@dataclass
class Outcome:
    """What the environment reports after a task is acted on.

    ``delta`` is a change in a conserved, externally measurable resource
    (bytes freed, tests passing, budget remaining). It is the outcome
    itself, never a model's opinion of the outcome. This is the survival
    paper's central design constraint and the reason proxy optimization
    and reward hacking have nothing to attach to.
    """

    delta: float
    detail: str = ""


@dataclass
class Trajectory:
    """One task attempt: which entries were consulted and what happened."""

    cycle: int
    task: str
    answer: str
    deciding_entry: str | None
    supporting_entries: list[str]
    outcome: Outcome


@dataclass
class CycleStats:
    """Population accounting for one survival cycle.

    ``silent`` counts tasks where memory produced no answer at all. A
    persistently high silence rate is the single best debugging signal:
    it means retrieval cannot connect your task phrasing to your corpus
    (or your action vocabulary is not being read), nothing ever earns,
    and the whole population will starve at roughly
    ``spawn_energy / upkeep`` cycles regardless of how good the
    knowledge is.
    """

    cycle: int
    population: int
    births: int
    deaths: int
    merges: int
    total_energy: float
    resource_delta: float
    tasks: int = 0
    silent: int = 0
    nonzero_outcomes: int = 0
