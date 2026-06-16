"""Organic memory: an adaptive, brain-like layer over darwin-memo (opt-in)."""

from __future__ import annotations

from .associative import (
    AssociativeGraph,
    BruteForceBackend,
    build_graph,
    store_related,
)

__all__ = ["AssociativeGraph", "BruteForceBackend", "build_graph", "store_related"]
