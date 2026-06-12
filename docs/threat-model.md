# Threat model

darwin-memo's headline claim is poisoning resistance: bad knowledge
dies because the outcomes it causes are measured, not graded. A claim
like that deserves a threat model that says exactly where the
mechanism helps, what it costs, and where it stops. This document is
specific to the code as shipped; when behavior and prose disagree, the
code and its tests win.

The short version: darwin-memo is a single-writer system. Everything
that can write to the store file, call `settle`, or append to the
event log is inside the trust boundary. Selection defends the
population against bad CONTENT arriving through trusted channels. It
does not defend against a bad CHANNEL.

## The trust boundary: who may call settle

`Ledger.settle(ticket_id, delta)` is the only way energy enters the
system, and it accepts a number from whoever holds a reference to the
ledger or can run the CLI against the store file. There is no
authentication, no signing, and no notion of identity anywhere in the
code: `settle` trusts its caller completely.

That makes the trust boundary operational, not cryptographic. In
practice the boundary is:

- the process that holds the store file open (your agent, the MCP
  server, a CI job),
- anything with write access to that file path (the advisory sidecar
  lock in `store.py` prevents accidental clobbering between honest
  processes; it stops nobody malicious),
- anything that can invoke `darwin-memo ledger FILE settle ...`.

Choose settlers the way you choose CI: the measured delta should come
from an instrument (bytes freed, tests passing, budget spent), and the
code path that reports it should be as reviewable as the code it
measures. The repo's own dogfood loop settles from CI results for
exactly this reason.

## Adversarial deltas: a malicious settler

A settler who lies is inside the trust boundary, and selection cannot
distinguish a lying instrument from a noisy one. Two properties bound
the damage rate but not the outcome:

- `tanh(delta / resource_scale)` caps any single settlement at
  `credit_gain` energy movement, so one absurd report cannot make an
  entry immortal or execute it instantly. A persistent liar just calls
  `settle` more than once.
- The benchmark flip suite (docs/benchmarks.md) measures this
  directly: under symmetric measurement lies the poison kill cycle
  climbs from median 0 to 3, and past the documented noise boundary
  selection stops working. That boundary is the honest statement of
  this attack's cost: a settler who controls enough settlements
  controls the population.

There is no mitigation inside darwin-memo by design. A judge that
second-guesses measurements would reintroduce exactly the reward-model
failure mode the project exists to avoid.

## Poisoned imports, and how probation bounds them

`darwin-memo import SRC DEST` copies another store's living entries.
A foreign store is an attractive poisoning channel: its entries arrive
with whatever text, sources, and energy balance the source chose, and
nothing about a JSON file proves who wrote it.

Probation (`--probation N`, default 3, `Ledger.import_entries` in
code) bounds what an import can do before local evidence exists:

- An imported entry CANNOT be the deciding entry of any ticket while
  `entry.probation > 0`. Local retrieval never elects it; in LLM mode,
  where citations arrive after the text exists, the protocol demotes
  a probationary citation to supporting at the citation parse site
  (`QueryProtocol`), so every consumer inherits the rule, and
  `Ledger.decide` re-checks as a backstop for protocol overrides.
  When every consulted entry is probationary the answer is withheld
  entirely, so imported knowledge alone never drives a decision and
  never earns from its own answer.
- Foreign balance does not transfer. Imports arrive at spawn energy
  (1.0) with zero uses, so a source cannot pre-fund its poison past
  the starvation horizon.
- While riding along, an import earns at most
  `credit_gain * supporting_share` per settlement (0.15 at defaults),
  whether a deciding entry was named or credit spread evenly over
  citations, and only when co-consulted with an entry that earned
  local trust.
- A probationary entry never consolidates. A merge would launder the
  lifecycle: the CONSOLIDATED heir starts with probation zero and the
  cluster's pooled energy, and the attacker controls the import's
  text, so near-duplicating a strong local entry would otherwise buy
  graduation for free. Juvenile entries are excluded for the same
  reason. Both merge like anyone else once they graduate.
- Graduation requires `probation` net-positive locally measured
  settlements. Negative settlements drain energy as usual but pay no
  installment. The Ledger's settle path and the survival loop's
  credit path advance the counter through the same rule
  (`advance_lifecycle`), so no consumer skips or strands probation.
- Import is idempotent on ids: an entry that died here stays dead
  through a re-import, so an attacker cannot resurrect executed poison
  by shipping the same store again.

What probation does NOT do: it does not read or sanitize the text.
A poisoned import that gives good advice on measured tasks will
graduate, and its text reaches model contexts as soon as it is
retrieved (see prompt injection below). Probation bounds credit
capture and decision authority, nothing else. And the deliberate cost:
a store of ONLY imports stays silent forever, because nothing eligible
can decide. Bootstrapping a fresh store from a source you fully trust
is the explicit `--probation 0` path.

## The price lesson: cold-start damage and admission gating

The benchmarks document the "lesson price" honestly: a freshly minted
wrong lesson decides real actions until its negative outcomes
accumulate, and the damage before its death is the price of learning
without a judge. The deterministic suite measures that price; the
random-eviction arm shows it 27x worse without outcome direction.

Admission gating (`SurvivalConfig.admission_window`, default 0, which
means OFF) bounds that price for entries written through `Ledger.add`:

- A new entry starts with `admission_window` juvenile settlements
  ahead of it (3 is the documented default when you enable it).
- While juvenile, a deciding entry earns and loses at
  `supporting_share` instead of full credit, so a lucky young lesson
  cannot bank energy faster than the incumbents it must outlive.
- One negative measured delta while the juvenile entry DECIDED denies
  admission outright: the balance zeroes and the regular settle sweep
  buries it. The price of a bad price lesson becomes one settlement's
  external damage instead of several.
- Riding along on someone else's bad decision drains energy without
  denying admission, and zero-delta settlements (abandons, expiry)
  move nothing.

Gating ships off by default because it changes settle arithmetic for
young entries and would silently alter every existing deployment and
benchmark number. The probation mechanism, by contrast, is always on,
because it only activates for entries that did not exist before this
feature.

## Prompt injection through lesson text

Lesson text is data to darwin-memo and instructions to whatever model
reads it. `query`, `render`, the MCP server, and the agent adapters
all place retrieved lesson text into model contexts. Anyone who can
get text into an entry (encode a document, import a store, call
`ledger add`, or socially engineer the agent into writing a lesson)
can attempt injection on every future context that retrieves it.

This is the agent-memory poisoning class that OWASP's LLM and agentic
security guidance describes: memory write today, instruction execution
tomorrow. Within that class, darwin-memo's mechanisms help only where
the payload's ADVICE is measurably bad: an injected lesson that causes
losing outcomes gets executed by selection like any other poison. An
injected lesson whose advice earns, or that never decides anything
while riding along, survives with its payload intact.

Treat the render boundary as the place to defend: sanitize or fence
retrieved text before it reaches a model that can act, and treat
`imported_from` and `sources` as display labels, never as a basis for
trusting text. Selection is an outcome filter, not a content filter.

## Pinning is a trust statement

`Ledger.pin` exists because the starvation cliff kills by design, and
some knowledge is rare but critical: the fire-extinguisher lesson that
pays off once a year must survive the wait. A pinned entry still pays
upkeep and still earns and loses on settlements, but its balance
floors at zero on both paths: it cannot starve, it cannot be buried
when a settlement drains it past zero (the settle sweep floors it
exactly as upkeep does), it cannot be merged away by consolidation,
and `forget` refuses it until unpinned.

The flip side is exactly as sharp: pinning opts an entry out of
selection's kill switch. A pinned poisoned entry is permanent until a
human notices. Pin sparingly, and audit pins with `darwin-memo top`
and `why`, which display pinned status for this reason.

## What darwin-memo explicitly does not defend against

- Multi-writer stores. One trusted writer per store file is the
  operating assumption; the sidecar lock is advisory and exists for
  honest concurrency, not security.
- Unauthenticated settle. Anyone inside the process or file boundary
  can mint outcomes. There is no signing and no audit beyond the
  append-only JSONL event log, which is itself plain text and
  tamperable by the same parties.
- Cryptographic provenance. `imported_from` and `imported_at` are
  labels written by the importing process. They support forensics,
  not verification.
- Content inspection. No mechanism reads lesson text for safety;
  selection only ever sees measured outcomes.
- In-process code execution in `TestSuiteEnv`, which runs generated
  Python by design. Do not point it at untrusted code (see
  SECURITY.md).
- Denial of service by a writer flooding the store with entries; the
  upkeep economy eventually starves them, but they exist until then.

Report vulnerabilities through the process in [SECURITY.md](../SECURITY.md).
