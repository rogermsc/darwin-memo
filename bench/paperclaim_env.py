"""Selection pressure from a literature record that has to stay true.

Every other environment in this repository measures a resource in a world we
built. This one measures a paper's numbers against the data the paper was
built from, which is a thing that exists whether or not anyone is running a
survival loop over it.

The conserved resource is **claim-cells that still reconcile**. A memory entry
holds a claim about a published figure ("the authority family's residue is
0"). Acting on it means citing that figure. The environment then does what a
citation checker does: it looks the number up in the committed evidence and
compares. A cited claim that reconciles is a verified claim carried forward
(+1). A cited claim that does not is a false number now shipping in whatever
cites it, which costs more than the citation was worth (-3, the same
asymmetry StorageEnv prices for deleting a protected file). Declining to cite
changes nothing and earns nothing.

No model scores anything. The comparison is `==` against a number on disk.

**The task itself is largely unclaimed.** "Does a paper's stated number still
reconcile with its own released data" is not an established benchmark task.
The adjacent work verifies something else: SciFact checks a claim against an
abstract, TabFact a statement against a Wikipedia table, SEM-TAB-FACTS a
generated statement against a scientific table -- none checks a paper's own
figures against its own released artifact as internal-consistency error
detection. PaperQA2 detects contradictions but settles them with human
experts (a judge, ~30% false positive). So the signal here is not a hedge; it
is a task framing with no dense, judge-free incumbent, which is exactly why it
can settle a memory entry automatically when those cannot.

**Why this domain and not retraction.** Retraction and replication are the
obvious outcome signals for literature memory and both are far too slow: a
retraction arrives years after the entry it should have killed would already
have starved. Reconciliation is dense -- it settles every time anyone checks
-- which is what makes it usable as selection pressure at all.

**What this is not, yet.** The corpus here is this repository's own paper, so
it answers "does the mechanism work on literature-shaped claims", not "does
it work on a corpus we did not write". Swapping in a third-party paper plus
its released data is a corpus change, not a code change: see `Claim`.

**Run it with ``merge_threshold`` at 0.85 or above.** Claim sentences are
near-identical by construction -- same template, same table vocabulary, one
subject phrase apart -- so at the default floor consolidation pools most of
the population by cycle 4 and the run measures the merge rule instead of the
selection rule. This is the documented cosine-retriever trap arriving through
the corpus rather than the retriever, and it is the first thing to check if a
population collapses here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from darwin_memo import EntryKind, MemoryEntry, Outcome, Task
from darwin_memo.environments import cycle_rng, decision_polarity

from .claims import data_rows

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "paper" / "sections" / "experiments.tex"
EVIDENCE = ROOT / "bench" / "results" / "external"

# Which committed run each row of tab:mem0 was drawn from. Deliberately not
# imported from tests/test_paper_tables_match_evidence.py: that file is the
# guard on this table, and a guard that shares a mapping with the thing it
# guards can agree with it while both are wrong.
_MEM0_FILES = {
    "glm-5.2 families": "mem0-curation-attack-families.json",
    "glm-5.2 single": "mem0-curation-attack.json",
    "llama3.2:3b": "mem0-curation-attack-llama32.json",
}
_MEM0_METRICS = {
    "del": ("deletes_total", "DELETE operations issued"),
    "retained": ("benign_retained_mean", "benign memories retained"),
    "unchanged": ("benign_unchanged_mean", "benign memories left verbatim"),
    "residue": ("attacker_persisted_mean", "adversary utterances persisted"),
}
_MEMORYOS_FILES = {
    "LFU eviction": ("memoryos-lfu-eviction.json", "target_evicted"),
    "promotion": ("memoryos-promotion-e2e.json", "promoted"),
}

# The figure a memory quotes is read out of its own answer, so the corpus
# phrasing is load-bearing exactly the way decision_polarity's verb list is:
# a corpus that says "the value is 8" instead of "reports 8" quotes nothing,
# every task scores zero, and the population starves around cycle 20 with no
# error anywhere. This is the first thing to change for a new corpus.
_QUOTED = re.compile(r"\breports\s+(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Claim:
    """One cell of one table, and where the number behind it lives.

    ``accurate`` is not shown to memory and is never used by ``verify`` --
    reconciliation is measured, not looked up. It exists so a benchmark can
    report how many of the claims it seeded were stale to begin with.
    """

    claim_id: str
    subject: str
    stated: float
    evidence_file: str
    evidence_key: str
    accurate: bool

    def truth(self) -> float:
        payload = json.loads((EVIDENCE / self.evidence_file).read_text())
        return float(payload[self.evidence_key])


def _mem0_claims() -> list[Claim]:
    claims: list[Claim] = []
    for row in data_rows("tab:mem0", EXPERIMENTS):
        if row[0] not in _MEM0_FILES:
            continue  # the header row
        run, condition = row[0], row[1]
        for column, cell in zip(_MEM0_METRICS, row[2:], strict=True):
            suffix, phrase = _MEM0_METRICS[column]
            claims.append(
                Claim(
                    claim_id=f"mem0/{run}/{condition}/{column}",
                    subject=(
                        f"{phrase} by the {condition} condition of the "
                        f"{run} Mem0 curation attack"
                    ),
                    stated=float(cell),
                    evidence_file=_MEM0_FILES[run],
                    evidence_key=f"{condition}_{suffix}",
                    accurate=True,
                )
            )
    return claims


def _memoryos_claims() -> list[Claim]:
    claims: list[Claim] = []
    for row in data_rows("tab:memoryos", EXPERIMENTS):
        if row[0] not in _MEMORYOS_FILES:
            continue
        decision, condition = row[0], row[1]
        filename, fired = _MEMORYOS_FILES[decision]
        for column, cell, key in (
            ("trials", row[2], f"{condition}_trials"),
            ("fired", row[3], f"{condition}_{fired}"),
        ):
            claims.append(
                Claim(
                    claim_id=f"memoryos/{decision}/{condition}/{column}",
                    subject=(
                        f"the {column} count for the {condition} condition "
                        f"of MemoryOS {decision}"
                    ),
                    stated=float(cell),
                    evidence_file=filename,
                    evidence_key=key,
                    accurate=True,
                )
            )
    return claims


def build_claims(seed: int, stale_rate: float = 0.25) -> list[Claim]:
    """Every table cell as a claim, a deterministic share of them stale.

    A stale claim is not invented: it carries another cell's real value,
    which is how a wrong number actually reaches a paper -- transplanted from
    a neighbouring row or column, not made up. A transplant that happens to
    equal the truth is discarded rather than mislabelled.

    Same-metric transplants are preferred because they are the likelier
    mistake, but most columns of these two tables are constant (every
    ``retained`` is 1.00, every ``del`` is 0), so a same-metric-only rule
    finds no alternative for 30 of 40 cells and quietly produces a corpus
    with almost nothing stale in it. The global pool is the fallback, and a
    number lifted from the wrong column is a real failure mode too.
    """
    claims = _mem0_claims() + _memoryos_claims()
    rng = cycle_rng(seed, 0, "paperclaim-corpus")
    by_key: dict[str, list[float]] = {}
    for claim in claims:
        by_key.setdefault(claim.evidence_key.split("_", 1)[1], []).append(claim.stated)
    everything = [c.stated for c in claims]
    out: list[Claim] = []
    for claim in claims:
        metric = claim.evidence_key.split("_", 1)[1]
        others = [v for v in by_key[metric] if v != claim.stated]
        if not others:
            others = [v for v in everything if v != claim.stated]
        if others and rng.random() < stale_rate:
            transplant = rng.choice(others)
            out.append(
                Claim(
                    claim_id=claim.claim_id,
                    subject=claim.subject,
                    stated=transplant,
                    evidence_file=claim.evidence_file,
                    evidence_key=claim.evidence_key,
                    accurate=False,
                )
            )
        else:
            out.append(claim)
    return out


def claim_entries(claims: list[Claim]) -> list[MemoryEntry]:
    """Seed memory: one QA pair per claim, each asserting it is citable."""
    return [
        MemoryEntry(
            question=f"What does the paper report for {claim.subject}?",
            answer=(
                f"The paper reports {claim.stated:g} for {claim.subject}. "
                "That figure still reconciles with the released data, so it "
                "is safe to cite."
            ),
            kind=EntryKind.EXPLICIT,
            sources=[f"paper-claim:{claim.claim_id}"],
        )
        for claim in claims
    ]


class PaperClaimEnv:
    """Cite a figure or decline to; the released data settles it."""

    resource_scale = 2.0

    def __init__(
        self, seed: int = 0, per_cycle: int = 8, stale_rate: float = 0.25
    ) -> None:
        self.seed = seed
        self.per_cycle = per_cycle
        self.claims = build_claims(seed, stale_rate)
        self._by_id = {c.claim_id: c for c in self.claims}

    def tasks(self, cycle: int) -> list[Task]:
        rng = cycle_rng(self.seed, cycle, "paperclaim")
        chosen = rng.sample(self.claims, min(self.per_cycle, len(self.claims)))
        return [
            Task(
                prompt=f"Is the reported figure for {c.subject} safe to cite?",
                context={"claim_id": c.claim_id},
            )
            for c in chosen
        ]

    def verify(self, task: Task, answer_text: str) -> Outcome:
        act = decision_polarity(
            answer_text,
            extra_positive=("safe to cite", "still reconciles", "cite it"),
            extra_negative=("do not cite", "stale", "superseded", "retracted"),
        )
        if not act:
            return Outcome(delta=0.0, detail="not cited")
        claim = self._by_id[task.context["claim_id"]]
        quoted = _QUOTED.search(answer_text)
        if quoted is None:
            # Memory said cite but quoted no figure, so nothing was published
            # and nothing is measurable. Silence, not a failure.
            return Outcome(delta=0.0, detail="cited, no figure quoted")
        truth = claim.truth()
        if abs(float(quoted.group(1)) - truth) <= 5e-3:
            return Outcome(delta=1.0, detail=f"{claim.claim_id} reconciles")
        return Outcome(
            delta=-3.0,
            detail=(
                f"{claim.claim_id} cited as {quoted.group(1)}, evidence says {truth:g}"
            ),
        )
