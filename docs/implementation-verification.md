# Local implementation record

Observed on 2026-09-21 in branch `release/measured-memory`, based on
`b90b7be`. No target-repository commit, push, publication, participant contact,
or paid model request was made. Research spending is $0.

## Product behavior

| Real path | Observed output |
|---|---|
| Unrelated lexical write to an embedding-backed store | Original checkout lost cached vectors; the implementation preserves them. |
| Two Python writers loaded from one snapshot | Original checkout overwrote the intervening change; the implementation rejects the stale writer. |
| Concurrent CLI mutation while another process holds the lock | Exit `1`: `is busy; retry the entire operation`; population remains two. |
| MCP over stdio, external CLI write, and MCP restart | MCP sees both entries; the pending ticket survives restart. |
| MCP CI profile | `memory_settle` is unavailable to the connected agent. |
| Repository initialization | Creates five repository-local files; a second invocation refuses every existing target. |
| Fixed evaluation before and after the example repair | Base pytest exit `1`, head exit `0`, settlement delta `1.0`; report contains repository, task, commits, run, and report hashes. |
| Green-to-green comparison | Both evaluations exit `0`; delta `0.0`, recorded without improvement credit. |
| Missing import in the task commit | Evaluation exits `2`; command abstains with exit `3`; store bytes are unchanged and the ticket remains pending. |
| Duplicate ticket and mismatched task | Rejected before settlement. |
| Reused run after 120 pin/unpin events | The first implementation lost the guard with capped history. Durable run records reject the reuse after those events and a reload. |
| Expired pending ticket | Zero pending tickets, zero uses, and an `expired` event; no observed outcome is invented. |
| Dashboard pin and refused deletion | Detail changes from Pin to Unpin without a tick. Escrowed deletion displays `forget: escrowed`. |
| Missing historical evidence | Unknown source/comparison/outcome remains unknown; it is not converted into verified evidence or zero. |

The example runs pytest as the product's fixed evaluation. The project's test
suite was not run, and no verification test suite was added.

## Packaging and interface

Built the TypeScript/Vite dashboard and inspected lesson details, pending
outcomes, source/commit/run evidence, and advanced retention controls in Chrome.
The build retains its existing bundle-size advisory. Built a wheel and installed
it without dependencies in an isolated environment. Verified imports from that
environment's `site-packages`, the durable run guard, the bundled dashboard, and
all four profile assets; `init` creates the fifth file, the empty store.
The core dependency list remains empty.

The generated GitHub workflow was not dispatched. Its evaluator ran locally;
local reports correctly identify the operator path. A hosted run requires the
reviewed revision to be published and configured in the target repository.
The profile supports root-importable Python evaluations. Projects needing pytest
plugins or different import/dependency arrangements need a reviewed adapter.

## Research artifacts

`python tools/reconstruct_paper.py` reconstructs all 35 central attack-table cells
from 1,050 committed observations and all 14 counter-sweep cells from 420
observations. Every cell requires each seed from 0 through 29 exactly once.
Changing one source observation in a temporary copy produced a printed-cell
mismatch, confirming the reconstruction reads the source data. Historical
benchmark files were not edited.

`python -m bench.swebench_cl.compare bench/results/swebench_cl_long` reconstructs
two repository sequences, three repeated runs, and 300 tasks per arm. No memory
resolves 108 tasks; darwin-memo resolves 105. The paired hierarchical bootstrap
interval for the success difference is approximately `[-0.0333, 0.0167]`.
This is exploratory, with only two repositories, and is not a preregistered
noninferiority result. Complete costs and provider tokens are unknown. No cost
benefit or preserved-success claim follows from this reconstruction.

A failed local endpoint request records failure, latency, and unknown provider
usage. The forgiveness counter retains a lesson through negative, positive,
negative, and zero outcomes, then removes it on the next negative at threshold
two. These observations exercise instrumentation and retention logic without
buying model responses.

The paper builds as a local review preprint. Selected changed pages and the
central table were visually inspected; this is not a complete submission-layout
review. The toolchain emits an `algorithm.sty` encoding warning and underfull
bibliography warnings. No venue template or submission compliance is claimed.

## Remaining release gates

External activation and four-week retention pilots, two consented case studies,
the pilot-based demonstration video, authorized calibration and held-out runs,
a frozen study manifest, a complete claim/citation audit, independent
reproduction, and a selected venue's actual template remain pending. See the
[release record](release-readiness.md), [research protocol](research/measured-memory-protocol.md),
and [paper claim audit](../paper/claim-audit.md).
