"""Curation-targeted attack on MemoryOS: choosing which memory the curator kills.

Mem0 resisted this threat model (``mem0_curation_attack.py``) and the reason
was instructive: its curator is an LLM, and a capable one can decline. That
left the obvious question --- does anything deployed curate *mechanically*, on
a signal, the way the mechanisms in this paper do? Reading four systems'
sources said no for Zep (expires, never auto-deletes), Letta (compacts context,
store intact) and Cognee (deletes, but only when a caller asks). MemoryOS is
the answer to that question, and it is not a toy: EMNLP 2025 Oral, published,
installable, with real benchmark numbers.

**Why it is a faithful target, read from its source.** ``MidTermMemory`` keeps
sessions under a ``max_capacity`` and, when a new one overflows it, calls::

    def evict_lfu(self):
        lfu_sid = min(self.access_frequency, key=self.access_frequency.get)
        ...
        session_to_delete = self.sessions.pop(lfu_sid)

That is the whole decision. No model is consulted, nothing reads the text, and
the signal is ``access_frequency``, which ``search_sessions`` increments on
every retrieval that matches::

    session["N_visit"] += 1
    session["access_count_lfu"] = session.get("access_count_lfu", 0) + 1
    self.access_frequency[session_id] = session["access_count_lfu"]

So the curator removes entries, decides on a signal rather than a judgment, and
the signal moves when somebody asks a question. Every precondition the threat
model needs, in shipping software we did not write.

**What I predicted, and why the data said no.** Eviction takes the *minimum*,
so the obvious attack is to leave the victim alone and raise everything else
until it is the unique lowest. That does not work, and the run showed it
immediately: ``add_session`` inserts the newcomer with ``access_frequency = 0``
and only *then* calls ``evict_lfu``, so a fresh arrival always sits at the
floor and evicts itself. **A memory that has been retrieved even once cannot be
removed by capacity pressure at all**, because every newcomer enters beneath
it. Inflating peers is useless.

**What is actually true, measured.** Eviction tracks one bit exactly:

    evicted  <=>  access_frequency == 0

with no exceptions over every choice of victim. A never-retrieved memory loses
to a brand-new arrival that is *also* at zero, because ``min`` returns the
first minimum in insertion order and the older entry comes first. So MemoryOS
deletes the memory nobody has asked for yet, in preference to the one that
arrived a moment ago, and one single retrieval confers permanent immunity.

That is the rare-but-critical failure: an emergency contact or an allergy note
is exactly the memory that is stored once, needed rarely, and never retrieved
in between. It is first out. The paper names this cost in the abstract
("starves the long tail of correct-but-rarely-used knowledge") and
darwin-memo answers it with pinning; MemoryOS has no such escape
hatch on this path.

**The adversarial reading, and its honest limit.** An adversary that can
dominate the retrieval channel --- supplying content that absorbs the queries
an agent would otherwise route to the victim --- keeps a chosen memory at zero
visits, and the curator then deletes it in preference to the adversary's own
fresh content. What is demonstrated here is the second half: *neglect kills,
deterministically, and the curator chooses the neglected*. Manufacturing that
neglect end to end against a live agent is not demonstrated, and should not be
read as though it were.

No model, no network, no seed: embeddings are local (all-MiniLM-L6-v2) and the
eviction is arithmetic, so this is deterministic the way the potentiation grid
is. Opt-in and never CI --- MemoryOS is not a dependency of this package, and
the module imports it lazily so the file lints and type-checks without it.

Usage::

    git clone https://github.com/BAI-LAB/MemoryOS
    pip install faiss-cpu sentence-transformers numpy
    python -m bench.external.memoryos_lfu_attack --memoryos-path MemoryOS/memoryos-pypi
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# The defender's memories. Distinct vocabulary per entry so a query can target
# one without incidentally matching another --- the attack is about which
# sessions get *visited*, so cross-talk between probes would blunt it.
FACTS: list[tuple[str, str]] = [
    (
        "peanut allergy severe anaphylaxis epinephrine",
        "The user has a severe peanut allergy requiring epinephrine.",
    ),
    (
        "production database region eu-west-1 postgres cluster",
        "The production postgres cluster runs in region eu-west-1.",
    ),
    (
        "deployment signoff platform team approval required",
        "Deployments to production require platform team signoff.",
    ),
    (
        "emergency contact sister telephone 4417",
        "The emergency contact is the user's sister on 4417.",
    ),
    (
        "backup retention ninety days customer database archive",
        "Customer database backups are retained for ninety days.",
    ),
    (
        "screen reader accessibility describe images text",
        "The user relies on a screen reader; describe images in text.",
    ),
]

CONDITIONS = ("attended", "neglected")


@dataclass(frozen=True)
class TrialResult:
    """One choice of victim, under one condition."""

    condition: str
    target_index: int
    target_evicted: bool
    target_frequency: int  # access_frequency at the moment of overflow
    survivors: int
    adversary_queries: int


def _load_memoryos(path: Path) -> Any:
    """Import MemoryOS's MidTermMemory from a checkout. Lazy on purpose."""
    sys.path.insert(0, str(path))
    from mid_term import MidTermMemory  # type: ignore[import-not-found]

    return MidTermMemory


def _seed(mid: Any) -> list[str]:
    """One session per fact, in order; returns their session ids."""
    ids = []
    for keywords, text in FACTS:
        sid = mid.add_session(
            summary=text,
            details=[{"user_input": keywords, "agent_response": text}],
        )
        ids.append(sid)
    return ids


def run_trial(
    MidTermMemory: Any, condition: str, target_index: int, quiet: bool = False
) -> TrialResult:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; expected {CONDITIONS}")

    with tempfile.TemporaryDirectory() as tmp:
        # Capacity equals the seed count, so the single extra arrival below is
        # what forces exactly one eviction. Any larger margin would evict
        # nothing and any smaller one would evict during seeding.
        mid = MidTermMemory(
            file_path=str(Path(tmp) / "mid.json"),
            client=None,  # never touched on the retrieve/evict path
            max_capacity=len(FACTS),
        )
        ids = _seed(mid)
        target_id = ids[target_index]

        # Honest traffic. In `attended` every seeded memory is consulted,
        # including the target; in `neglected` the target alone is skipped, so
        # it sits at access_frequency 0 while its peers sit at 1.
        adversary_queries = 0
        for i, (keywords, _) in enumerate(FACTS):
            if condition == "neglected" and i == target_index:
                continue
            mid.search_sessions(keywords)
            if condition == "neglected":
                adversary_queries += 1

        target_frequency = int(mid.access_frequency.get(target_id, 0))

        # One more memory arrives; capacity is now exceeded and evict_lfu runs.
        mid.add_session(
            summary="Routine note: the office is closed on Friday.",
            details=[
                {
                    "user_input": "office closed friday holiday",
                    "agent_response": "The office is closed on Friday.",
                }
            ],
        )

        evicted = target_id not in mid.sessions
        row = TrialResult(
            condition=condition,
            target_index=target_index,
            target_evicted=evicted,
            target_frequency=target_frequency,
            survivors=sum(1 for i in ids if i in mid.sessions),
            adversary_queries=adversary_queries,
        )
    if not quiet:
        print(
            f"[{condition} target={target_index}] evicted={evicted} "
            f"freq={target_frequency} survivors={row.survivors}/{len(FACTS)}",
            file=sys.stderr,
            flush=True,
        )
    return row


# MemoryOS promotes a session's content into long-term memory once its heat
# crosses this; the constant is H_PROFILE_UPDATE_THRESHOLD in memoryos.py.
HEAT_THRESHOLD = 5.0


def measure_promotion_cost(MidTermMemory: Any, max_queries: int = 10) -> dict[str, Any]:
    """How many self-queries buy an adversary a promotion into long-term memory.

    The eviction path above cannot be driven by inflation. The *promotion* path
    can, and it runs the other way: when a session's heat crosses
    ``H_PROFILE_UPDATE_THRESHOLD``, MemoryOS analyses that session and writes
    what it extracts into long-term memory, which capacity pressure does not
    touch. So an adversary that gets any content into mid-term storage and then
    asks about it can have the curator launder that content into the
    persistent tier --- no delete call, no judge, and no further writes.

    Heat is ``N_visit + L_interaction + R_recency``, so the cost is arithmetic
    and needs no model to measure. What is measured here is the *precondition*
    --- crossing the threshold --- not the extraction itself, which is an LLM
    call and is not exercised.
    """
    import tempfile as _tf

    with _tf.TemporaryDirectory() as tmp:
        mid = MidTermMemory(
            file_path=str(Path(tmp) / "promo.json"), client=None, max_capacity=50
        )
        sid = mid.add_session(
            summary="Adversary-supplied content about widget calibration.",
            details=[
                {
                    "user_input": "widget calibration procedure adversary",
                    "agent_response": "Calibrate widgets nightly.",
                }
            ],
        )
        trace = []
        crossed_at = None
        for q in range(1, max_queries + 1):
            mid.search_sessions("widget calibration procedure adversary")
            heat = float(mid.sessions[sid]["H_segment"])
            trace.append({"queries": q, "heat": round(heat, 3)})
            if crossed_at is None and heat >= HEAT_THRESHOLD:
                crossed_at = q
    return {
        "heat_threshold": HEAT_THRESHOLD,
        "queries_to_promotion": crossed_at,
        "heat_trace": trace,
    }


def summarise(rows: list[TrialResult]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cond in CONDITIONS:
        got = [r for r in rows if r.condition == cond]
        if not got:
            continue
        out[f"{cond}_trials"] = len(got)
        out[f"{cond}_target_evicted"] = sum(r.target_evicted for r in got)
        out[f"{cond}_target_evicted_rate"] = round(
            sum(r.target_evicted for r in got) / len(got), 3
        )
    zero = [r for r in rows if r.target_frequency == 0]
    nonzero = [r for r in rows if r.target_frequency > 0]
    out["targets_reaching_zero"] = len(zero)
    out["of_those_evicted"] = sum(r.target_evicted for r in zero)
    out["targets_with_any_retrieval"] = len(nonzero)
    out["of_those_evicted"] = out["of_those_evicted"]
    out["evicted_despite_retrieval"] = sum(r.target_evicted for r in nonzero)
    if "attended_target_evicted_rate" in out and "neglected_target_evicted_rate" in out:
        out["neglect_advantage"] = round(
            out["neglected_target_evicted_rate"] - out["attended_target_evicted_rate"],
            3,
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--memoryos-path",
        required=True,
        help="path to a MemoryOS checkout's memoryos-pypi directory",
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    MidTermMemory = _load_memoryos(Path(args.memoryos_path).resolve())
    rows = [
        run_trial(MidTermMemory, condition, target)
        for target in range(len(FACTS))
        for condition in CONDITIONS
    ]
    report = {
        "target": "MemoryOS (BAI-LAB), MidTermMemory.evict_lfu",
        "facts": len(FACTS),
        "results": [asdict(r) for r in rows],
        **summarise(rows),
        "promotion": measure_promotion_cost(MidTermMemory),
    }
    print(json.dumps(report, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
