# Claim and artifact audit

Review date: 2026-09-21. This record distinguishes completed local reconstruction
from review work that still needs an independent reader.

| Claim | Producer → observations → aggregation → printed result | Status |
|---|---|---|
| Central attack comparison | `StorageEnv.verify` → `bench/results/adversary.json` → per-arm, budget, and seed means → `tab:adversary` | All 35 printed cells reconstruct locally from 1,050 rows. Each cell requires seeds 0–29 exactly once. Restoration penalty is modeled, not physical cost. |
| Truth versus delivered feedback | Storage adversary/runner → `cum_delta` and `reported_cum_delta`; coding runner → `metrics.delta` and `adversary.reported_delta` | Fields remain separate; archive original truth before any future corruption run. |
| Tuned counter competes | `bench/results/counter_sweep.json` → `tab:countersweep` | All 14 printed threshold cells reconstruct from 30 seeds each. Historical counterexample retained in the main argument. Prospective coding threshold still needs development-set tuning. |
| Lower total cost with preserved success | Prospective coding-agent comparison | Not established. Provider billing and full execution costs are missing from historical runs; no five-point noninferiority result is available. |
| Physical storage restoration cost | `StorageEnv.verify` recreates bytes and returns `-3 * size` | Invalid physical-measurement interpretation removed. Historical values and configuration are unchanged. |
| Causal lesson credit | `assign_credit` uses consulted-entry provenance | Association only; neither settlement nor passing tests establish causation. |
| Whole-paper reproduction | All other tables, figures, and headline statements | Existing report tools remain available. Full independent cell-by-cell and producer audit is still required before submission. |

## Primary-source checks

- [Safety in Self-Evolving LLM Agent Systems, v1, section 4.3](https://arxiv.org/html/2606.23075v1#S4.SS3) explicitly discusses performance-feedback corruption changing retained memory. It supports the threat's prior description, not a novelty guarantee.
- [Long-term-memory security survey, v1](https://arxiv.org/html/2604.16548v1) has a different title from v2; the bibliography's v1 title is corrected. Its three availability gaps concern flooding, retrieval latency, and reflection loops. The paper no longer presents that statement as evidence of priority for feedback-corruption experiments.
- [MPBench, v2, table 4](https://arxiv.org/html/2606.04329v2) reports detector drops of 18.12–41.94 percentage points. The paper's rounded 18–42-point statement agrees.
- [MemSecBench](https://arxiv.org/abs/2607.27080) describes the Write–Execute–Forget lifecycle. Our reimplementation is not a numerical comparison against that benchmark.
- [Forget to Improve](https://arxiv.org/abs/2606.25115) describes net-value-per-byte retention under a resource budget. This is a relevant comparison; it does not establish that darwin-memo uniquely occupies an unclaimed category.

Remaining citations need a full, version-specific review before submission. A
source existing at the cited URL does not by itself validate every attributed
claim. No public priority claim or publication is authorized by this audit.

## Reproduction boundary

`tools/reconstruct_paper.py` re-aggregates committed observations and checks the
printed central table. This is a substantive offline reconstruction, not a fresh
simulation run or independent reproduction. Deliberately altering a source
observation must produce a printed-cell mismatch; deleting a seed must produce
a missing-seed error. Hashes protect artifact bytes, not the validity of their
producer. An archived development snapshot is not a reviewed submission.
