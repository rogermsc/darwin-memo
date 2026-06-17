"""Organic memory: an adaptive, brain-like layer over darwin-memo (opt-in)."""

from __future__ import annotations

from .activation import ActivationState, detail, surface
from .associative import (
    AssociativeGraph,
    BruteForceBackend,
    build_graph,
    store_related,
)
from .dynamics import HebbianWeights, OrganicMemory

__all__ = [
    "ActivationState",
    "AssociativeGraph",
    "BruteForceBackend",
    "HebbianWeights",
    "OrganicMemory",
    "build_graph",
    "detail",
    "store_related",
    "surface",
]
