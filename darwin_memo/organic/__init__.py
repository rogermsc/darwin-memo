"""Organic memory: an adaptive, brain-like layer over darwin-memo (opt-in).

EXPERIMENTAL, and reachable only from Python. Nothing in the package
imports this subpackage: it is absent from ``darwin_memo.__all__`` and
from the CLI, the MCP server and the dashboard, by decision rather than
by oversight. ``import darwin_memo.organic`` is the whole surface.

Two things to know before building on it, both measured rather than
asserted:

- **Its state does not persist.** ``ActivationState``,
  ``HebbianWeights`` and ``EarnedImportance`` are in-memory dicts with
  no ``dump_state``/``load_state``, and ``MemoryStore.save`` does not
  carry them. A layer described as learning associations forgets every
  one of them when the process exits. docs/organic.md says activation is
  ephemeral; the learned weights are too.
- **Usage is a weaker retention signal than survival.**
  ``bench/results/salience.json`` measures salience-matched eviction
  killing poison at 0.20 against random-matched at 0.80 and survival at
  1.00, because usage cannot tell "used" from "useful" and consulted
  poison gets shielded. ``MemoryStore.charge_upkeep`` clamps any scale
  to ``MIN_UPKEEP_SCALE`` so potentiation stretches the starvation
  horizon roughly fourfold and never removes it. See docs/organic.md.
"""

from __future__ import annotations

from .activation import ActivationState, detail, surface
from .associative import (
    AssociativeGraph,
    BruteForceBackend,
    build_graph,
    store_related,
)
from .dynamics import HebbianWeights, OrganicMemory
from .importance import EarnedImportance

__all__ = [
    "ActivationState",
    "AssociativeGraph",
    "BruteForceBackend",
    "EarnedImportance",
    "HebbianWeights",
    "OrganicMemory",
    "build_graph",
    "detail",
    "store_related",
    "surface",
]
