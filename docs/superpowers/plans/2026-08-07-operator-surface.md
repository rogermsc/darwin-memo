# Operator Surface (`doctor` + `ui`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a darwin-memo store visible and diagnosable — `darwin-memo doctor` names which silent failure mode a store hit, and `darwin-memo ui` serves a local read-only dashboard over the same data.

**Architecture:** Three layers built in order, each independently useful. (1) Pure functions in `darwin_memo/diagnose.py` and `darwin_memo/observe.py` that read the existing memory file and JSONL event log — no new instrumentation. (2) `darwin_memo/ui.py`, a stdlib `ThreadingHTTPServer` bound to loopback that projects those functions as JSON and serves a built bundle. (3) `ui/`, a Vite/React/TypeScript frontend built into `darwin_memo/data/ui/` and shipped as package data.

**Tech Stack:** Python 3.10+ stdlib only for the runtime (no new dependency). Frontend: Vite + React + TypeScript + Recharts, built at release time.

## Global Constraints

- **Python floor is 3.10** (`requires-python = ">=3.10"`). No `match`, no PEP 695 generics, no `itertools.batched`.
- **Zero new Python runtime dependencies.** `dependencies = []` in `pyproject.toml` stays empty and no `[project.optional-dependencies]` entry is added. The frontend's npm packages (React, Recharts, Vite) are build-time only and bundle into static assets — they are not a constraint violation.
- **mypy strict** over `darwin_memo` and `tests` (`[tool.mypy] strict = true`). Every new function needs complete annotations; `tests` may use untyped defs.
- **ruff** line-length 88, `select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]`.
- **Coverage gate `fail_under = 80`** over `source = ["darwin_memo"]`. New modules must be tested, not exempted.
- **Read-only.** No endpoint, function, or CLI added here may write to the store, the event log, or anything else. `_load_ledger` (`observe.py:424`) is the read-only load pattern to follow.
- **Loopback only.** The server binds `127.0.0.1`; a non-loopback host is refused.
- **CLI convention:** observe-family subcommands take `memory` as a **positional** argument plus `--json`, and register via `set_defaults(fn=...)`. Follow `register_observe_commands` (`observe.py:433`).
- **Tooling:** nothing is installed locally for this repo. Use `uvx ruff check <paths>`, `uvx ruff format <paths>`, and `uvx --python 3.13 --with-editable . --with pytest pytest <args>` / `... mypy`. `uvx ruff` is unpinned and newer than the repo baseline — **scope every ruff invocation to the files you touched and revert strays**.
- Work happens in the `feat/operator-surface` worktree at `~/darwin-memo-operator`.

---

## Corrections to the spec (verified against source — apply these, not the spec's wording)

Three things in `docs/superpowers/specs/2026-08-07-operator-surface-design.md` are wrong. Task 1 fixes the spec text; the plan below is already correct.

1. **Death causes are NOT in the event log.** `Ledger._note()` (`ledger.py:685`) appends to `self._history`, which is persisted inside `memory.json` — only `Ledger._log()` (`ledger.py:693`) writes JSONL. The `tick` record carries `dead_entries` (ids) but no causes. Therefore `doctor()` takes a **`Ledger`**, not a bare store: it needs `ledger.history()` (via `entry_life`) and `ledger.pending()`.
2. **`env_never_paid` must count GROSS movement, not net.** The spec said `delta_total == 0`. `survival.py:231-233` explicitly warns against exactly that: "a cycle whose payouts exactly cancel still paid out, and net-zero float equality must not trigger a 'never paid' diagnosis." Count settle events whose own `delta != 0`.
3. **`health_warning()` implements 2 rules, not 3**, and `starvation_cliff` is new rather than extracted. It also has **zero tests** — grep confirms no test references it — so the anti-drift test in Task 1 is its first, and the small wording change is safe.

---

## File Structure

| File | Responsibility |
|---|---|
| `darwin_memo/diagnose.py` (new, ~90 lines) | `Finding` dataclass, thresholds, and the shared degeneracy predicates. Leaf module — imports nothing from the package, so both `survival` and `observe` can use it without a cycle. |
| `darwin_memo/survival.py` (modify) | `health_warning()` delegates to `diagnose.selection_findings`. |
| `darwin_memo/observe.py` (modify, +~130 lines) | `timeline()`, `economics()`, `doctor()`, `cmd_doctor`; `_top_row` → public `top_row`. |
| `darwin_memo/cli.py` (modify) | `stats` gains an economics line when an event log exists. |
| `darwin_memo/ui.py` (new, ~170 lines) | `state()` aggregator, the HTTP handler, `serve()`, `cmd_ui`. |
| `darwin_memo/data/ui/` (build output) | Bundle, gitignored, produced by `ui/`. |
| `ui/` (new) | Vite/React/TS frontend. One file per panel under `ui/src/panels/`. |
| `tests/test_observe.py` (modify) | Diagnosis, timeline, economics, anti-drift. |
| `tests/test_ui.py` (new) | Server routing, JSON shape, 404s, loopback refusal. |

---

## Task 1: Shared diagnosis predicates

**Files:**
- Create: `darwin_memo/diagnose.py`
- Modify: `darwin_memo/survival.py:217-250`
- Modify: `docs/superpowers/specs/2026-08-07-operator-surface-design.md` (§4.3 corrections)
- Test: `tests/test_observe.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Finding(code: str, severity: str, summary: str, evidence: str, fix: str)` with `.as_dict() -> dict[str, str]`; `selection_findings(*, decides: int, silent: int, nonzero_outcomes: int, settles: int) -> list[Finding]`; constants `SILENCE_LIMIT = 0.8`, `MIN_DECIDES = 10`, `MIN_SETTLES = 5`, `STALE_TICKET_TICKS = 50`, `MIN_DEATHS = 3`, `STARVED_SHARE = 0.5`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_observe.py`:

```python
from darwin_memo.diagnose import Finding, selection_findings


def test_silent_majority_fires_and_suppresses_the_never_paid_rule():
    findings = selection_findings(
        decides=100, silent=95, nonzero_outcomes=0, settles=100
    )
    assert [f.code for f in findings] == ["silent_majority"], (
        "silence is the actionable diagnosis; a silent store obviously "
        "never earned, and reporting both buries the useful one"
    )
    assert findings[0].severity == "error"


def test_never_paid_reads_gross_movement_not_net():
    # Payouts that exactly cancel DID pay out: the environment works.
    findings = selection_findings(
        decides=100, silent=0, nonzero_outcomes=6, settles=100
    )
    assert findings == []
    findings = selection_findings(
        decides=100, silent=0, nonzero_outcomes=0, settles=100
    )
    assert [f.code for f in findings] == ["env_never_paid"]


def test_small_runs_are_not_declared_broken():
    assert selection_findings(
        decides=3, silent=3, nonzero_outcomes=0, settles=3
    ) == []


def test_finding_serializes_to_flat_strings():
    finding = Finding("c", "warn", "s", "e", "f")
    assert finding.as_dict() == {
        "code": "c", "severity": "warn", "summary": "s",
        "evidence": "e", "fix": "f",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py -k "silent_majority or never_paid or small_runs or serializes" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'darwin_memo.diagnose'`

- [ ] **Step 3: Write the module**

Create `darwin_memo/diagnose.py`:

```python
"""Degeneracy rules shared by the batch loop and the event-driven ledger.

Both shapes hit the same failure modes and both used to diagnose them
separately (or, in the Ledger's case, not at all). One threshold set
lives here so a fix lands once and the two surfaces cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass

# A store that answers almost nothing cannot earn, whatever else is true.
SILENCE_LIMIT = 0.8
# Volume floors: three decisions are not evidence of a broken environment.
MIN_DECIDES = 10
MIN_SETTLES = 5
# Mirrors the ``expire_after`` default on Ledger.tick and the tick CLI.
STALE_TICKET_TICKS = 50
# Starvation reads as a population property, not a one-entry accident.
MIN_DEATHS = 3
STARVED_SHARE = 0.5


@dataclass(frozen=True)
class Finding:
    """One diagnosis: what fired, how bad, the evidence, and the fix.

    ``severity`` is "error" (the store is not working) or "warn" (an
    operational fault worth knowing about). Only errors set an exit code.
    """

    code: str
    severity: str
    summary: str
    evidence: str
    fix: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "fix": self.fix,
        }


def selection_findings(
    *, decides: int, silent: int, nonzero_outcomes: int, settles: int
) -> list[Finding]:
    """The two degeneracies a new environment hits, in priority order.

    Mutually exclusive by design: memory that never speaks obviously
    never earned, so reporting both diagnoses buries the actionable one.

    ``nonzero_outcomes`` is GROSS movement and must never be a net sum.
    A window whose payouts exactly cancel did pay out, and float
    equality against a net total would call a working environment dead.
    """
    if decides >= MIN_DECIDES and silent / decides > SILENCE_LIMIT:
        return [
            Finding(
                code="silent_majority",
                severity="error",
                summary=f"memory was silent on {silent}/{decides} decisions",
                evidence=f"silence rate {silent / decides:.0%}",
                fix=(
                    "task phrasing likely does not lexically overlap the "
                    "corpus (see min_coverage), so nothing can earn energy"
                ),
            )
        ]
    if settles >= MIN_SETTLES and nonzero_outcomes == 0:
        return [
            Finding(
                code="env_never_paid",
                severity="error",
                summary=f"none of {settles} settlements carried an outcome",
                evidence=f"{settles} settlements, every delta zero",
                fix=(
                    "the environment never paid out; check that verify() "
                    "reads your answers (is decision_polarity's vocabulary "
                    "right for your action verbs?)"
                ),
            )
        ]
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py -k "silent_majority or never_paid or small_runs or serializes" -v`
Expected: 4 passed

- [ ] **Step 5: Write the anti-drift test**

Add to `tests/test_observe.py`:

```python
def test_health_warning_speaks_through_the_shared_rules():
    """The batch report must not drift from the shared predicates."""
    from darwin_memo.survival import SurvivalReport
    from darwin_memo.types import CycleStats

    quiet = SurvivalReport(
        stats=[
            CycleStats(
                cycle=c, population=5, births=0, deaths=0, merges=0,
                total_energy=5.0, resource_delta=0.0, tasks=10, silent=10,
                nonzero_outcomes=0,
            )
            for c in range(3)
        ]
    )
    warning = quiet.health_warning()
    assert "WARNING" in warning
    assert "silent on 30/30" in warning
    assert "min_coverage" in warning

    healthy = SurvivalReport(
        stats=[
            CycleStats(
                cycle=c, population=5, births=0, deaths=0, merges=0,
                total_energy=5.0, resource_delta=12.0, tasks=10, silent=1,
                nonzero_outcomes=9,
            )
            for c in range(3)
        ]
    )
    assert healthy.health_warning() == ""
```

Before running, open `darwin_memo/survival.py` and read the real `CycleStats` field list; if any field name or default differs from the call above, fix the test to match the dataclass rather than changing the dataclass.

- [ ] **Step 6: Run it and watch it fail on wording**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py -k health_warning -v`
Expected: FAIL — the current message says "memory was silent on 30/30 tasks", the shared rule says "decisions".

- [ ] **Step 7: Delegate `health_warning` to the shared rules**

In `darwin_memo/survival.py`, add to the imports:

```python
from .diagnose import selection_findings
```

Replace the body of `health_warning` (`survival.py:217-250`), keeping the docstring's first line and updating the rest:

```python
    def health_warning(self) -> str:
        """A plain-language diagnosis when the run looks degenerate.

        The failure modes a new environment hits are silent: memory
        never answers (phrasing mismatch or action vocabulary not read),
        or answers never earn (verify never pays out). Both end the same
        way, the whole population starving at spawn_energy / upkeep
        cycles, so the report says so instead of letting the table look
        like success. The rules live in :mod:`darwin_memo.diagnose` so
        the Ledger's ``doctor`` diagnoses identically.
        """
        total_tasks = sum(s.tasks for s in self.stats)
        if not total_tasks:
            return ""
        findings = selection_findings(
            decides=total_tasks,
            silent=sum(s.silent for s in self.stats),
            # Gross movement, not net: see selection_findings.
            nonzero_outcomes=sum(s.nonzero_outcomes for s in self.stats),
            settles=total_tasks,
        )
        if not findings:
            return ""
        return "\n\nWARNING: " + "\nWARNING: ".join(
            f"{f.summary}: {f.fix}" for f in findings
        )
```

- [ ] **Step 8: Run the full observe and survival suites**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py tests/test_survival.py -v`
Expected: all pass

- [ ] **Step 9: Fix the three spec errors**

In `docs/superpowers/specs/2026-08-07-operator-surface-design.md` §4.3, replace the `env_never_paid` row's condition with `≥5 settles landed and no settle carried a nonzero delta (gross, never net)`, replace the paragraph beginning "`starvation_cliff` reads the death record directly" with a note that death causes live in per-entry history persisted in `memory.json` (`ledger.py:685`) rather than in the JSONL log, so `doctor` takes a `Ledger`, and change "already implements rules 1–3" to "already implements rules 1–2 (and is itself untested; the anti-drift test is its first)".

- [ ] **Step 10: Lint, type-check, commit**

```bash
uvx ruff format darwin_memo/diagnose.py darwin_memo/survival.py tests/test_observe.py
uvx ruff check darwin_memo/diagnose.py darwin_memo/survival.py tests/test_observe.py
uvx --python 3.13 --with-editable . --with pytest mypy
git add darwin_memo/diagnose.py darwin_memo/survival.py tests/test_observe.py docs/superpowers/specs/2026-08-07-operator-surface-design.md
git commit -m "feat: shared degeneracy rules for batch and ledger diagnosis"
```

---

## Task 2: `timeline()` and `economics()`

**Files:**
- Modify: `darwin_memo/observe.py` (append after `audit_digest`, before `cmd_audit`)
- Test: `tests/test_observe.py`

**Interfaces:**
- Consumes: `audit_digest(events, store)` (`observe.py:274`), `MemoryStore.upkeep` / `.graveyard()` / `.alive()` / `__len__`.
- Produces: `timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]` with row keys `tick, population, total_energy, deaths, merges, pending, delta`; `economics(events: list[dict[str, Any]], store: MemoryStore) -> dict[str, Any]` with top-level keys `resource`, `energy`, `population`.

- [ ] **Step 1: Write the failing test**

```python
from darwin_memo.observe import economics, timeline


def test_timeline_rows_track_ticks_and_bucket_settled_deltas(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.tick()
    ledger.save(memory)

    rows = timeline(read_events(memory.with_suffix(".events.jsonl")))
    assert [r["tick"] for r in rows] == [1, 2]
    assert rows[0]["delta"] == 7.0, "settled before the first tick closed"
    assert rows[1]["delta"] == 0.0
    assert set(rows[0]) == {
        "tick", "population", "total_energy", "deaths", "merges",
        "pending", "delta",
    }


def test_economics_separates_resource_from_energy(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.save(memory)

    report = economics(read_events(memory.with_suffix(".events.jsonl")), ledger.store)
    assert report["resource"]["delta_total"] == 7.0, "world units, never energy"
    assert report["resource"]["decides"] == 1
    assert report["energy"]["credited"] > 0
    assert report["energy"]["upkeep_paid"] == pytest.approx(
        report["population"]["alive"] * 0.05
    ), "one tick of upkeep for the surviving population"
    assert report["energy"]["upkeep_exact"] is False
    assert report["energy"]["upkeep_caveat"] == "", "no pinned entries in this store"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py -k "timeline or economics" -v`
Expected: FAIL with `ImportError: cannot import name 'timeline'`

- [ ] **Step 3: Implement both**

Append to `darwin_memo/observe.py`, after `audit_digest` and before `cmd_audit`:

```python
def timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per tick record, with settled deltas bucketed by tick.

    Rows carry whatever tick records the log still holds; a rotated log
    leaves a gap in the tick numbers, which callers plot on a numeric
    axis so the gap shows as a gap rather than an interpolated line.
    """
    delta_by_tick: dict[int, float] = {}
    for record in events:
        if record.get("event") == "settle" and isinstance(record.get("tick"), int):
            tick = int(record["tick"])
            delta_by_tick[tick] = delta_by_tick.get(tick, 0.0) + float(
                record.get("delta") or 0.0
            )
    rows: list[dict[str, Any]] = []
    for record in events:
        if record.get("event") != "tick":
            continue
        tick = int(record.get("tick") or 0)
        rows.append(
            {
                "tick": tick,
                "population": int(record.get("population") or 0),
                "total_energy": float(record.get("total_energy") or 0.0),
                "deaths": int(record.get("deaths") or 0),
                "merges": int(record.get("merges") or 0),
                "pending": int(record.get("pending") or 0),
                "delta": round(delta_by_tick.get(tick, 0.0), 6),
            }
        )
    return rows


def economics(
    events: list[dict[str, Any]], store: MemoryStore
) -> dict[str, Any]:
    """Two currencies, reported separately and never summed.

    The **resource** ledger is the real case: settled deltas in world
    units (bytes, passing tests, dollars), with decide and silence
    counts so coverage is visible — the same delta over three decisions
    and over three hundred are not the same claim. The **energy** ledger
    is the internal, dimensionless mechanism. Adding one to the other
    would be adding bytes to tanh output.

    Upkeep is estimated as population x upkeep. Every alive entry pays
    each tick (``MemoryStore.charge_upkeep``: ``protect`` and ``pinned``
    change burial and flooring, not the charge), so the estimate is
    exact except that a pinned entry sitting at zero has its charge
    forgiven by the floor.
    """
    digest = audit_digest(events, store=store)
    rows = timeline(events)
    upkeep_paid = round(sum(r["population"] for r in rows) * store.upkeep, 6)
    pinned = sum(1 for entry in store.alive() if entry.pinned)
    caveat = (
        f"estimated as population x upkeep; {pinned} pinned "
        "entries may have had a charge forgiven at the zero floor"
        if pinned
        else ""
    )
    return {
        "resource": {
            "delta_total": digest["settles"]["delta_total"],
            "decides": digest["decides"]["total"],
            "silent": digest["decides"]["silent"],
            "settles": digest["settles"]["landed"],
        },
        "energy": {
            "credited": digest["energy"]["credited"],
            "debited": digest["energy"]["debited"],
            "net": digest["energy"]["net"],
            "upkeep_paid": upkeep_paid,
            "upkeep_exact": False,
            "upkeep_caveat": caveat,
        },
        "population": {"alive": len(store), "dead": len(store.graveyard())},
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py -k "timeline or economics" -v`
Expected: 2 passed

- [ ] **Step 5: Lint, type-check, commit**

```bash
uvx ruff format darwin_memo/observe.py tests/test_observe.py
uvx ruff check darwin_memo/observe.py tests/test_observe.py
uvx --python 3.13 --with-editable . --with pytest mypy
git add darwin_memo/observe.py tests/test_observe.py
git commit -m "feat: timeline and economics over the event log"
```

---

## Task 3: `doctor()` and the `darwin-memo doctor` command

**Files:**
- Modify: `darwin_memo/observe.py` (add `doctor`, `_operational_findings`, `cmd_doctor`; rename `_top_row` → `top_row`; extend module docstring; register the subparser)
- Modify: `darwin_memo/cli.py:204-216` (`cmd_stats` economics line)
- Test: `tests/test_observe.py`

**Interfaces:**
- Consumes: `Finding`, `selection_findings`, `STALE_TICKET_TICKS`, `MIN_DEATHS`, `STARVED_SHARE` from Task 1; `audit_digest`, `entry_life`, `read_events`, `timeline`, `economics`.
- Produces: `doctor(ledger: Ledger, events: list[dict[str, Any]]) -> list[Finding]`; `top_row(entry: MemoryEntry, tick: int) -> dict[str, Any]` (public rename); `cmd_doctor(args) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
from darwin_memo.observe import doctor


def _events(memory):
    return read_events(memory.with_suffix(".events.jsonl"))


def test_doctor_is_clean_on_a_healthy_store(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
        ledger.tick()
    ledger.save(memory)
    assert doctor(ledger, _events(memory)) == []


def test_doctor_names_an_environment_that_never_paid(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=0.0, detail="nothing happened")
        ledger.tick()
    ledger.save(memory)
    codes = [f.code for f in doctor(ledger, _events(memory))]
    assert "env_never_paid" in codes
    assert "silent_majority" not in codes, "memory answered; it just never earned"


def test_doctor_flags_a_stale_ticket(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ledger.decide("are stale feature flags safe to remove?")
    ledger.tick_count = 500  # far past STALE_TICKET_TICKS
    ledger.save(memory)
    findings = {f.code: f for f in doctor(ledger, _events(memory))}
    assert findings["tickets_stale"].severity == "warn"


def test_doctor_cli_exits_nonzero_on_an_error_finding(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=0.0, detail="nothing happened")
        ledger.tick()
    ledger.save(memory)

    assert cli_main(["doctor", str(memory)]) == 1
    assert "env_never_paid" in capsys.readouterr().out

    assert cli_main(["doctor", str(memory), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"][0]["code"] == "env_never_paid"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py -k doctor -v`
Expected: FAIL with `ImportError: cannot import name 'doctor'`

- [ ] **Step 3: Rename `_top_row` to `top_row`**

In `darwin_memo/observe.py`, rename the function at line 42 and its single call site inside `cmd_top` (line 65). `ui.py` imports it in Task 4 and importing a private name across modules is worse than the rename.

- [ ] **Step 4: Implement `doctor`**

Add to the `darwin_memo/observe.py` imports:

```python
from .diagnose import (
    MIN_DEATHS,
    STALE_TICKET_TICKS,
    STARVED_SHARE,
    Finding,
    selection_findings,
)
```

Append after `economics`:

```python
def _starved_unused(ledger: Ledger) -> tuple[int, int]:
    """(entries that starved having never earned, total dead).

    Cause of death lives in per-entry history persisted inside the
    memory file, not in the JSONL log, so this reads the ledger through
    :func:`entry_life` — the same path ``why`` uses, so one definition
    of "starved" serves both.
    """
    dead = ledger.store.graveyard()
    starved = 0
    for entry in dead:
        life = entry_life(ledger, entry.id)
        if life and life["cause_of_death"] == "starved" and not life["settlements"]:
            starved += 1
    return starved, len(dead)


def _operational_findings(
    ledger: Ledger, digest: dict[str, Any]
) -> list[Finding]:
    """Faults that only exist in the event-driven shape."""
    findings: list[Finding] = []

    starved, dead = _starved_unused(ledger)
    if dead >= MIN_DEATHS and starved / dead >= STARVED_SHARE:
        findings.append(
            Finding(
                code="starvation_cliff",
                severity="error",
                summary=f"{starved} of {dead} dead entries starved unused",
                evidence=f"{starved}/{dead} died having never been credited",
                fix=(
                    "nothing ever earned its upkeep: entries spawn at 1.0 and "
                    "pay 0.05 a tick, so an unconsulted population dies around "
                    "tick 20 whatever else is true"
                ),
            )
        )

    stale = [
        t
        for t in ledger.pending()
        if ledger.tick_count - t.born_tick > STALE_TICKET_TICKS
    ]
    if stale:
        findings.append(
            Finding(
                code="tickets_stale",
                severity="warn",
                summary=f"{len(stale)} tickets older than {STALE_TICKET_TICKS} ticks",
                evidence=", ".join(t.id for t in stale[:5]),
                fix=(
                    "decisions were acted on but never reported back; settle "
                    "or abandon them, or let tick() expire them at delta zero"
                ),
            )
        )

    dropped = int(digest["settles"]["dropped"])
    if dropped:
        findings.append(
            Finding(
                code="settles_dropped",
                severity="warn",
                summary=f"{dropped} settlements landed on unknown tickets",
                evidence=f"{dropped} settle_dropped events",
                fix=(
                    "the ticket id was already settled, abandoned, or minted "
                    "by a different store file"
                ),
            )
        )

    untracked = int(digest["settles"]["untracked"])
    if untracked:
        findings.append(
            Finding(
                code="credit_untracked",
                severity="warn",
                summary=f"{untracked} settlements carry no per-entry credit",
                evidence=f"{untracked} settle events without an 'applied' list",
                fix=(
                    "written by a version before per-entry credit was logged; "
                    "energy flow for those settlements is unattributable"
                ),
            )
        )
    return findings


def doctor(ledger: Ledger, events: list[dict[str, Any]]) -> list[Finding]:
    """Name the failure mode behind a store that is not earning.

    Takes the ledger rather than the store because two of the six rules
    read state the JSONL log does not carry: death causes (per-entry
    history, persisted in the memory file) and open tickets.
    """
    digest = audit_digest(events, store=ledger.store)
    # Gross movement: count settlements that individually moved, so a
    # window whose payouts cancel is not read as a dead environment.
    nonzero = sum(
        1
        for record in events
        if record.get("event") == "settle"
        and float(record.get("delta") or 0.0) != 0.0
    )
    findings = selection_findings(
        decides=int(digest["decides"]["total"]),
        silent=int(digest["decides"]["silent"]),
        nonzero_outcomes=nonzero,
        settles=int(digest["settles"]["landed"]),
    )
    findings.extend(_operational_findings(ledger, digest))
    return findings


def cmd_doctor(args: argparse.Namespace) -> int:
    ledger = _load_ledger(args.memory)
    if ledger is None:
        return 1
    log = Path(args.memory).expanduser().with_suffix(".events.jsonl")
    findings = doctor(ledger, read_events(log))
    if args.json:
        print(json.dumps({"findings": [f.as_dict() for f in findings]}))
    elif not findings:
        print("clean: no degeneracy detected")
    else:
        for finding in findings:
            print(f"{finding.severity.upper()}: {finding.summary}")
            print(f"  evidence: {finding.evidence}")
            print(f"  fix: {finding.fix}")
    return 1 if any(f.severity == "error" for f in findings) else 0
```

- [ ] **Step 5: Register the subcommand**

In `register_observe_commands` (`observe.py:433`), append before the closing of the function:

```python
    diagnose_cmd = sub.add_parser(
        "doctor", help="name the failure mode behind a store that is not earning"
    )
    diagnose_cmd.add_argument("memory")
    diagnose_cmd.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )
    diagnose_cmd.set_defaults(fn=cmd_doctor)
```

Add the command to the module docstring's command list at the top of `observe.py`:

```
    darwin-memo doctor FILE [--json]                        diagnosis
```

- [ ] **Step 6: Run to verify they pass**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py -v`
Expected: all pass

- [ ] **Step 7: Add the economics line to `stats`**

In `darwin_memo/cli.py`, add the import:

```python
from .observe import economics, read_events
```

In `cmd_stats` (`cli.py:204`), insert after the `total energy` line:

```python
    log = Path(args.memory).expanduser().with_suffix(".events.jsonl")
    if log.exists():
        report = economics(read_events(log), store)
        resource, energy = report["resource"], report["energy"]
        print(
            f"resource delta: {resource['delta_total']:+g} over "
            f"{resource['decides']} decisions ({resource['silent']} silent)"
        )
        print(
            f"energy: net {energy['net']:+.3f} against "
            f"{energy['upkeep_paid']:.3f} upkeep paid"
        )
```

- [ ] **Step 8: Test the stats line**

```python
def test_stats_reports_economics_when_an_event_log_exists(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.save(memory)

    assert cli_main(["stats", str(memory)]) == 0
    out = capsys.readouterr().out
    assert "resource delta: +7" in out
    assert "upkeep paid" in out
```

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_observe.py -k stats_reports -v`
Expected: PASS

- [ ] **Step 9: Lint, type-check, full suite, commit**

```bash
uvx ruff format darwin_memo/observe.py darwin_memo/cli.py tests/test_observe.py
uvx ruff check darwin_memo/observe.py darwin_memo/cli.py tests/test_observe.py
uvx --python 3.13 --with-editable . --with pytest mypy
uvx --python 3.13 --with-editable . --with pytest pytest
git add darwin_memo/observe.py darwin_memo/cli.py tests/test_observe.py
git commit -m "feat: darwin-memo doctor names the failure mode behind a dead store"
```

---

## Task 4: The read-only server

**Files:**
- Create: `darwin_memo/ui.py`
- Modify: `darwin_memo/cli.py` (register `ui`)
- Modify: `.gitignore` (ignore the bundle)
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `doctor`, `economics`, `timeline`, `entry_life`, `filter_events`, `read_events`, `top_row` from `observe`; `Ledger.load`, `Ledger.pending`, `Ledger.tick_count`.
- Produces: `state(memory: Path) -> dict[str, Any]`; `serve(memory: Path, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer`; `cmd_ui(args) -> int`; `BUNDLE: Path`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui.py`:

```python
"""The local dashboard server: read-only, loopback-only, JSON over observe."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from darwin_memo import Ledger, MemoryEntry, MemoryStore
from darwin_memo.ui import serve, state


@pytest.fixture
def served(tmp_path):
    memory = tmp_path / "memory.json"
    store = MemoryStore(upkeep=0.05)
    store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
            sources=["runbook"],
        )
    )
    ledger = Ledger(
        store, resource_scale=1.0, event_log=memory.with_suffix(".events.jsonl")
    )
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.save(memory)

    server = serve(memory, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", memory, ticket
    server.shutdown()
    server.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_state_endpoint_carries_every_panel(served):
    base, _, _ = served
    status, payload = _get(f"{base}/api/state")
    assert status == 200
    assert set(payload) >= {
        "tick", "upkeep", "counts", "total_energy", "doctor",
        "timeline", "economics", "entries", "graveyard", "pending",
    }
    assert payload["entries"][0]["ticks_to_starvation"] > 0


def test_entry_endpoint_returns_a_life_and_404s_on_nonsense(served):
    base, _, ticket = served
    status, life = _get(f"{base}/api/entry/{ticket.deciding_entry}")
    assert status == 200
    assert life["id"] == ticket.deciding_entry
    with pytest.raises(urllib.error.HTTPError) as caught:
        _get(f"{base}/api/entry/not-a-real-id")
    assert caught.value.code == 404


def test_static_route_refuses_to_escape_the_bundle(served):
    base, _, _ = served
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{base}/../../../etc/passwd", timeout=5)
    assert caught.value.code == 404


def test_serve_refuses_a_non_loopback_host(tmp_path):
    memory = tmp_path / "memory.json"
    MemoryStore().save(memory)
    with pytest.raises(ValueError, match="loopback"):
        serve(memory, port=0, host="0.0.0.0")


def test_state_is_read_only(tmp_path):
    memory = tmp_path / "memory.json"
    store = MemoryStore(upkeep=0.05)
    store.add(
        MemoryEntry(question="q", answer="a", sources=["runbook"])
    )
    Ledger(store).save(memory)
    before = memory.read_bytes()
    state(memory)
    assert memory.read_bytes() == before, "the dashboard must never write"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_ui.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'darwin_memo.ui'`

- [ ] **Step 3: Implement the server**

Create `darwin_memo/ui.py`:

```python
"""A local, read-only dashboard over one memory file.

    darwin-memo ui memory.json [--port 8787] [--no-open]

Loopback-only and read-only by construction. There are no mutation
endpoints, which is precisely what lets this skip authentication, CSRF
tokens and session handling: nothing a browser can reach here changes
state. Culling, settling and pinning stay on the CLI and MCP, where
every operation is event-logged and audited.

The store and the event log are re-read on every request. They are
small, and a dashboard showing yesterday's population is worse than a
re-parse.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .ledger import Ledger
from .observe import (
    doctor,
    economics,
    entry_life,
    filter_events,
    read_events,
    timeline,
    top_row,
)

BUNDLE = Path(__file__).parent / "data" / "ui"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

_NO_BUNDLE = b"""<!doctype html><meta charset="utf-8">
<title>darwin-memo</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto">
<h1>No UI bundle</h1>
<p>This checkout has no built frontend. Build it once:</p>
<pre>cd ui &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>The JSON API is live regardless: <a href="/api/state">/api/state</a></p>
"""


def _load(memory: Path) -> tuple[Ledger, list[dict[str, Any]]]:
    ledger = Ledger.load(memory)
    return ledger, read_events(memory.with_suffix(".events.jsonl"))


def state(memory: Path) -> dict[str, Any]:
    """Everything the dashboard renders, in one read-only pass."""
    ledger, events = _load(memory)
    store = ledger.store
    tick = ledger.tick_count
    upkeep = store.upkeep
    entries = []
    for entry in sorted(store.alive(), key=lambda e: e.energy, reverse=True):
        row = top_row(entry, tick)
        # The operator's actual question, and the one number that makes
        # the starvation cliff visible before it bites.
        row["ticks_to_starvation"] = (
            round(entry.energy / upkeep, 1) if upkeep > 0 else None
        )
        entries.append(row)
    graveyard = []
    for dead in store.graveyard():
        life = entry_life(ledger, dead.id)
        if life is None:
            continue
        graveyard.append(
            {
                "id": life["id"],
                "question": life["question"],
                "cause": life["cause_of_death"] or "unknown",
                "uses": life["uses"],
                "sources": life["sources"],
            }
        )
    return {
        "tick": tick,
        "upkeep": upkeep,
        "counts": {
            "alive": len(store),
            "dead": len(store.graveyard()),
            "pinned": sum(1 for e in store.alive() if e.pinned),
            "pending": len(ledger.pending()),
        },
        "total_energy": round(store.total_energy(), 3),
        "doctor": [f.as_dict() for f in doctor(ledger, events)],
        "timeline": timeline(events),
        "economics": economics(events, store),
        "entries": entries,
        "graveyard": graveyard,
        "pending": [
            {
                "id": ticket.id,
                "query": ticket.query,
                "born_tick": ticket.born_tick,
                "age_ticks": tick - ticket.born_tick,
            }
            for ticket in ledger.pending()
        ],
    }


class _Handler(BaseHTTPRequestHandler):
    """GET-only. Any other verb is a 405; there is nothing to write."""

    server_version = "darwin-memo"

    def __init__(self, memory: Path, *args: Any, **kwargs: Any) -> None:
        self.memory = memory
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence per-request logging; the terminal shows the URL only."""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802 (stdlib callback name)
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        try:
            if route == "/api/state":
                self._json(200, state(self.memory))
            elif route.startswith("/api/entry/"):
                self._entry(route[len("/api/entry/") :])
            elif route == "/api/events":
                self._events(parse_qs(parsed.query))
            else:
                self._static(route)
        except FileNotFoundError:
            self._json(404, {"error": "memory file not found"})

    def _entry(self, entry_id: str) -> None:
        ledger, _ = _load(self.memory)
        life = entry_life(ledger, entry_id)
        if life is None:
            self._json(404, {"error": f"{entry_id} is unknown to this store"})
            return
        self._json(200, life)

    def _events(self, query: dict[str, list[str]]) -> None:
        _, events = _load(self.memory)
        last = query.get("last", ["200"])[0]
        since = query.get("since", [None])[0]
        try:
            limit: int | None = int(last)
        except ValueError:
            limit = 200
        self._json(200, {"events": filter_events(events, since=since, last=limit)})

    def _static(self, route: str) -> None:
        if not BUNDLE.is_dir():
            self._send(200, _NO_BUNDLE, "text/html; charset=utf-8")
            return
        root = BUNDLE.resolve()
        target = (root / route.lstrip("/")).resolve()
        if target == root or target.is_dir():
            target = root / "index.html"
        # Containment check before touching the filesystem: a path that
        # climbed out of the bundle is a 404, never a read.
        if root not in target.parents or not target.is_file():
            self._json(404, {"error": "not found"})
            return
        guessed, _ = mimetypes.guess_type(target.name)
        self._send(200, target.read_bytes(), guessed or "application/octet-stream")


def serve(
    memory: Path, port: int, host: str = "127.0.0.1"
) -> ThreadingHTTPServer:
    """Build (but do not start) the dashboard server.

    Refuses a non-loopback bind: the server has no authentication
    because it has no mutations, and that trade only holds on localhost.
    """
    if host not in LOOPBACK:
        raise ValueError(
            f"refusing to bind {host}: the dashboard is unauthenticated "
            "and loopback-only by design"
        )
    return ThreadingHTTPServer((host, port), partial(_Handler, memory))


def cmd_ui(args: argparse.Namespace) -> int:
    memory = Path(args.memory).expanduser()
    if not memory.exists():
        print(f"error: {args.memory} not found")
        return 1
    server = serve(memory, port=args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"darwin-memo ui: {url}  (ctrl-c to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0
```

- [ ] **Step 4: Register the command**

In `darwin_memo/cli.py`, add `from .ui import cmd_ui` to the imports, and inside `main()` next to the other `sub.add_parser` calls (before `register_observe_commands(sub)`):

```python
    ui = sub.add_parser("ui", help="local read-only dashboard in your browser")
    ui.add_argument("memory")
    ui.add_argument("--port", type=int, default=8787, help="default 8787; 0 picks one")
    ui.add_argument("--no-open", action="store_true", help="do not open a browser")
    ui.set_defaults(fn=cmd_ui)
```

Add the line to the `cli.py` module docstring command list:

```
    darwin-memo ui FILE                  local read-only dashboard
```

- [ ] **Step 5: Ignore the build output**

Append to `.gitignore`:

```
# Built by ui/; shipped in the wheel, never committed.
darwin_memo/data/ui/
```

- [ ] **Step 6: Run to verify they pass**

Run: `uvx --python 3.13 --with-editable . --with pytest pytest tests/test_ui.py -v`
Expected: 5 passed

- [ ] **Step 7: Lint, type-check, full suite, commit**

```bash
uvx ruff format darwin_memo/ui.py darwin_memo/cli.py tests/test_ui.py
uvx ruff check darwin_memo/ui.py darwin_memo/cli.py tests/test_ui.py
uvx --python 3.13 --with-editable . --with pytest mypy
uvx --python 3.13 --with-editable . --with pytest pytest
git add darwin_memo/ui.py darwin_memo/cli.py tests/test_ui.py .gitignore
git commit -m "feat: darwin-memo ui serves a read-only dashboard on loopback"
```

---

## Task 5: Frontend scaffold, packaging, and the app shell

**Files:**
- Create: `ui/` (Vite scaffold), `ui/src/api.ts`, `ui/src/App.tsx`, `ui/src/theme.css`, `ui/src/panels/Header.tsx`, `ui/src/panels/DoctorBanner.tsx`
- Modify: `pyproject.toml` (package data), `.github/workflows/release.yml`, `CONTRIBUTING.md`

**Interfaces:**
- Consumes: `GET /api/state` from Task 4.
- Produces: `useState()` hook and the `State` TypeScript type in `ui/src/api.ts`, imported by every panel in Tasks 6–8.

- [ ] **Step 1: Scaffold**

```bash
cd ~/darwin-memo-operator
npm create vite@latest ui -- --template react-ts
cd ui && npm install && npm install recharts
```

Use whatever versions the scaffold resolves — do not pin by hand.

- [ ] **Step 2: Point the build at package data**

Replace `ui/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Relative asset URLs: the bundle is served from package data at /,
  // but never assume a mount point.
  base: "./",
  build: { outDir: "../darwin_memo/data/ui", emptyOutDir: true },
  // Dev server proxies the API to a running `darwin-memo ui`.
  server: { proxy: { "/api": "http://127.0.0.1:8787" } },
});
```

- [ ] **Step 3: Write the API client**

Create `ui/src/api.ts`:

```ts
export type Finding = {
  code: string;
  severity: "error" | "warn";
  summary: string;
  evidence: string;
  fix: string;
};

export type TimelineRow = {
  tick: number;
  population: number;
  total_energy: number;
  deaths: number;
  merges: number;
  pending: number;
  delta: number;
};

export type Entry = {
  id: string;
  balance: number;
  kind: string;
  sources: string[];
  born_tick: number;
  age_ticks: number;
  last_settled_tick: number | null;
  uses: number;
  pinned: boolean;
  probation: number;
  question: string;
  ticks_to_starvation: number | null;
};

export type Grave = {
  id: string;
  question: string | null;
  cause: string;
  uses: number | null;
  sources: string[];
};

export type State = {
  tick: number;
  upkeep: number;
  counts: { alive: number; dead: number; pinned: number; pending: number };
  total_energy: number;
  doctor: Finding[];
  timeline: TimelineRow[];
  economics: {
    resource: {
      delta_total: number;
      decides: number;
      silent: number;
      settles: number;
    };
    energy: {
      credited: number;
      debited: number;
      net: number;
      upkeep_paid: number;
      upkeep_exact: boolean;
      upkeep_caveat: string;
    };
    population: { alive: number; dead: number };
  };
  entries: Entry[];
  graveyard: Grave[];
  pending: { id: string; query: string; born_tick: number; age_ticks: number }[];
};

import { useEffect, useState } from "react";

const POLL_MS = 2000;

export function useServerState() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const response = await fetch("api/state");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (live) {
          setState(await response.json());
          setError(null);
        }
      } catch (caught) {
        if (live) setError(String(caught));
      }
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  return { state, error };
}

export async function fetchEntry(id: string) {
  const response = await fetch(`api/entry/${encodeURIComponent(id)}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
```

- [ ] **Step 4: Design the shell**

Invoke the `frontend-design` skill before writing `theme.css` and the panels. Direction: clean light, muted teal accent, generous whitespace, a monospace column for ids and numbers. Do not use a dark-only palette.

Create `ui/src/theme.css` with CSS custom properties for the palette, spacing scale, and a `.panel` card class, and import it from `ui/src/main.tsx`.

- [ ] **Step 5: Write the shell and the two first panels**

Replace `ui/src/App.tsx`:

```tsx
import { useServerState } from "./api";
import { Header } from "./panels/Header";
import { DoctorBanner } from "./panels/DoctorBanner";

export default function App() {
  const { state, error } = useServerState();
  if (error) return <main className="panel">Cannot reach the server: {error}</main>;
  if (!state) return <main className="panel">Loading…</main>;
  return (
    <main>
      <Header state={state} />
      <DoctorBanner findings={state.doctor} />
    </main>
  );
}
```

Create `ui/src/panels/Header.tsx`:

```tsx
import type { State } from "../api";

export function Header({ state }: { state: State }) {
  const { counts } = state;
  const cells: [string, string | number][] = [
    ["tick", state.tick],
    ["alive", counts.alive],
    ["dead", counts.dead],
    ["pinned", counts.pinned],
    ["pending", counts.pending],
    ["total energy", state.total_energy.toFixed(2)],
  ];
  return (
    <header className="panel header">
      {cells.map(([label, value]) => (
        <div key={label}>
          <span className="label">{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </header>
  );
}
```

Create `ui/src/panels/DoctorBanner.tsx`:

```tsx
import type { Finding } from "../api";

export function DoctorBanner({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <section className="panel clean">No degeneracy detected.</section>;
  }
  return (
    <section className="panel">
      {findings.map((finding) => (
        <article key={finding.code} className={`finding ${finding.severity}`}>
          <h3>{finding.summary}</h3>
          <p className="label">{finding.evidence}</p>
          <p>{finding.fix}</p>
        </article>
      ))}
    </section>
  );
}
```

- [ ] **Step 6: Ship the bundle as package data**

In `pyproject.toml`, change the package-data line to:

```toml
[tool.setuptools.package-data]
darwin_memo = ["py.typed", "data/demo_corpus/*.txt", "data/ui/**/*"]
```

- [ ] **Step 7: Build the bundle before the wheel in CI**

Read `.github/workflows/release.yml` and insert, before the step that builds the distribution:

```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: Build the dashboard bundle
        run: npm ci && npm run build
        working-directory: ui
```

Add to `CONTRIBUTING.md`, under a new "Dashboard" heading: the bundle is built from `ui/` with `npm install && npm run build`, the output at `darwin_memo/data/ui/` is gitignored and produced in CI at release, and `darwin-memo ui` serves a "no bundle" page with a live JSON API when it is absent, so Python-only contributors never need node.

- [ ] **Step 8: Verify end to end**

```bash
cd ~/darwin-memo-operator/ui && npm run build && cd ..
darwin-memo ledger /tmp/dm-ui.json decide "are stale feature flags safe to remove?"
darwin-memo ui /tmp/dm-ui.json --no-open --port 8787
```

Expected: the page loads with a populated header and a doctor banner. (The store is nearly empty, so "No degeneracy detected" is the correct reading at this point.)

- [ ] **Step 9: Commit**

```bash
git add ui pyproject.toml .github/workflows/release.yml CONTRIBUTING.md
git commit -m "feat: dashboard scaffold, app shell, and release build wiring"
```

---

## Task 6: Timeline chart and the living-entries table

**Files:**
- Create: `ui/src/panels/Timeline.tsx`, `ui/src/panels/LivingTable.tsx`
- Modify: `ui/src/App.tsx`

**Interfaces:**
- Consumes: `State`, `TimelineRow`, `Entry` from `ui/src/api.ts`.
- Produces: `<Timeline rows={...} />`, `<LivingTable entries={...} onSelect={...} />`.

- [ ] **Step 1: Read the dataviz guidance**

Invoke the `dataviz` skill before writing the chart. Two series on one plot: `population` (count) and `total_energy` (energy) need separate y-axes, and `tick` is a numeric x-axis so a rotated-away gap renders as a gap.

- [ ] **Step 2: Write the chart**

Create `ui/src/panels/Timeline.tsx`:

```tsx
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import type { TimelineRow } from "../api";

export function Timeline({ rows }: { rows: TimelineRow[] }) {
  if (rows.length === 0) {
    return <section className="panel">No ticks recorded yet.</section>;
  }
  return (
    <section className="panel">
      <h2>Population over time</h2>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" />
          {/* Numeric x-axis: a rotated log leaves a gap, and it should look like one. */}
          <XAxis dataKey="tick" type="number" domain={["dataMin", "dataMax"]} />
          <YAxis yAxisId="count" />
          <YAxis yAxisId="energy" orientation="right" />
          <Tooltip />
          <Line yAxisId="count" dataKey="population" dot={false} />
          <Line yAxisId="energy" dataKey="total_energy" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </section>
  );
}
```

- [ ] **Step 3: Write the table**

Create `ui/src/panels/LivingTable.tsx`:

```tsx
import { useState } from "react";
import type { Entry } from "../api";

type Column = keyof Pick<
  Entry, "balance" | "ticks_to_starvation" | "uses" | "age_ticks"
>;

export function LivingTable({
  entries,
  onSelect,
}: {
  entries: Entry[];
  onSelect: (id: string) => void;
}) {
  const [sortBy, setSortBy] = useState<Column>("balance");
  const sorted = [...entries].sort(
    (a, b) => Number(b[sortBy] ?? 0) - Number(a[sortBy] ?? 0),
  );
  return (
    <section className="panel">
      <h2>Living entries</h2>
      <table>
        <thead>
          <tr>
            {(
              ["balance", "ticks_to_starvation", "uses", "age_ticks"] as Column[]
            ).map((column) => (
              <th key={column}>
                <button onClick={() => setSortBy(column)}>
                  {column.replace(/_/g, " ")}
                </button>
              </th>
            ))}
            <th>question</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((entry) => (
            <tr key={entry.id} onClick={() => onSelect(entry.id)}>
              <td className="num">{entry.balance.toFixed(2)}</td>
              <td className="num">
                {entry.ticks_to_starvation?.toFixed(1) ?? "—"}
              </td>
              <td className="num">{entry.uses}</td>
              <td className="num">{entry.age_ticks}</td>
              <td>
                {entry.question}
                {entry.pinned && <span className="tag">pinned</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 4: Mount both**

In `ui/src/App.tsx`, add the selection state and render `<Timeline rows={state.timeline} />` and `<LivingTable entries={state.entries} onSelect={setSelected} />` after `<DoctorBanner />`.

The selected id is not read until the drawer arrives in Task 8, and the Vite react-ts template sets `noUnusedLocals`, so elide the unused binding rather than suppressing the warning:

```tsx
const [, setSelected] = useState<string | null>(null);
```

Task 8 changes that one line to `const [selected, setSelected] = useState<string | null>(null);` when it mounts the drawer.

- [ ] **Step 5: Verify and commit**

```bash
cd ui && npm run build && npx tsc --noEmit && cd ..
darwin-memo ui /tmp/dm-ui.json --no-open
```

Expected: the chart draws and the table sorts on header click.

```bash
git add ui && git commit -m "feat: dashboard timeline chart and living-entries table"
```

---

## Task 7: Graveyard and economics

**Files:**
- Create: `ui/src/panels/Graveyard.tsx`, `ui/src/panels/Economics.tsx`
- Modify: `ui/src/App.tsx`

**Interfaces:**
- Consumes: `State["graveyard"]`, `State["economics"]`.
- Produces: `<Graveyard graves={...} />`, `<Economics report={...} />`.

- [ ] **Step 1: Write the graveyard**

The starved-vs-executed split is the thesis rendered as a picture — starved is the property no counter has — so counts lead and the list follows.

Create `ui/src/panels/Graveyard.tsx`:

```tsx
import type { Grave } from "../api";

const ORDER = ["starved", "executed", "merged", "forgotten", "unknown"];

export function Graveyard({ graves }: { graves: Grave[] }) {
  const byCause = new Map<string, Grave[]>();
  for (const grave of graves) {
    byCause.set(grave.cause, [...(byCause.get(grave.cause) ?? []), grave]);
  }
  const causes = ORDER.filter((cause) => byCause.has(cause));
  return (
    <section className="panel">
      <h2>Graveyard</h2>
      <div className="cause-counts">
        {causes.map((cause) => (
          <div key={cause} className={`cause ${cause}`}>
            <strong>{byCause.get(cause)!.length}</strong>
            <span className="label">{cause}</span>
          </div>
        ))}
      </div>
      {causes.map((cause) => (
        <details key={cause}>
          <summary>
            {cause} ({byCause.get(cause)!.length})
          </summary>
          <ul>
            {byCause.get(cause)!.map((grave) => (
              <li key={grave.id}>
                <code>{grave.id}</code> {grave.question ?? "(no question on record)"}
              </li>
            ))}
          </ul>
        </details>
      ))}
      {graves.length === 0 && <p>Nothing has died yet.</p>}
    </section>
  );
}
```

- [ ] **Step 2: Write economics**

Create `ui/src/panels/Economics.tsx`:

```tsx
import type { State } from "../api";

export function Economics({ report }: { report: State["economics"] }) {
  const { resource, energy } = report;
  return (
    <section className="panel">
      <h2>Economics</h2>
      <p className="headline">
        <strong>{resource.delta_total > 0 ? "+" : ""}{resource.delta_total}</strong>
        <span className="label">
          resource delta over {resource.decides} decisions
          {resource.silent > 0 && ` (${resource.silent} silent)`}
        </span>
      </p>
      {/* Deliberately a separate block: energy is dimensionless and must
          never be read as continuous with the resource units above. */}
      <dl className="secondary">
        <dt>energy net</dt>
        <dd>{energy.net.toFixed(3)}</dd>
        <dt>upkeep paid</dt>
        <dd>
          {energy.upkeep_paid.toFixed(3)}
          {!energy.upkeep_exact && <span className="tag">estimated</span>}
        </dd>
      </dl>
      {energy.upkeep_caveat && <p className="label">{energy.upkeep_caveat}</p>}
    </section>
  );
}
```

- [ ] **Step 3: Mount both**

Add `<Economics report={state.economics} />` and `<Graveyard graves={state.graveyard} />` to `ui/src/App.tsx`, with `Economics` above `Graveyard`.

- [ ] **Step 4: Verify and commit**

```bash
cd ui && npm run build && npx tsc --noEmit && cd ..
git add ui && git commit -m "feat: dashboard graveyard and economics panels"
```

---

## Task 8: Event stream and entry drawer

**Files:**
- Create: `ui/src/panels/EventStream.tsx`, `ui/src/panels/EntryDrawer.tsx`
- Modify: `ui/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/events?last=N`, `fetchEntry(id)` from `ui/src/api.ts`, and the `selected` state from Task 6.
- Produces: `<EventStream />`, `<EntryDrawer id={...} onClose={...} />`.

- [ ] **Step 1: Write the event stream**

Create `ui/src/panels/EventStream.tsx`:

```tsx
import { useEffect, useState } from "react";

type Event = { event: string; tick?: number; ts?: string } & Record<string, unknown>;

export function EventStream() {
  const [events, setEvents] = useState<Event[]>([]);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    let live = true;
    const load = async () => {
      const response = await fetch("api/events?last=200");
      if (response.ok && live) setEvents((await response.json()).events);
    };
    load();
    const timer = setInterval(load, 2000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  const shown = filter
    ? events.filter((e) => JSON.stringify(e).includes(filter))
    : events;
  return (
    <section className="panel">
      <h2>Events</h2>
      <input
        value={filter}
        placeholder="filter"
        onChange={(change) => setFilter(change.target.value)}
      />
      <ol className="stream">
        {[...shown].reverse().map((event, index) => (
          <li key={index}>
            <code>t{event.tick ?? "?"}</code> <strong>{event.event}</strong>{" "}
            <span className="label">{event.ts ?? ""}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
```

- [ ] **Step 2: Write the drawer**

Create `ui/src/panels/EntryDrawer.tsx`:

```tsx
import { useEffect, useState } from "react";
import { fetchEntry } from "../api";

type Life = {
  id: string;
  status: string;
  question: string | null;
  answer: string | null;
  balance: number | null;
  uses: number | null;
  cause_of_death: string | null;
  birth: { tick: number | null; ts: string | null; source: string | null };
  settlements: Record<string, unknown>[];
  events: { text?: string }[];
};

export function EntryDrawer({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const [life, setLife] = useState<Life | null>(null);
  useEffect(() => {
    let live = true;
    fetchEntry(id).then((loaded) => live && setLife(loaded));
    return () => {
      live = false;
    };
  }, [id]);
  return (
    <aside className="drawer">
      <button onClick={onClose}>close</button>
      {!life ? (
        <p>Loading…</p>
      ) : (
        <>
          <h2>{life.question}</h2>
          <p>{life.answer}</p>
          <p className="label">
            {life.status} · balance {life.balance ?? "—"} · uses {life.uses ?? 0}
            {life.cause_of_death && ` · died: ${life.cause_of_death}`}
          </p>
          <ol className="stream">
            {life.events.map((event, index) => (
              <li key={index}>{event.text ?? JSON.stringify(event)}</li>
            ))}
          </ol>
        </>
      )}
    </aside>
  );
}
```

- [ ] **Step 3: Mount both**

In `ui/src/App.tsx`, change Task 6's `const [, setSelected] = …` to `const [selected, setSelected] = useState<string | null>(null);`, add `<EventStream />` after `<Graveyard />`, and render the drawer conditionally:

```tsx
{selected && <EntryDrawer id={selected} onClose={() => setSelected(null)} />}
```

- [ ] **Step 4: Verify and commit**

```bash
cd ui && npm run build && npx tsc --noEmit && cd ..
darwin-memo ui /tmp/dm-ui.json --no-open
```

Expected: clicking a table row opens the drawer with that entry's life; the event stream fills and filters.

```bash
git add ui && git commit -m "feat: dashboard event stream and entry drawer"
```

---

## Task 9: Documentation and release

**Files:**
- Modify: `README.md`, `docs/README.md`, `docs/api.md`, `docs/tuning.md`, `CHANGELOG.md`, `darwin_memo/__init__.py:51`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Document the two commands in `docs/api.md`**

Add `darwin-memo doctor FILE [--json]` and `darwin-memo ui FILE [--port N] [--no-open]` to the CLI section, with the six finding codes from Task 3 as a table (code, severity, what it means), and the exit-code contract: 0 clean or warnings only, 1 on any error finding.

- [ ] **Step 2: Cross-reference from `docs/tuning.md`**

In the section on failure symptoms, add a line pointing at `darwin-memo doctor` as the way to identify which symptom a live store is showing, rather than reading the table by hand.

- [ ] **Step 3: Add the dashboard to `README.md`**

After the "Event-driven (production shape): the Ledger" section, add a short block:

````markdown
### Seeing it: the local dashboard

```bash
darwin-memo doctor memory.json     # why is nothing earning?
darwin-memo ui memory.json         # population, graveyard, economics
```

`doctor` reads the event log and names which failure mode a store hit
instead of leaving three of them looking identical. `ui` serves the same
data as a read-only dashboard on localhost: population and energy over
time, the graveyard split by cause of death, and the resource-versus-
upkeep accounting. Read-only and loopback-only, so there is nothing to
authenticate.
````

Add both to the docs index in `docs/README.md` under "Operating it".

- [ ] **Step 4: Changelog and version**

Add to the `## [Unreleased]` / `### Added` section of `CHANGELOG.md` an entry covering: the shared degeneracy rules in `darwin_memo/diagnose.py` (and that `SurvivalReport.health_warning` now delegates to them so the batch loop and the Ledger cannot drift), `darwin-memo doctor` with its six findings and exit-code contract, `darwin-memo ui` as a read-only loopback dashboard with no new runtime dependency, and `timeline`/`economics` on the observe surface. State plainly that economics reports resource and energy separately because they are different units, and that upkeep is estimated until the tick event carries the exact figure.

Bump `__version__` in `darwin_memo/__init__.py:51` to `"0.6.0"`.

- [ ] **Step 5: Full verification**

```bash
uvx ruff check darwin_memo tests
uvx --python 3.13 --with-editable . --with pytest mypy
uvx --python 3.13 --with-editable . --with pytest --with pytest-cov --with hypothesis pytest --cov=darwin_memo
```

Expected: all pass, coverage at or above 80.

Then the three broken-store checks. Build each with `darwin-memo ledger`, run `darwin-memo doctor` on it, and confirm it names its own mode and not the others:

```bash
# never paid: decisions that settle at zero
for i in $(seq 1 6); do
  T=$(darwin-memo ledger /tmp/dm-zero.json decide "are stale flags safe to remove?" | python -c "import json,sys;print(json.load(sys.stdin)['ticket_id'])")
  darwin-memo ledger /tmp/dm-zero.json settle "$T" 0
  darwin-memo ledger /tmp/dm-zero.json tick
done
darwin-memo doctor /tmp/dm-zero.json        # expect env_never_paid, exit 1
```

The store must be seeded first (`darwin-memo encode` or `darwin-memo ledger … add`), or every decide is silent and the silence rule fires instead. `ticket_id` is `null` on a silent decide (`cli.py:256`), so a silent seed makes the settle call fail loudly rather than quietly measuring nothing. Repeat the pattern for a silent store (decide questions with no lexical overlap with the corpus) and a never-settled store (decide and tick without settling, expecting `tickets_stale`).

- [ ] **Step 6: Commit and open the PR**

```bash
git add -A
git commit -m "docs: operator surface in README, api, tuning, changelog; 0.6.0"
git push -u origin feat/operator-surface
gh pr create --title "Operator surface: doctor and a local read-only dashboard" --body "..."
```

The PR body should lead with what the surface makes visible (the starved-versus-executed split and the resource-versus-upkeep accounting), note that no runtime dependency was added, and state that `health_warning` gained its first tests.

---

## Self-Review

**Spec coverage:** §4.1 → Task 2. §4.2 → Task 2. §4.3 → Tasks 1 and 3 (all six findings). §4.4 → Task 3. §5 → Task 4 (all four endpoints, loopback refusal, traversal 404, per-request re-read). §6 → Tasks 5–8 (all eight panels). §7 → Task 5 (package data, release build, CONTRIBUTING). §9 → tests in Tasks 1–4. §10 → Task 9 Step 5. §11 build sequence → Tasks 1–9 in order.

**Known deviations from the spec, all corrected above and flagged in Task 1 Step 9:** `doctor` takes a `Ledger` not a store; `env_never_paid` counts gross movement; `health_warning` had two rules and no tests.

**Type consistency:** `Finding.as_dict()` is used by `cmd_doctor` and by `state()`; `top_row` is the public name everywhere after Task 3 Step 3; `timeline()` row keys match `TimelineRow` in `api.ts`; `state()` keys match `State` in `api.ts`; `ticket.query` (not `question`) matches the `Ticket` dataclass at `ledger.py:82`.
