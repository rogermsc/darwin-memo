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

from .llm import LLMClient
from .store import MemoryStore


@dataclass
class ProtocolAnswer:
    text: str
    deciding_entry: str | None = None
    supporting_entries: list[str] = field(default_factory=list)


class QueryProtocol:
    """Grounding, entity identification, answer seeking."""

    def __init__(self, store: MemoryStore, client: LLMClient | None = None) -> None:
        self.store = store
        self.client = client

    def answer(self, query: str, k: int = 3) -> ProtocolAnswer:
        if self.client is None:
            return self._answer_local(query, k)
        return self._answer_llm(query, k)

    # ------------------------------------------------------------------
    # Local mode
    # ------------------------------------------------------------------

    def _answer_local(self, query: str, k: int) -> ProtocolAnswer:
        hits = self.store.retrieve(query, k=k)
        if not hits:
            return ProtocolAnswer(text="")
        deciding, _ = hits[0]
        return ProtocolAnswer(
            text=deciding.answer,
            deciding_entry=deciding.id,
            supporting_entries=[e.id for e, _ in hits[1:]],
        )

    # ------------------------------------------------------------------
    # LLM mode
    # ------------------------------------------------------------------

    def _answer_llm(self, query: str, k: int) -> ProtocolAnswer:
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

        consulted: dict[str, str] = {}  # entry id -> snippet
        for sub in sub_questions or [query]:
            for entry, _ in self.store.retrieve(sub, k=2):
                consulted[entry.id] = f"Q: {entry.question}\nA: {entry.answer}"

        # Stage 2: entity identification. Narrow which retrieved facts
        # actually bear on the query.
        # Stage 3: answer seeking, conditioned on the surviving facts.
        # Snippets carry citation tags so credit can flow to the entries
        # the model actually used, instead of spreading evenly over
        # everything retrieval happened to surface.
        ids = list(consulted)
        memory_block = (
            "\n\n".join(f"[{i + 1}] {consulted[eid]}" for i, eid in enumerate(ids))
            or "(memory returned nothing)"
        )
        final = self.client.complete(
            "Answer the query using ONLY the numbered memory snippets below. "
            "First identify which entities or facts are actually relevant, "
            "then answer. If memory does not support an answer, say so "
            "plainly rather than guessing. End your answer with one line:\n"
            "SOURCES: the bracket numbers you actually used, e.g. SOURCES: [1] [3]\n"
            "If you used none, write SOURCES: none\n\n"
            f"Memory:\n{memory_block}\n\nQuery: {query}"
        )
        text, cited = _split_citations(final, ids)
        if cited:
            # Citation-based attribution: cited entries carry the credit.
            return ProtocolAnswer(
                text=text,
                deciding_entry=cited[0] if len(cited) == 1 else None,
                supporting_entries=cited if len(cited) > 1 else [],
            )
        # No parseable citations: fall back to even spread over consulted.
        return ProtocolAnswer(
            text=text,
            deciding_entry=None,
            supporting_entries=ids,
        )


_SOURCES_RE = re.compile(r"^\s*SOURCES?\s*:\s*(.*)$", re.IGNORECASE | re.MULTILINE)
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _split_citations(answer: str, ids: list[str]) -> tuple[str, list[str]]:
    """Strip the SOURCES line and resolve bracket numbers to entry ids.

    Hybrid-reasoning models (Hermes 4, DeepSeek-R1 style) may emit a
    ``<think>...</think>`` block before the answer; it is discarded
    before parsing so bracket numbers inside the reasoning never count
    as citations.
    """
    answer = _THINK_RE.sub("", answer)
    match = _SOURCES_RE.search(answer)
    if not match:
        return answer.strip(), []
    text = (answer[: match.start()] + answer[match.end() :]).strip()
    cited: list[str] = []
    for number in re.findall(r"\[(\d+)\]", match.group(1)):
        index = int(number) - 1
        if 0 <= index < len(ids) and ids[index] not in cited:
            cited.append(ids[index])
    return text, cited
