"""MeMo's three-stage query protocol against the memory store.

At inference time MeMo's frozen Executive model interrogates the Memory
model in three stages: grounding (decompose into atomic sub-questions),
entity identification (narrow candidates), answer seeking (synthesize
from supporting facts). The protocol here is the same shape. Memory
responses stay compact and independent of corpus size, which preserves
the constant-time inference property the paper cares about.

The local mode answers from retrieval alone so that environments can
exercise the survival loop offline. The answer also reports which
entries produced it: that provenance is what survival credit assignment
attaches to. Provenance fidelity differs by mode. In local mode the
answer IS the top entry's text, so ``deciding_entry`` is real. In LLM
mode the snippets are numbered and the model cites which it used, so
credit flows to the cited entries (a single citation becomes the
deciding entry). When citations cannot be parsed, the protocol falls
back to spreading credit evenly across everything consulted rather
than inventing a winner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .consolidate import DEFAULT_MERGE_THRESHOLD
from .llm import THINK_RE as _THINK_RE
from .llm import LLMClient
from .store import MemoryStore
from .temporal import (
    CONFLICT_LABEL,
    age_annotation,
    conflict_clusters,
    render_consult,
)
from .types import EntryKind, MemoryEntry


@dataclass
class ProtocolAnswer:
    text: str
    deciding_entry: str | None = None
    supporting_entries: list[str] = field(default_factory=list)
    # The consult-surface rendering of ``text``: the same answer plus
    # age annotations, and a dated conflict block when near-duplicate
    # entries disagree (see darwin_memo.temporal). Acting paths (the
    # survival loop, environments) keep reading ``text``; surfaces that
    # show memory to a model or agent read this.
    annotated_text: str = ""


class QueryProtocol:
    """Grounding, entity identification, answer seeking.

    ``conflict_threshold`` is the near-duplicate similarity floor used
    to flag overlapping retrieval hits as conflicting advice; it reuses
    consolidation's threshold semantics (raise it toward
    ``EMBEDDING_MERGE_THRESHOLD`` over cosine retrievers).
    """

    def __init__(
        self,
        store: MemoryStore,
        client: LLMClient | None = None,
        conflict_threshold: float = DEFAULT_MERGE_THRESHOLD,
    ) -> None:
        self.store = store
        self.client = client
        self.conflict_threshold = conflict_threshold

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
        """Answer a query from memory.

        ``half_life``, ``now_cycle``, ``kind``, and ``source`` pass
        straight through to :meth:`MemoryStore.retrieve`: optional
        recency-weighted ranking and metadata filters, all pure
        retrieval concerns that never touch balances.
        """
        if self.client is None:
            return self._answer_local(query, k, half_life, now_cycle, kind, source)
        return self._answer_llm(query, k, half_life, now_cycle, kind, source)

    # ------------------------------------------------------------------
    # Local mode
    # ------------------------------------------------------------------

    def _answer_local(
        self,
        query: str,
        k: int,
        half_life: float | None,
        now_cycle: int | None,
        kind: EntryKind | str | None,
        source: str | None,
    ) -> ProtocolAnswer:
        hits = self.store.retrieve(
            query,
            k=k,
            half_life=half_life,
            now_cycle=now_cycle,
            kind=kind,
            source=source,
        )
        if not hits:
            return ProtocolAnswer(text="")
        deciding, _ = hits[0]
        return ProtocolAnswer(
            text=deciding.answer,
            deciding_entry=deciding.id,
            supporting_entries=[e.id for e, _ in hits[1:]],
            annotated_text=render_consult(
                hits, self.store.similarity, self.conflict_threshold
            ),
        )

    # ------------------------------------------------------------------
    # LLM mode
    # ------------------------------------------------------------------

    def _answer_llm(
        self,
        query: str,
        k: int,
        half_life: float | None,
        now_cycle: int | None,
        kind: EntryKind | str | None,
        source: str | None,
    ) -> ProtocolAnswer:
        assert self.client is not None
        # Stage 1: grounding. Decompose into atomic sub-questions.
        decomposition = self.client.complete(
            "Decompose this query into at most 4 atomic sub-questions, each "
            "targeting a single fact or constraint. One per line, nothing "
            f"else.\n\nQuery: {query}"
        )
        sub_questions = [
            line.strip(" -.0123456789)")
            for line in decomposition.splitlines()
            if line.strip()
        ][:4]

        consulted: dict[str, MemoryEntry] = {}  # entry id -> entry
        for sub in sub_questions or [query]:
            for entry, _ in self.store.retrieve(
                sub,
                k=2,
                half_life=half_life,
                now_cycle=now_cycle,
                kind=kind,
                source=source,
            ):
                consulted[entry.id] = entry

        # Stage 2: entity identification. Narrow which retrieved facts
        # actually bear on the query.
        # Stage 3: answer seeking, conditioned on the surviving facts.
        # Snippets carry citation tags so credit can flow to the entries
        # the model actually used, instead of spreading evenly over
        # everything retrieval happened to surface. Each snippet carries
        # its age line, and near-duplicate snippets get a mechanical
        # conflict note, so the model sees the time dimension instead of
        # treating all surviving advice as equally current.
        ids = list(consulted)
        memory_block = (
            "\n\n".join(
                f"[{i + 1}] Q: {consulted[eid].question}\n"
                f"A: {consulted[eid].answer}\n{age_annotation(consulted[eid])}"
                for i, eid in enumerate(ids)
            )
            or "(memory returned nothing)"
        )
        conflict_notes = [
            "note: snippets "
            + " ".join(f"[{ids.index(e.id) + 1}]" for e in cluster)
            + f" are {CONFLICT_LABEL}"
            for cluster in conflict_clusters(
                [consulted[eid] for eid in ids],
                self.store.similarity,
                self.conflict_threshold,
            )
        ]
        if conflict_notes:
            memory_block += "\n\n" + "\n".join(conflict_notes)
        final = self.client.complete(
            "Answer the query using ONLY the numbered memory snippets below. "
            "First identify which entities or facts are actually relevant, "
            "then answer. If memory does not support an answer, say so "
            "plainly rather than guessing. End your answer with one line:\n"
            "SOURCES: the bracket numbers you actually used, e.g. SOURCES: [1] [3]\n"
            "If you used none, write SOURCES: none\n\n"
            f"Memory:\n{memory_block}\n\nQuery: {query}"
        )
        text, cited, explicit_none = _split_citations(final, ids)
        # In LLM mode the age lines and conflict notes already traveled
        # to the model inside the snippets, so the model's own prose is
        # the surfaced form: annotated_text is just text.
        if explicit_none:
            # The model declared it used nothing. Honoring that means no
            # provenance at all: no escrow, no credit, counted as silence.
            return ProtocolAnswer(text=text, deciding_entry=None, annotated_text=text)
        if cited:
            # Citation-based attribution: cited entries carry the credit.
            return ProtocolAnswer(
                text=text,
                deciding_entry=cited[0] if len(cited) == 1 else None,
                supporting_entries=cited if len(cited) > 1 else [],
                annotated_text=text,
            )
        # No parseable citations: fall back to even spread over consulted.
        return ProtocolAnswer(
            text=text,
            deciding_entry=None,
            supporting_entries=ids,
            annotated_text=text,
        )


_SOURCES_RE = re.compile(r"^\s*SOURCES?\s*:\s*(.*)$", re.IGNORECASE | re.MULTILINE)


def _split_citations(answer: str, ids: list[str]) -> tuple[str, list[str], bool]:
    """Strip the citation line and resolve bracket numbers to entry ids.

    Returns (text, cited_ids, explicit_none). The contract says the
    SOURCES line ENDS the answer, so the LAST matching line wins:
    earlier prose that happens to start with "Sources:" (or an echoed
    instruction) is left in the text and never counts as citations.
    ``explicit_none`` distinguishes a model declaring "SOURCES: none"
    from output where no citation line could be parsed at all; callers
    must not attach fallback provenance to an explicit none.

    Hybrid-reasoning models (Hermes 4, DeepSeek-R1 style) may emit a
    ``<think>...</think>`` block before the answer; it is discarded
    before parsing so bracket numbers inside the reasoning never count
    as citations.
    """
    answer = _THINK_RE.sub("", answer)
    matches = list(_SOURCES_RE.finditer(answer))
    if not matches:
        return answer.strip(), [], False
    match = matches[-1]
    text = (answer[: match.start()] + answer[match.end() :]).strip()
    payload = match.group(1)
    if re.search(r"\bnone\b", payload, re.IGNORECASE):
        return text, [], True
    cited: list[str] = []
    for number in re.findall(r"\[(\d+)\]", payload):
        index = int(number) - 1
        if 0 <= index < len(ids) and ids[index] not in cited:
            cited.append(ids[index])
    return text, cited, False
