"""Instrumentation for the LLM-mode benchmark arm.

The survival_llm arm runs the real 3-stage protocol with a local model
answering, so the run itself is the citation-fidelity sample: every
task answer takes one of the attribution paths citation_probe.py
classifies (cited / explicit_none / fallback / refused /
unattributed_action). This module wraps the protocol so the arm
records, per answer, the raw completions and the path taken, and folds
the per-run rates into the metrics block, where the report's bootstrap
machinery treats them like any other per-seed value.

Network-dependent by design (the client is Ollama), but everything
here is testable offline with a scripted client; tests inject one
through ``build_audited_protocol``'s monkeypatched OllamaClient.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from darwin_memo import MemoryStore, OllamaClient, QueryProtocol
from darwin_memo.protocol import ProtocolAnswer
from darwin_memo.types import EntryKind

from .citation_probe import CLASSIFICATION_KEYS, RecordingClient, classify_answer


class AuditedProtocol(QueryProtocol):
    """QueryProtocol that classifies every answer's attribution path."""

    def __init__(
        self,
        store: MemoryStore,
        client: Any,
        refuse_unparseable: bool = False,
    ) -> None:
        self.recorder = RecordingClient(client)
        super().__init__(store, self.recorder, refuse_unparseable=refuse_unparseable)
        # One record per protocol answer: the raw completions behind it
        # plus the classification of the path the protocol took.
        self.answers: list[dict[str, Any]] = []

    def answer(
        self,
        query: str,
        k: int = 3,
        *,
        half_life: float | None = None,
        now_cycle: int | None = None,
        kind: EntryKind | str | None = None,
        source: str | None = None,
    ) -> ProtocolAnswer:
        before = len(self.recorder.calls)
        result = super().answer(
            query,
            k,
            half_life=half_life,
            now_cycle=now_cycle,
            kind=kind,
            source=source,
        )
        calls = self.recorder.calls[before:]
        record = classify_answer(calls[-1]["raw"] if calls else "", result)
        record["query"] = query
        record["answer"] = result.text[:200]
        self.answers.append({"calls": calls, "classification": record})
        return result


def build_client(overrides: dict[str, Any]) -> OllamaClient:
    """The arm's chat client, configured from run overrides.

    ``llm_think`` defaults to absent: the field is only sent when set,
    because Ollama rejects it on models without the thinking
    capability instead of ignoring it.
    """
    think = overrides.get("llm_think")
    return OllamaClient(
        model=str(overrides.get("llm_model", "llama3.2")),
        timeout=float(overrides.get("llm_timeout", 600.0)),
        max_tokens=int(overrides.get("llm_max_tokens", 1024)),
        think=None if think is None else bool(think),
    )


def build_audited_protocol(
    store: MemoryStore, overrides: dict[str, Any]
) -> AuditedProtocol:
    """The survival_llm arm's protocol, configured from run overrides."""
    client = build_client(overrides)
    return AuditedProtocol(
        store,
        client,
        refuse_unparseable=bool(overrides.get("llm_refuse_unparseable", False)),
    )


class FullContextStore:
    """A store view that hands the reader everything, unranked and unfiltered.

    The baseline the memory literature now settles on is not "no memory" but
    "no memory *system*": put the whole history in the prompt and let the
    model do the selecting. ``keep_everything_llm`` is not that. It never
    curates, but the model still only sees ``store.retrieve``'s top-k, and
    that call applies the retriever's relevance floor -- so it measures a
    store with no eviction, not a reader with no retrieval.

    This proxies the store and replaces exactly one method. Everything else,
    including the energy ledger the surrounding policy does not use, passes
    through untouched, so the arm differs from its control in one place and
    a reader can see where.

    A uniform score of 1.0 is not a ranking claim. Entries arrive in store
    order and the protocol's own tie-breaking decides the rest, which is the
    point: nothing here is choosing for the model.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def retrieve(self, query: str, k: int = 3, **kwargs: Any) -> Any:
        return [(entry, 1.0) for entry in self._store.alive()]


def build_full_context_protocol(
    store: MemoryStore, overrides: dict[str, Any]
) -> AuditedProtocol:
    """The full_context_llm arm: same model, same audit trail, no retrieval."""
    client = build_client(overrides)
    return AuditedProtocol(
        FullContextStore(store),  # type: ignore[arg-type]
        client,
        refuse_unparseable=bool(overrides.get("llm_refuse_unparseable", False)),
    )


def citation_metrics(answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-run attribution-path rates, named for the metrics block."""
    n = len(answers)
    metrics: dict[str, Any] = {"llm_queries": n}
    for key in CLASSIFICATION_KEYS:
        hits = sum(1 for a in answers if a["classification"][key])
        metrics[f"citation_{key}_rate"] = hits / n if n else 0.0
    return metrics


def write_transcript(
    path: Path,
    answers: list[dict[str, Any]],
    header: dict[str, Any],
    files_per_cycle: int,
) -> None:
    """One JSONL file per run: a header line, then one line per answer.

    The cycle index is derived from answer order; StorageEnv yields
    exactly ``files_per_cycle`` tasks per cycle and the audited
    protocol only sees loop tasks (final-population probes run through
    a separate local-mode protocol).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"transcript_of": header})]
    for i, answer in enumerate(answers):
        lines.append(
            json.dumps(
                {
                    "index": i,
                    "cycle": i // files_per_cycle,
                    "classification": answer["classification"],
                    "calls": answer["calls"],
                }
            )
        )
    path.write_text("\n".join(lines) + "\n")
