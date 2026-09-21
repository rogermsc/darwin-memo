# Glossary

Terms this project invents or overloads, in the words a newcomer needs
rather than the words the code uses. Where two names mean one thing, that
is said plainly.

## The economics

**Energy** — the survival currency. Every entry holds a balance, pays
upkeep from it every tick, and can only add to it by being cited in a
decision whose outcome was measured. At zero the entry is buried. It is
dimensionless: energy is *not* comparable with the resource you measure.

**Balance** — the same number as energy, under the name the observability
layer and the dashboard use (`darwin-memo top`, the `balance` column,
`entry_life`). The core calls it `entry.energy`; if a doc says balance and
the code says energy, they are the one field.

**Upkeep** — energy charged to every living entry on every tick, `0.05` by
default. It is what makes memory cost something and therefore what makes
"stops earning" mean "goes away".

**Spawn energy** — what a new entry starts with, `1.0`. Also called the
**stake** in birth events and in `why` output. Three names, one number.

**Max energy** — the ceiling a balance can reach, `5.0` by default. It is
why nothing becomes immortal by having one very good day.

**Runway** / **ticks to starvation** — how many more ticks an entry's
current balance buys at the flat upkeep rate. `MemoryStore.ticks_to_starvation`.

**Starvation horizon** — the same idea at population scale: how long the
store as a whole can go without earning. Some docs say **starvation
cliff** for the moment it arrives.

**Credit** — energy moved to an entry by a settlement,
`credit_gain * tanh(delta / resource_scale)`. The deciding entry takes it
in full; supporting entries take `supporting_share` of it.

## The clock and the three moments

**Tick** — one round of upkeep. It is *not* a wall clock: it advances only
when you or a script call `tick()`, so "4 ticks to starvation" means four
more rounds, however long those take.

**Cycle** — the same clock, in batch (`SurvivalLoop`) shape. Fields named
`born_cycle` and `last_used_cycle` render to users as "born tick" and
"last settled tick"; the two words are one concept.

**Decide** — memory answers a question and opens a ticket carrying the
provenance of that answer.

**Settle** — the outcome is known, so credit flows along the ticket's
provenance. `delta` is a reported observable outcome, never a
grade.

**Abandon** — you did not act on the answer, so there is no outcome to
measure. The ticket closes at delta zero and releases its escrow.

**Escrow** — an entry named by any unsettled ticket keeps paying upkeep
but cannot be buried or merged. It is what stops a verdict arriving after
the execution.

**Ledger** — three different things, so read the context:
1. the `Ledger` class, the event-driven API (decide / settle / tick);
2. the energy ledger inside `MemoryStore`, meaning the balance arithmetic;
3. "the ledger" in benchmark prose, meaning the whole selection mechanism.

## Death, and its causes

**Graveyard** — buried entries. It only grows, so a dead entry stays
inspectable.

**Executed** — the environment measured real damage from a decision this
entry made, and the negative delta killed it. Distinct from merely having
been dented once: an entry is executed when it dies on the cycle it was
charged.

**Starved** — nothing ever punished it. It simply never earned back the
upkeep it paid. The healthy death mode for trivia nobody needed.

**Merged** — absorbed into a consolidated near-duplicate. Its energy
pooled and its lineage is recorded, so it is gone without being lost.

**Forgotten** — buried on request, without waiting for selection. For
advice that is wrong but inert, which selection cannot reach because
nothing acts on it.

## Curation and trust

**Consolidation** — merging near-duplicate survivors above
`merge_threshold` into one entry that carries their pooled energy and
lineage.

**Negative-Space Learning** — the name the MeMo line of work gives to that
merge step: what the population learns by removing redundancy rather than
by adding. The mechanism is `darwin_memo.consolidate`.

**Laundering** (or **consolidation laundering**) — the attack where a
poisoned entry survives by merging into a healthy one, inheriting its
standing. `merge_source_policy` is the lever that requires provenance
agreement on top of similarity.

**Pinned** — exempt from starvation and merges. A pin is a standing claim
that an entry is correct regardless of what it earns, so it suspends the
only mechanism that removes bad memory.

**Probation** — net-positive settlements a foreign entry owes before it
may decide locally. Set by `import`; a probationary entry can still be
cited as support and earns at the supporting share.

**Graduated** — a probationary entry paid its last installment and may now
decide.

**Juvenile** / **admission window** — the same gate for locally written
entries: a new entry owes `admission_window` settlements before it decides
at full weight, and one negative outcome while deciding denies admission
outright. Off by default.

**Damaged** — an entry that has ever taken negative credit. Recorded in
the ledger file so an obituary can say what happened.

## Diagnosis and audit

**Doctor** — `darwin-memo doctor`, which names which of eight degeneracies
a store hit rather than leaving them all looking like "nothing is
working". An empty result means either healthy or *nothing measured yet*,
and the output says which.

**Silence** — memory declining to answer because nothing cleared the
relevance floor (`min_coverage`). A feature: silence is better than a
confident wrong answer, and the silence rate is the best degeneracy
signal there is.

**Operator-entered** — a settle whose delta a person typed, rather than
one a measurement produced. Possible from the dashboard, recorded as
`source: "operator"` everywhere it appears, and flagged by `doctor` once
such settlements outweigh measured ones. The distinction exists because a
source label describes the reporting path; neither operator input nor a
legacy measured label establishes independent verification.

**Event log** — the JSONL sidecar next to the store, rotated at 10 MB. The
audit trail behind `audit` and the dashboard.

**Evidence window** — how much the diagnosis had to work with: events,
ticks, settlements, living entries and graves. It is what separates "clean"
from "no data".

## Things that are not terms of art here

**Rent tiers**, **aligned / inverted / uniform** — benchmark concepts from
`bench/`, describing how a synthetic environment prices inaction. They do
not appear in a normal deployment.

**Potentiation** — the organic layer's optional slowing of upkeep for
entries with earned importance. Experimental, opt-in, Python-only, and its
own benchmark says usage is a weaker retention signal than survival. See
[organic.md](organic.md).
