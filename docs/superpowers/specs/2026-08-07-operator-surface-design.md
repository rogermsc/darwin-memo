# Operator surface: `doctor` + `ui` — design spec

- **Date:** 2026-08-07
- **Branch / worktree:** `feat/operator-surface` (`~/darwin-memo-operator`)
- **Status:** approved design, pre-implementation
- **Scope:** Phase 1 of a four-phase programme (Phases 2–4 scoped in §8, each gets its own spec)
- **Target release:** 0.6.0

## 1. Goal

A memory store is currently invisible. Everything an operator can learn arrives
as terminal text or JSON, one entry at a time: `stats`, `top`, `why <id>`,
`audit`. There is no way to see a population over time, no way to see the
graveyard split by cause of death, and — most costly — **no way to diagnose the
three silent failure modes the README itself documents**, because they all
present identically: the whole population dying around tick 20 with every delta
at zero.

Phase 1 ships two things:

1. `darwin-memo doctor` — reads the event log and *names* which failure mode you
   hit, in the production (Ledger) shape where nothing does this today.
2. `darwin-memo ui` — a local, read-only dashboard over the same data.

Non-goals: hosted or multi-user anything, authentication, mutation from the
browser, any new selection knob, any change to selection mechanics.

## 2. The framing this must serve

The Aug-3 benchmark session settled what this library is, and the operator
surface has to tell that story rather than the original one:

- **The security framing is falsified.** `evict_on_negative` — a one-line
  if-statement — ties the ledger on harm (E2 adoption 0.02 both) and revokes
  poison ~5× faster (`poison_kill_cycle` 1–3 vs 8–10; the energy buffer must
  burn down first). The WEF `F1 1.00 vs 0.00` row is a starvation artifact.
- **Removal by disuse is what survived.** A counter prunes only what caused a
  measured loss; it never removes the merely useless. The consequence is
  economic: on the headline corpus (n=5) survival is the only arm ending in
  credit (+2.58M) against `keep_everything` (−3.31M) and the counter (−3.61M).

So the product sentence is **"a memory store that stays lean and cheap, and can
prove it"**, and the UI's job is to make that provable on the operator's own
store. Concretely, that means the **starved vs executed split in the graveyard**
and the **economics panel** are the load-bearing views, not the poison story.

## 3. Architecture

Three layers, built in order, each independently useful:

```
observe.py pure functions  ->  ui.py stdlib HTTP server  ->  ui/ Vite bundle
   (also CLI, also MCP)          (read-only, loopback)       (package data)
```

The functions land first and ship value through the CLI alone. The server is a
JSON projection of them. The frontend is a view. Nothing in the core changes.

**Data source: the existing event log.** No new instrumentation is required for
Phase 1. `Ledger.tick()` already logs `population`, `deaths`, `merges`,
`pending`, `expired` and `total_energy` per tick (`darwin_memo/ledger.py:530`),
and `observe.read_events()` (`observe.py:222`) already parses the rotated log at
`Path(memory).with_suffix(".events.jsonl")`.

## 4. Component 1 — diagnosis and accounting (`darwin_memo/observe.py`)

### 4.1 `timeline(events) -> list[dict]`

One row per `tick` record: `tick`, `population`, `total_energy`, `deaths`,
`merges`, `pending`, plus resource `delta` from settlements bucketed into the
tick they landed in. Chronological, gaps preserved (a missing tick means the
log rotated, and the chart must show a gap rather than interpolate).

### 4.2 `economics(events, store) -> dict`

**Two currencies, reported separately and never summed.** Conflating them is the
single most likely way this panel misleads:

- **Resource ledger** (the real-world case): cumulative settled `delta` — what
  the store's decisions actually did, in bytes or test-passes or dollars —
  alongside `decides.total` / `decides.silent` so coverage is visible. A large
  positive delta over 3 non-silent decisions is not the same claim as the same
  delta over 300.
- **Energy ledger** (the internal mechanism, dimensionless): `credited`,
  `debited`, `net` against upkeep paid.

Both halves reuse `audit_digest()` (`observe.py:274`), which already computes
`settles.delta_total`, `decides.{total,silent}` and `energy.{credited,debited,net}`.

Upkeep paid is estimated as `Σ(population_t × store.upkeep)`. Verified against
`MemoryStore.charge_upkeep` (`store.py:203`): every alive entry pays each tick —
`protect` and `pinned` change *burial* and *flooring*, not whether the charge
happens. The estimate is therefore exact except that a pinned entry at zero has
its charge forgiven by the floor. Report the caveat inline when the store has
pinned entries; Phase 2 logs the exact figure and this falls back automatically.

### 4.3 `doctor(events, store) -> list[Finding]`

`Finding` = `{code, severity, summary, evidence, fix}`. Rules:

| code | severity | fires when | reads as |
|---|---|---|---|
| `silent_majority` | error | `decides.silent / decides.total > 0.8` over ≥10 decides | relevance floor or vocabulary mismatch — the corpus and the tasks do not share words |
| `env_never_paid` | error | ≥5 settles landed and no settle carried a nonzero delta (gross, never net) | action vocabulary: `decision_polarity` never recognised the verbs, so the environment never acted |
| `starvation_cliff` | error | `death` events with `cause == "starved"` and `uses == 0` are ≥ half of all deaths | nothing ever earned; the population simply ran out the clock |
| `settles_dropped` | warn | `settle_dropped > 0` | settlements arriving for unknown or already-buried tickets |
| `tickets_stale` | warn | pending tickets older than `expire_after` | decisions acted on but never reported back |
| `credit_untracked` | warn | `untracked > 0` | settlements written by a pre-`applied` version; per-entry flow is unattributable for those |

Death causes live in per-entry history persisted in `memory.json`
(`ledger.py:685`) rather than in the JSONL event log, so `doctor` takes a
`Ledger`, not just the event stream, to evaluate `starvation_cliff`. The
minimum-volume guards on the first two rules stop a three-decide store from
being declared broken.

Only `error` findings set the exit code; `warn` findings print and exit 0. The
last three have no batch-loop equivalent — they are operational faults that only
exist in the event-driven shape.

**Reuse, do not duplicate.** `SurvivalReport.health_warning()`
(`darwin_memo/survival.py:217`) already implements rules 1–2 (and is itself
untested; the anti-drift test is its first) against in-memory
per-cycle stats. Extract the thresholds and predicates into shared helpers that
both callers use, so the batch loop and the production ledger diagnose
identically and a threshold change lands once. `health_warning()` keeps its
current output format; only its internals move.

### 4.4 CLI

- New: `darwin-memo doctor --memory <path> [--json]`, registered in
  `observe.register_observe_commands()` (`observe.py:433`). Exit code 0 when
  clean, 1 when any finding is severity `error`, so it composes into CI.
- Extended: `darwin-memo stats` gains the economics headline (one line: resource
  delta, energy net, upkeep paid, population).

## 5. Component 2 — server (`darwin_memo/ui.py`)

- Entry point: `darwin-memo ui --memory <path> [--port 8787] [--no-open]`.
- `http.server.ThreadingHTTPServer`, stdlib only, **no new runtime dependency**.
- **Binds 127.0.0.1 only.** A non-loopback `--host` is refused with an
  explanation rather than silently honoured.
- **Read-only.** No mutation endpoints at all, which is what lets the whole
  thing skip auth, CSRF and token handling. Culling, settling and pinning stay
  on the CLI and MCP, where they are already audited and event-logged. This is a
  deliberate scope cut.

| endpoint | returns |
|---|---|
| `GET /` and static paths | the built bundle from package data |
| `GET /api/state` | stats, `timeline()`, `economics()`, `doctor()`, living entries, graveyard, pending tickets |
| `GET /api/entry/<id>` | `entry_life()` (`observe.py:131`); 404 on unknown id |
| `GET /api/events?last=N&since=…` | `filter_events()` (`observe.py:256`) |

Store and log are re-read per request. They are small, and a stale dashboard is
worse than a re-parse. The frontend polls `/api/state` every 2 s — polling until
polling measurably hurts, then SSE.

Static routing resolves against the package data directory and rejects anything
that escapes it.

## 6. Component 3 — frontend (`ui/`)

Vite + React + TypeScript, built to `darwin_memo/data/ui/` and served as package
data. Charts via a lightweight library (uPlot or Recharts). Visual direction:
clean light, muted teal, works without a dark-mode assumption. Build with the
`frontend-design` and `dataviz` skills.

| panel | content | source |
|---|---|---|
| Header | tick, alive / dead / pinned, total energy, pending tickets | `/api/state` |
| Doctor banner | green, or the named finding with its fix | `doctor()` |
| Timeline | population and total energy per tick, death and settlement markers | `timeline()` |
| Living entries | `_top_row()` fields plus **`ticks_to_starvation = energy / upkeep`** — the operator's real question, and a field that does not exist yet | `observe._top_row` (`observe.py:42`) |
| Graveyard | dead entries grouped by cause: executed / starved / merged / forgotten | `_cause_of_death` (`observe.py:116`) |
| Economics | resource delta headline; energy and upkeep accounting beneath it, explicitly labelled as a different currency | `economics()` |
| Event stream | filterable tail | `/api/events` |
| Entry drawer | birth, every settlement, merges, death, provenance | `entry_life()` |

The graveyard's **starved vs executed** split is the thesis rendered as a
picture — starved is the property no counter has — so it gets visual priority
over the event stream and the raw tables.

## 7. Packaging

The `[ui]` extra as originally imagined cannot do what it suggests: a Python
extra cannot conditionally include package data, so the wheel carries the built
bundle either way, and the UI needs no Python runtime dependency — the extra
would install nothing.

**Decision: ship the bundle in the main wheel** (~250KB), keep the Vite
toolchain in `ui/` as a build-time concern documented in `CONTRIBUTING.md`, and
have `darwin-memo ui` work off a plain `pip install darwin-memo`. If wheel
weight ever becomes a real complaint, the alternative is a separate
`darwin-memo-ui` distribution that a `[ui]` extra depends on — that is a
packaging change only, no code moves.

Release must build the bundle before the wheel; `.github/workflows/release.yml`
gains a node build step, and the built output is gitignored (built in CI, not
committed).

## 8. Phases 2–4 (scoped, separate specs)

**Phase 2 — mechanism depth (0.7.0).** Make disuse legible; add no knobs, because
upkeep already *is* the disuse policy. Promote `ticks_to_starvation` to a store
helper so CLI, MCP and UI share one definition. Log exact upkeep charged in the
`tick` event, retiring §4.2's estimate. Resolve the organic-memory PRs: **#33**
(associative graph) merges — additive, opt-in, and it powers a related-entries
view; **#34** (activation + gist↔detail) merges **only** under the invariant
that *activation never influences retention*, with a property test in the same
family as "retrieval never reads energy". The evidence for that invariant is
this repo's own `salience_matched` arm: usage-importance as a retention signal
shields consulted poison (kill rate 0.20 vs random's 0.80) because it cannot
tell "used" from "useful".

**Phase 3 — research depth.** Run the cycle-count sweep the Aug-3 session named
as the obvious next measurement: WEF at 12 / 24 / 48 / 96 cycles, since spawn
1.0 / upkeep 0.05 starves an unconsulted entry at exactly tick 20 and the suite
runs 24 — every published number sits four cycles past the edge. That sweep
decides whether `F1`/`E1` are results or artifacts. Enforce the control rule
mechanically with a test asserting every suite's `ARMS` contains
`evict_on_negative`. Dispose of the open PRs: **#32** merges (it holds the two
non-tautological results); **#35** splits — land the code (`salience_matched`,
`bench/swebench_cl/code_retrieval.py`, `edits.py`, the WEF suite, the
`ollama_model_digest` fix) and rescope the strong-claim prose to an honest
boundary study or drop it. Fix the two pre-existing failures on that branch
first (`test_exactly_three_arms_with_pinned_semantics` is an intentional guard —
decide whether the added arms are correct rather than widening the assertion;
`test_chat_endpoint_read_timeout_is_loud` asserts stale error text).

**Phase 4 — integration depth.** A store that is never consulted never earns, so
integration work is selection pressure, not decoration; go deep on the one
integration with a real conserved signal rather than broad. The CI lesson store
(`darwin_memo/ci.py`, `.github/workflows/memory.yml`) gains a per-PR settlement
comment: which lessons were consulted, what each earned or lost, what died and
why. MCP (`darwin_memo/mcp_server.py`) gains `memory_doctor` and `memory_top` so
an agent can inspect its own store, reusing §4. Claude Code's `render` path is
projection-only with no settlement signal — specify what a *measured* signal
would be before building one, and if there is none, leave it projection-only and
say so, which is the README's own rule.

## 9. Testing

Per the repo's convention, load-bearing behaviour only — no per-function suites.

- `tests/test_observe.py`: `timeline()` shape and gap handling; each `doctor`
  rule firing on a crafted event log **and not firing** on the healthy demo run;
  `economics()` arithmetic including the pinned-entry caveat; one test that
  `health_warning()` and `doctor()` reach the same verdict on the same run
  (the anti-drift test for the shared predicates).
- `tests/test_ui.py`: `/api/state` returns 200 and the documented keys against a
  fixture store; unknown entry id → 404; a path-traversal request on the static
  route → 404; a non-loopback host is refused.
- No browser tests.

## 10. Verification

```bash
python -m darwin_memo demo --cycles 30 --save /tmp/demo.json
darwin-memo doctor --memory /tmp/demo.json          # healthy run must report clean
darwin-memo ui --memory /tmp/demo.json              # every panel populated
curl -s localhost:8787/api/state | python -m json.tool
```

Then three deliberately broken stores — silent-heavy, all-zero-delta, and
never-settled — each of which must be named correctly by `doctor` and must not
trigger the other two findings.

Tooling notes for this repo: no ruff/mypy/pytest are installed locally — use
`uvx ruff …` and `uvx --python 3.13 --with-editable . --with pytest {mypy,pytest}`.
`uvx ruff` is unpinned and newer than the repo's baseline, so scope invocations
to the files touched and revert strays.

## 11. Build sequence (detail in writing-plans)

1. Shared diagnosis predicates extracted from `health_warning()`; `doctor()`,
   `timeline()`, `economics()` on top; tests.
2. `darwin-memo doctor` CLI + `stats` economics line; docs (`docs/api.md`,
   `docs/tuning.md` cross-reference).
3. `darwin_memo/ui.py` server + tests.
4. `ui/` frontend, built into package data; release workflow build step.
5. README and `docs/README.md` entries; CHANGELOG.
