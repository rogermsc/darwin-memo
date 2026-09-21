# Store format

What darwin-memo writes to disk and what it promises about reading it
back. The format is plain JSON, designed to be inspected with `jq`
and diffed in pull requests: this repo commits its own store
(`.darwin-memo/lessons.json`) and reviews changes to it like code.

## The store file (`memory.json` / `lessons.json`)

One JSON object. `MemoryStore.save` writes the first four keys;
`Ledger.save` writes the same payload plus `ledger`, so a ledger file
IS a valid plain store file and `MemoryStore.load` simply ignores the
`ledger` key.

| key | required | written by | content |
|---|---|---|---|
| `config` | yes | both | `{"max_energy": float, "upkeep": float}` |
| `entries` | yes | both | list of entry objects, the living population |
| `graveyard` | yes | both | list of entry objects, dead, kept forever |
| `retriever` | no | both | retriever state, only when non-empty (see below) |
| `ledger` | no | `Ledger.save` | tickets, tick count, history (see below) |

On load, `config` is filtered to the known keys (`max_energy`,
`upkeep`): unknown config keys from other versions are ignored, and
missing ones fall back to the constructor defaults. Unknown top-level
keys are ignored entirely.

### Entry objects

The output of `MemoryEntry.to_dict`, one per entry:

```json
{
  "question": "Are LLM benchmark arms safe to run in CI?",
  "answer": "No. Sampled model output is not deterministic; ...",
  "kind": "explicit",
  "sources": ["docs/benchmarks"],
  "energy": 0.9499996,
  "born_cycle": 0,
  "recorded_ts": "",
  "last_used_cycle": 1,
  "uses": 1,
  "lineage": [],
  "id": "053a99cf0a4c"
}
```

| field | type | required on load | default when missing |
|---|---|---|---|
| `question` | str | yes | |
| `answer` | str | yes | |
| `kind` | str, one of `explicit` / `inferred` / `entity` / `cross_doc` / `experience` / `consolidated` | yes | |
| `sources` | list[str] | no | `[]` |
| `energy` | float | no | `1.0` |
| `born_cycle` | int | no | `0` |
| `recorded_ts` | str | no | `""` (age unknown) |
| `last_used_cycle` | int | no | `-1` (never credited) |
| `uses` | int | no | `0` |
| `lineage` | list[str] | no | `[]` (ids of entries merged into this one) |
| `pinned` | bool | no | `false` (exempt from starvation and merges) |
| `probation` | int | no | `0` (net-positive settlements owed before it may decide) |
| `juvenile` | int | no | `0` (settlements left in its admission window) |
| `imported_from` | str \| null | no | `null` (source store path, set by `import`) |
| `imported_at` | str \| null | no | `null` (UTC ISO-8601 import moment) |
| `id` | str | yes | the loader keys entries by it (`KeyError` when missing) |

The five trust-lifecycle fields (`pinned` through `imported_at`) are
**written only when they differ from those defaults**, so a store that
never used them is byte-identical to one written before they existed,
and a reader from before the addition still loads it. Do not infer from
their absence that a store predates them.

An entry is alive when `energy > 1e-9`; graveyard entries have their
energy clamped to at most `0.0` at burial.

`recorded_ts` is the UTC ISO-8601 moment (second precision) the entry
was created; every consult surface renders it as part of the entry's
age line. Files saved before the field existed (the example above is
one such entry) load as the empty string and render as "age unknown":
the loader never substitutes a fake timestamp. Consolidation writes
the NEWEST merged member's `recorded_ts` into the merge product, so a
merge cannot make stale advice look freshly recorded.

### `retriever`

Present only when the retriever has state worth persisting. The
default `LexicalRetriever` has none, so most files lack this key.
`EmbeddingRetriever` writes `{"vectors": {entry_id: [float, ...]}}`,
which is what keeps paid embeddings from being recomputed on every
load. Loading hands the state to whatever retriever you construct,
and saving writes whatever the CURRENT retriever dumps.

CLI and MCP operations rank lexically when no embedder is supplied, but retain
cached embedding state across unrelated writes. Supplying an embedding retriever
restores those vectors. Burial removes the buried entry's cached vector.

### `ledger`

```json
{
  "tick_count": 12,
  "pending": [
    {
      "query": "Is the dedupe helper safe to remove?",
      "answer": "...",
      "deciding_entry": "053a99cf0a4c",
      "supporting_entries": ["9f2c01ab33de"],
      "born_tick": 11,
      "id": "6fb7013be81e"
    }
  ],
  "history": {"053a99cf0a4c": [ ... notes ... ]},
  "damaged": ["d4d3c2b1a098"]
}
```

- `tick_count`: how many ticks this ledger has run.
- `pending`: open tickets. All fields except `id` are required on
  load. Persisting tickets is the point: a ticket opened today must
  settle correctly from tomorrow's process.
- `history`: per-entry event notes, oldest first, capped at 100 per
  entry in memory (the JSONL event log is the full record). Notes
  written by current versions are objects
  (`{"tick": int, "ts": "<UTC ISO-8601>", "text": str, ...}` plus
  structured fields per event kind); notes from older versions are
  plain strings. Every reader handles both, and missing fields render
  as unknown (`null` in JSON output), never crash.
- `damaged`: ids of entries that ever received negative credit, used
  to distinguish `executed` from `starved` at burial.
- `settled_runs`: durable repository/run identities and evidence for bound
  outcomes. Missing historical records remain unknown. These records are not
  capped with lesson history, so history rotation cannot permit duplicate runs.

A file with no `ledger` key loads as a `Ledger` with fresh state
(tick zero, no tickets), so upgrading from plain `MemoryStore`
persistence just works.

## Atomicity and the write path

Every save writes a sibling temp file (`NAME.tmp`) and renames it
over the target (`os.replace`), so a crash mid-write can never leave
a truncated store; the previous snapshot survives. You may see the
`.tmp` file transiently; finding a stale one after a crash is
harmless and it will be overwritten by the next save.

## The lock sidecar (`NAME.lock`)

Persistence requires POSIX advisory locking on a local filesystem. CLI,
MCP, and dashboard mutations lock the complete load–modify–save operation.
MCP reloads on every call. Contending operations raise `StoreLockedError`;
retry the whole operation. Nested calls in one thread reuse the lock.
Direct Python writers also reject a save if the loaded file changed.
For Python operations, hold `store_lock(path)` across load, mutation, and save.
Do not share writable snapshots across machines or network filesystems.
Platforms without `fcntl` refuse persistence instead of writing without a lock.
The zero-length lock sidecar is never removed. A lock does not span a task's
query-to-settlement interval; the persisted ticket spans that interval.

## The event log (`NAME.events.jsonl`)

Optional, append-only JSONL: the full audit trail behind
`darwin-memo audit` and `memory_audit`. The Python `Ledger` writes it
only when constructed with `event_log=`; the CLI `ledger` and
`settle-ci` subcommands and the MCP server always write it, named by
replacing the store file's suffix (`lessons.json` writes
`lessons.events.jsonl` next to it).

Every record is one JSON object per line:

```json
{"event": "settle", "tick": 12, "ts": "2026-06-12T10:31:02+00:00", ...}
```

`event`, `tick`, and `ts` (UTC ISO-8601, second precision) are common
to all records; records written before timestamps existed lack `ts`
and fall outside any `--since` window. Per-kind payload fields:

| event | fields |
|---|---|
| `decide` | `ticket`, `query`, `silent`, `provenance` |
| `settle` | `ticket`, `delta`, `detail`, `source`, `applied` (list of `{entry, credit}`), `buried` (list of entry ids) |
| `settle_dropped` | `ticket`, `delta`, `detail` (the ticket was unknown, settled, or expired) |
| `settle_rejected` | `ticket`, `detail` (the delta was not finite; the value is deliberately not echoed, so the log stays valid JSON) |
| `add` | `entry`, `question`, `source`, `stake` |
| `import` | `entries`, `source`, `probation` (a probationary copy from another store) |
| `forget` | `entry` |
| `forget_refused` | `entry`, `reason` (escrowed or pinned) |
| `pin` | `entry` (exempted from starvation and merges) |
| `unpin` | `entry` (returned to normal selection pressure) |
| `graduate` | `entry` (a probationary import paid its last installment and may now decide) |
| `admission_denied` | `entry` (a juvenile decider took a negative measured outcome; its balance is zeroed) |
| `tick` | `population`, `deaths`, `merges`, `pending`, `expired`, `total_energy`, `dead_entries`, `upkeep_charged` |

`settle.source` identifies the reporting path: `ci`, `operator`, `agent`, or
`unknown`. Historical `measured` values are caller claims, not independently
verified observations. Missing source or evidence is unknown. Optional
`evidence` stores repository, task, base/head commits, run identity, evaluation
fingerprint, and report hashes. These fields are not cryptographic attestation.
`doctor` flags settlements without CI provenance. CI alone does not prove causation.
Pending tickets can carry an optional `binding`; old tickets remain readable.
Abandonment and expiry record `abandon` and `expired` events, respectively;
neither is an observed zero-improvement outcome or increments lesson usage.

`tick.upkeep_charged` is what makes the economics report exact rather
than estimated: `economics()` switches between the two on whether every
tick record in the window carries it.

Settle records from older versions lack `applied`; the audit digest
counts them under `untracked` rather than guessing. Audit readers
skip torn or corrupt lines: an audit must survive them.

### Rotation

The writer rotates logrotate-style: when the live file has reached
`event_log_max_bytes` (default 10 MiB) before an append, it shifts to
`NAME.events.jsonl.1`, existing rotated files bump one suffix up, and
the file beyond `event_log_keep` (default 3) falls off the end. One
file can overshoot the threshold by at most a single record. Readers
(`darwin-memo audit`, `memory_audit`) discover rotated files by
globbing numeric suffixes, highest (oldest) first, then the live
file, so any retention setting reads back in append order.

## The flaky-test sidecar (`flaky.json`)

Written only by `darwin-memo settle-ci` (junit mode), by default next
to the store. Per-test pass/fail observations, newest last, capped to
the sliding window:

```json
{"tests": {"tests.test_store::test_save_load": [true, true, false, true]}}
```

A test whose recent observations flip direction `--flip-threshold`
times (default 3) within the `--window` (default 10) is quarantined
out of settlement deltas until the flips slide out. A missing file is
empty history. Commit it alongside the store so quarantine survives
between CI runs.

## Compatibility policy (de facto)

There is **no `schema_version` field** in any of these files today.
What holds instead, and what the code actually guarantees:

- **Old files always load on new code.** Missing optional entry
  fields take dataclass defaults (except `id`: the loader keys
  entries by `d["id"]`, so an id-less entry is a `KeyError`, see the
  entry table above), missing config keys
  take constructor defaults, a missing `ledger` key means fresh
  ledger state, string history notes still render, settle events
  without `applied` count as untracked, records without `ts` are
  simply unwindowed. This is tested behavior, and the observability
  surfaces render missing data as unknown rather than crashing.
- **New fields are added as optional**, so files keep loading across
  upgrades without migration steps. `recorded_ts` is the live
  example: files written before it existed load with the empty string
  (rendered "age unknown") and gain real timestamps only on entries
  created after the upgrade. There has never been a migration tool
  because there has never needed to be one.
- **The reverse direction is weaker, and here is the honest edge:**
  unknown top-level and config keys are ignored on load, but entry
  objects and tickets are passed straight into their dataclass
  constructors, so a file written by a future version that adds a
  per-entry or per-ticket field would fail to load on today's code
  (`TypeError`). Downgrading across a field addition is therefore not
  supported: a store saved after the `recorded_ts` addition does not
  load on code from before it, and the same will hold for the next
  field.

Recommended forward policy, recorded here as future work and
deliberately not implemented in this docs change: add a
`schema_version` integer at the top level, filter entry and ticket
dicts to known fields on load (mirroring what `config` already does),
and state a one-version downgrade window. Until then, treat the
de-facto policy above as the contract.

## Scale, plainly

The whole store loads into memory and saves as one file; there is no
partial read, no index, and no compaction beyond consolidation. The
committed scaling measurements
([benchmarks: scaling](benchmarks.md#scaling-synthetic-corpus-median-of-repeats-apple-m4))
put the comfort zone at a few thousand entries: at 10,000 entries
retrieval is ~9 ms per query and a consolidation pass is ~1.1 s.
The graveyard only grows, by design (obituaries depend on it), and it
ships in the same file. If your store outgrows this shape, you want a
database and an index, which the zero-dependency core deliberately
does not provide.
