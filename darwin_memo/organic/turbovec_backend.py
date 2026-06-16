"""Optional turbovec ANN backend for the associative graph (the [organic] extra).

turbovec quantizes vectors for memory-efficient ANN at scale. It is import-
guarded: absence falls back to BruteForceBackend. turbovec uses integer ids, so
this maps memory string ids to ints; removals are tombstoned (turbovec has no
delete) and filtered at search time.
"""

from __future__ import annotations


class TurbovecBackend:
    def __init__(self, dim: int, bit_width: int = 4) -> None:
        import numpy as np
        from turbovec import IdMapIndex

        self._np = np
        self._index = IdMapIndex(dim=dim, bit_width=bit_width)
        self._dim = dim
        self._to_int: dict[str, int] = {}
        self._to_str: dict[int, str] = {}
        self._dead: set[str] = set()
        self._next = 1

    def add(self, entry_id: str, vector: list[float]) -> None:
        self._dead.discard(entry_id)
        if entry_id not in self._to_int:
            iid = self._next
            self._next += 1
            self._to_int[entry_id] = iid
            self._to_str[iid] = entry_id
        vec = self._np.asarray([vector], dtype=self._np.float32)
        ids = self._np.array([self._to_int[entry_id]], dtype=self._np.uint64)
        self._index.add_with_ids(vec, ids)

    def remove(self, entry_id: str) -> None:
        self._dead.add(entry_id)

    def search(
        self, vector: list[float], k: int, exclude: str | None = None
    ) -> list[tuple[str, float]]:
        # turbovec wants a 2-D queries batch; we query one vector and take row 0.
        query = self._np.asarray([vector], dtype=self._np.float32)
        # over-fetch to absorb tombstoned/excluded ids
        scores, ids = self._index.search(query, k + len(self._dead) + 1)
        scores0 = self._np.asarray(scores)[0]
        ids0 = self._np.asarray(ids)[0]
        out: list[tuple[str, float]] = []
        for score, iid in zip(scores0, ids0, strict=False):
            sid = self._to_str.get(int(iid))
            if sid is None or sid == exclude or sid in self._dead:
                continue
            out.append((sid, float(score)))
            if len(out) == k:
                break
        return out
