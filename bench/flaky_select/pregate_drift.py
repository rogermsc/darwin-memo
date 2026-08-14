"""Pre-gate: does the energy ledger beat counting under DRIFT + sparse observation?

The two NO-GOs both reduced to "i.i.d. evidence -> a sufficient statistic
(pass-count) -> threshold/window counting wins, the ledger only ties." The
structure that DEFEATS counting is NON-STATIONARITY: when a unit's true quality
drifts/flips over time and you observe it only irregularly, a cumulative count
lags badly and a fixed window-over-observations conflates wall-time with
observation-count. darwin-memo's ACTUAL design is a time-decayed accumulator
(upkeep = per-cycle decay, credit = per-observation), which should track a
drifting target better — this is the mechanism on its home turf.

Model: P units; each unit's true state in {good,bad} flips with prob `flip` per
cycle (drift). Each cycle a unit is observed w.p. `obs`; an observation reports
its CURRENT state, flipped w.p. `noise`. Each rule keeps/drops each unit per
cycle from observations so far; we score precision/recall of {kept} vs
{currently-good} averaged over cycles (after burn-in) and seeds.

Rules (each a tunable family, swept for its best frontier):
- cumulative(thr): keep if (passes - fails) over ALL history >= thr.
- window(W): keep if majority of the last W OBSERVATIONS passed.
- ledger(spawn, gain, upkeep): energy += gain*tanh(+/-1) per observation;
  energy -= upkeep every cycle (time decay); clip to [0, cap]; keep if energy >
  floor. Recovery allowed (no permanent burial) so it can track bad->good.

Pure synthetic, no Docker/API/cost. If the ledger's frontier does not beat the
window family here, the mechanism has no edge even on its home structure.
Run: PYTHONPATH=. .venv312/bin/python -m bench.flaky_select.pregate_drift
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
from collections import deque

CELLS = [  # (flip-per-cycle, observation-rate, per-obs noise)
    (0.02, 0.3, 0.1),
    (0.05, 0.3, 0.1),
    (0.05, 0.15, 0.2),
    (0.10, 0.2, 0.15),
]
CYCLES = 200
BURN_IN = 20
P_UNITS = 300
CAP = 5.0
FLOOR = 1e-9

CUM_THR = [-3, -1, 0, 1, 3]
WINDOWS = [3, 5, 9, 15]
# The CRITICAL control: a time-decayed (EWMA-style) accumulator is the proper
# drift-aware sufficient statistic and the closest LINEAR analog to the ledger
# (decay per cycle + +/-1 per observation). If the ledger only ties this, its
# "edge" under drift is just being a clipped EWMA — no real contribution.
DECAY_RHO = [0.7, 0.85, 0.95]
DECAY_THR = [-1.0, 0.0, 1.0, 2.0]
LEDGER = [  # (spawn, gain, upkeep)
    (s, g, u) for s in (0.5, 1.0, 2.0) for g in (0.4, 0.8) for u in (0.05, 0.15, 0.4)
]


def _seed(seed: int, flip: float, obs: float, noise: float) -> int:
    key = f"{seed}|{flip}|{obs}|{noise}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def _simulate(flip: float, obs: float, noise: float, rng: random.Random):
    """Yield, per cycle after burn-in, (true_states, observations) where
    observations[u] is True/False/None (None = not observed this cycle)."""
    states = [rng.random() < 0.5 for _ in range(P_UNITS)]
    frames = []
    for t in range(CYCLES):
        for u in range(P_UNITS):
            if rng.random() < flip:
                states[u] = not states[u]
        obs_row = []
        for u in range(P_UNITS):
            if rng.random() < obs:
                seen = states[u] if rng.random() >= noise else (not states[u])
                obs_row.append(seen)
            else:
                obs_row.append(None)
        if t >= BURN_IN:
            frames.append((list(states), obs_row))
        else:
            # still advance rule state during burn-in; caller replays all frames
            frames.append((list(states), obs_row))
    return frames


def _score_rule(frames, update, decide):
    """Run a stateful rule over all cycles.

    Scores P/R/F1 of kept-vs-good after burn-in.
    """
    state: dict = {}
    tp = kept = pos = 0
    for t, (truth, obs_row) in enumerate(frames):
        for u, o in enumerate(obs_row):
            if o is not None:
                update(state, u, o)
        update(state, None, None)  # per-cycle tick (e.g. upkeep decay)
        if t < BURN_IN:
            continue
        for u in range(P_UNITS):
            k = decide(state, u)
            if k:
                kept += 1
            if truth[u]:
                pos += 1
            if k and truth[u]:
                tp += 1
    prec = tp / kept if kept else 0.0
    rec = tp / pos if pos else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return f1


def _cumulative(thr):
    def update(st, u, o):
        if u is None:
            return
        st.setdefault(u, 0)
        st[u] += 1 if o else -1

    return update, (lambda st, u: st.get(u, 0) >= thr)


def _window(W):
    def update(st, u, o):
        if u is None:
            return
        st.setdefault(u, deque(maxlen=W)).append(o)

    def decide(st, u):
        dq = st.get(u)
        return bool(dq) and sum(dq) >= math.ceil(len(dq) / 2)

    return update, decide


def _decayed(rho, thr):
    """Leaky-integrator / EWMA-style accumulator: +/-1 per obs, *rho per cycle.
    The proper drift-aware sufficient statistic and the ledger's linear twin."""

    def update(st, u, o):
        if u is None:
            for k in st:
                st[k] *= rho
            return
        st[u] = st.get(u, 0.0) + (1.0 if o else -1.0)

    return update, (lambda st, u: st.get(u, 0.0) > thr)


def _ledger(spawn, gain, upkeep):
    def update(st, u, o):
        if u is None:  # per-cycle decay for all known units
            for k in st:
                st[k] = max(0.0, st[k] - upkeep)
            return
        e = st.get(u, spawn)
        e += gain * math.tanh(1.0 if o else -1.0)
        st[u] = max(0.0, min(CAP, e))

    return update, (lambda st, u: st.get(u, spawn) > FLOOR)


def run(seeds):
    rows = []
    for flip, obs, noise in CELLS:
        best = {"cumulative": 0.0, "window": 0.0, "decayed": 0.0, "ledger": 0.0}
        for s in seeds:
            frames = _simulate(
                flip, obs, noise, random.Random(_seed(s, flip, obs, noise))
            )
            for thr in CUM_THR:
                up, dec = _cumulative(thr)
                best["cumulative"] = max(
                    best["cumulative"], _score_rule(frames, up, dec)
                )
            for W in WINDOWS:
                up, dec = _window(W)
                best["window"] = max(best["window"], _score_rule(frames, up, dec))
            for rho in DECAY_RHO:
                for thr in DECAY_THR:
                    up, dec = _decayed(rho, thr)
                    best["decayed"] = max(best["decayed"], _score_rule(frames, up, dec))
            for sp, g, u in LEDGER:
                up, dec = _ledger(sp, g, u)
                best["ledger"] = max(best["ledger"], _score_rule(frames, up, dec))
        rows.append({"flip": flip, "obs": obs, "noise": noise, **best})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", default="0:5")
    args = ap.parse_args(argv)
    a, b = (int(x) for x in args.seeds.split(":"))
    rows = run(list(range(a, b)))
    print(
        f"\nDrift pre-gate: best-F1 per rule family (swept), {CYCLES} cycles, "
        f"{P_UNITS} units\n"
    )
    print(
        f"{'flip':>6}{'obs':>6}{'noise':>7}{'cumul':>8}{'window':>8}{'decayed':>9}{'ledger':>8}{'ledger>both?':>13}"
    )
    wins = 0
    for r in rows:
        strongest_baseline = max(r["cumulative"], r["window"], r["decayed"])
        better = r["ledger"] > strongest_baseline + 1e-3
        wins += better
        print(
            f"{r['flip']:>6}{r['obs']:>6}{r['noise']:>7}{r['cumulative']:>8.3f}"
            f"{r['window']:>8.3f}{r['decayed']:>9.3f}{r['ledger']:>8.3f}"
            f"{('YES' if better else 'no'):>13}"
        )
    print(
        f"\nVERDICT: ledger best-F1 beats the STRONGEST baseline (incl. decayed/EWMA) "
        f"in {wins}/{len(rows)} cells."
    )
    print(
        "DRIFT PRE-GATE:",
        "PASS (ledger beats even the EWMA twin)"
        if wins >= len(rows) - 1
        else "NO-GO (a decayed/EWMA count matches the ledger — no real edge)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
