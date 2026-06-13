"""judge_settled: settlement by LLM verdict instead of measured outcomes.

The package's differentiating claim is "no judge anywhere": selection
pressure comes from a conserved, measured resource, never from a
model's opinion of success. That claim needs a control arm, not a
slogan, so this arm IS the judge. The driver answers and acts exactly
like every baseline, but settlement (keep or cull, the survival
ledger's job) is decided by a local LLM that reads each deciding
entry's lesson together with the environment's own description of the
outcomes that lesson produced this cycle. arXiv 2605.12978 predicts
the failure mode this arm goes looking for: continuously updated
memories settled by judge go faulty, because a judge grades
plausibility and prose where the ledger weighs measured consequences.

Design decisions, stated because they shape the result:

- One batched call per cycle, listing every entry that decided at
  least one MEASURED task (nonzero delta, the same events that move
  ledger credit). Requests to a local Ollama server queue behind
  whatever else the machine is running, so per-entry calls would
  multiply waiting, and a batched verdict is also the cheaper shape a
  practitioner would deploy.
- The judge sees the outcome descriptions (the env's ``detail``
  strings). On the clean environment those name what really happened,
  so the judge arm gets MORE per-event information than the ledger's
  scalar delta; losing from there is the interesting result. Under
  measurement noise the corrupted detail strings name both the
  reported and the true delta, ground truth no in-loop component may
  read, so the runner refuses this arm under noise loudly.
- Unparseable replies, missing ids, and unknown verdicts default to
  keep and are counted (``judge_failures``): the conservative reading
  of an unreadable verdict, and a measured failure mode rather than a
  crash or a silent cull.
- Opt-in, never CI: sampled model output is not deterministic (the
  lesson store's first entry), same tier as ``survival_llm``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from darwin_memo import Environment, MemoryEntry, MemoryStore, QueryProtocol
from darwin_memo.llm import LLMClient, parse_json_array

from .policies import CycleRecord, OnCycle, PolicyResult

VERDICTS = ("keep", "cull")

JUDGE_SYSTEM = (
    "You are the settlement judge for an agent memory store. Each entry "
    "below is a lesson the agent consulted, shown with the decisions it "
    "produced this cycle and the environment's description of each "
    "outcome. Decide for every entry whether it stays in memory (keep) "
    "or is removed (cull). Respond with only a JSON array, no other text."
)

# A judged candidate: the entry plus the (task prompt, outcome detail)
# pairs for the measured tasks it decided this cycle.
Candidate = tuple[MemoryEntry, list[tuple[str, str]]]


@dataclass
class JudgeResult(PolicyResult):
    """PolicyResult plus the judge's own observability.

    ``extra_metrics`` is folded into the run's metrics by
    ``runner.run_one`` as extra, never required, keys: the required
    set stays suite-uniform (see the lesson on new metric keys).
    """

    judge_calls: int = 0
    judge_failures: int = 0  # verdicts missing or unreadable, kept by default
    judge_culls: int = 0
    judge_wall_s: float = 0.0

    @property
    def extra_metrics(self) -> dict[str, float]:
        return {
            "judge_calls": float(self.judge_calls),
            "judge_failures": float(self.judge_failures),
            "judge_culls": float(self.judge_culls),
            "judge_wall_s": round(self.judge_wall_s, 4),
        }


def judge_prompt(candidates: list[Candidate]) -> str:
    lines = ["Judge these memory entries."]
    for entry, events in candidates:
        lines += [
            "",
            f"Entry {entry.id}",
            f"lesson question: {entry.question}",
            f"lesson answer: {entry.answer}",
            "decisions this cycle:",
        ]
        for prompt, detail in events:
            lines += [f"- task: {prompt}", f"  outcome: {detail}"]
    lines += [
        "",
        "Respond with only a JSON array holding one object per entry id",
        'listed above, like [{"id": "<entry id>", "verdict": "keep"}].',
        'Every verdict must be "keep" or "cull".',
    ]
    return "\n".join(lines)


def parse_verdicts(text: str, expected_ids: set[str]) -> dict[str, str]:
    """Pull {entry id: verdict} out of a judge reply.

    Think blocks and code fences are tolerated via ``parse_json_array``.
    Anything else (wrong shape, unknown id, unknown verdict) is dropped;
    the caller counts the omission as a judge failure and the entry
    defaults to keep.
    """
    verdicts: dict[str, str] = {}
    for item in parse_json_array(text):
        if not isinstance(item, dict):
            continue
        entry_id = str(item.get("id", "")).strip()
        verdict = str(item.get("verdict", "")).strip().lower()
        if entry_id in expected_ids and verdict in VERDICTS:
            verdicts[entry_id] = verdict
    return verdicts


def run_judge_settled(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    judge: LLMClient,
    on_cycle: OnCycle | None = None,
) -> JudgeResult:
    """Answer and act like every baseline; settle by judge verdict.

    The task loop mirrors ``policies._baseline_task_loop`` (usage
    tracking included, so populations stay comparable) but keeps the
    per-entry outcome descriptions the judge needs, which the shared
    driver deliberately does not expose to its victim selectors.
    """
    result = JudgeResult()
    for cycle in range(cycles):
        protocol = QueryProtocol(store)
        delta = 0.0
        decided: dict[str, list[tuple[str, str]]] = {}
        for task in env.tasks(cycle):
            answer = protocol.answer(task.prompt)
            outcome = env.verify(task, answer.text)
            delta += outcome.delta
            if answer.deciding_entry and outcome.delta != 0:
                decided.setdefault(answer.deciding_entry, []).append(
                    (task.prompt, outcome.detail)
                )
            consulted = list(answer.supporting_entries)
            if answer.deciding_entry:
                consulted.append(answer.deciding_entry)
            for entry_id in consulted:
                entry = store.get(entry_id)
                if entry is not None:
                    entry.uses += 1
                    entry.last_used_cycle = cycle

        candidates: list[Candidate] = []
        for entry_id, events in decided.items():
            entry = store.get(entry_id)
            if entry is not None:
                candidates.append((entry, events))

        victims: list[MemoryEntry] = []
        if candidates:
            prompt = judge_prompt(candidates)
            start = time.perf_counter()
            reply = judge.complete(prompt, system=JUDGE_SYSTEM)
            result.judge_wall_s += time.perf_counter() - start
            result.judge_calls += 1
            verdicts = parse_verdicts(reply, {entry.id for entry, _ in candidates})
            for entry, _events in candidates:
                verdict = verdicts.get(entry.id)
                if verdict is None:
                    result.judge_failures += 1
                elif verdict == "cull":
                    victims.append(entry)

        for entry in victims:
            store.bury(entry.id)
        result.judge_culls += len(victims)
        record = CycleRecord(cycle, len(store), len(victims), delta)
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result
