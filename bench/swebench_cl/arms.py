"""The pilot's three arms, defined in code so a run cannot improvise.

Every arm answers the same tasks through the same endpoint and the
same executor. They differ only in what memory the model sees and how
the store is settled afterwards:

- ``memory_on``: lessons are retrieved by relevance, the per-task test
  outcome settles credit along the retrieval provenance, and a lesson
  is minted from every task's trajectory. The full darwin-memo loop.
- ``memory_off``: no store at all. The floor every curve is read
  against.
- ``random_matched``: the sharpest control, mirroring the storage
  bench's arm of the same name. Lessons are minted and settled with
  the same mechanics as memory_on, but the lessons INJECTED (and so
  the lessons that outcome credit lands on) are chosen uniformly at
  random under the same token budget relevance retrieval would have
  spent on that task. Same memory quantity, same credit magnitude, no
  outcome-directed selection. If memory_on does not beat this arm,
  the learning curve is a token-budget effect, not a memory effect.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArmSpec:
    """How one arm treats the lesson store."""

    name: str
    inject: str  # "retrieved" | "none" | "random_matched"
    mint: bool  # mint a lesson from each task's trajectory
    settle: bool  # settle injected lessons with the eval outcome


ARMS: dict[str, ArmSpec] = {
    "memory_on": ArmSpec(name="memory_on", inject="retrieved", mint=True, settle=True),
    "memory_off": ArmSpec(name="memory_off", inject="none", mint=False, settle=False),
    "random_matched": ArmSpec(
        name="random_matched", inject="random_matched", mint=True, settle=True
    ),
}


def token_count(text: str) -> int:
    """Whitespace tokens: the budget currency for random_matched.

    Deliberately model-agnostic. The budget exists to match memory
    QUANTITY between arms, not to bill an exact tokenizer, and a
    whitespace count is reproducible across every endpoint config.
    """
    return len(text.split())
