"""Organic memory: an adaptive, brain-like layer over darwin-memo (opt-in)."""

from __future__ import annotations

from .activation import ActivationState, detail, surface
from .associative import (
    AssociativeGraph,
    BruteForceBackend,
    build_graph,
    store_related,
)

__all__ = [
    "ActivationState",
    "AssociativeGraph",
    "BruteForceBackend",
    "build_graph",
    "detail",
    "store_related",
    "surface",
]
