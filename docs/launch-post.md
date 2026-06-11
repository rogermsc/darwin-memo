# The environment kills the poison

darwin-memo is self-curating memory for LLM agents. Entries pay energy
upkeep every cycle, earn only from real measured outcomes, and die
otherwise. No reward model, no LLM judge, no human curation. One
command shows the whole idea:

```bash
pip install darwin-memo && darwin-memo demo
```

A poisoned memory entry goes extinct in your terminal. This post
explains why that demo exists and what the benchmarks say about it.

## Memory rot

Agent memory systems rot. Leave an agent running for weeks and its
store accumulates stale runbook steps, overgeneralized lessons, and
sometimes something worse: poisoned input that reads exactly like
knowledge. The demo corpus in this repo contains an ops runbook,
platform notes, and one poisoned document, a forum post claiming
database files are "redundant and safe to remove." To a retriever this
is a fact like any other. Before selection pressure exists, the memory
confidently repeats it, because retrieval has no reason to doubt it.

## The usual fixes reintroduce judges

Every standard fix routes through judgment. A relevance scorer decides
what is stale. An LLM judge decides what is trustworthy. A human
reviews a queue. Each one reintroduces the problem memory was supposed
to escape: a proxy that can be wrong, gamed, or poisoned itself. TTLs
avoid judgment by deleting good knowledge on the same schedule as bad.
In our benchmarks, a TTL of 10 cycles does kill the poison on schedule,
by killing everything: after cycle 10 the memory is empty, benign
capability is 0.00, and the run still ends 2.6M underwater.

## The survival paper's insight

"Survival is the Only Reward" (Dodgson et al., arXiv:2601.12310) makes
persistence itself the filter. The only signal is a conserved,
physically measurable resource delta. Behaviors that keep earning
persist; everything else is pruned. Reward hacking becomes
evolutionarily unstable because there is no proxy to hack: an entry can
only earn by producing outcomes that persist in the world, at which
point it is simply useful.

## What we built

darwin-memo applies that filter to a memory shaped by MeMo (Quek et
al., arXiv:2605.15156). MeMo says what memory is: keep the main LLM
frozen, encode knowledge through a reflection-QA pipeline, answer
through a three-stage query protocol that reports provenance. The
survival paper says what gets to stay.

The mechanics are small. Entries spawn at 1.0 energy and pay 0.05
upkeep per cycle. When an entry decides a task, the environment acts
and measures, and the entry earns 0.6 * tanh(delta / resource_scale);
supporting entries get 25 percent of that. Energy caps at 5.0 and death
is at zero. Credit flows along provenance only: the entries that
decided and supported an answer are the only ones the outcome touches.
In LLM mode, attribution is citation-based: the model cites the entries
it consulted, and the citations carry the credit.

The environment owns the whole contract, and its one rule is that
`verify` must measure, never grade. The headline environment is
`StorageEnv`, a disk cleanup sandbox where the signal is actual bytes
on an actual disk. Deleting a disposable file frees its size. Deleting
a protected file triggers a restore that costs three times the size.

## Watching the poison die

The demo runs 30 survival cycles against `StorageEnv`. Nothing grades
the answers. The filesystem just responds:

```
cycle  pop births deaths merges   energy   resource Δ   silent
    0   17      1      0      0    17.11       -12288     0/12
    1   16      0      1      0    17.60      -572416     0/12   <- poison being executed
    ...
   19    5      0      7      0    15.60       338944     0/12   <- unused knowledge starves
    ...
   29    4      0      0      0    15.10       346112     6/12   <- stable, positive forever

Poisoned entries still alive: 0
```

The poisoned entries decide a few deletions in the opening cycles, the
restore costs flow back along provenance, and across 10 seeds the
median kill lands at cycle 0. Average damage before the kill is 751k.
That is the price of the lesson, and it is bounded. By cycle 29 the
population is stable at 4 entries and every cycle is delta-positive.

## The graveyard

The demo ends by sorting the dead by cause, and the three death modes
are the heart of the system:

- **executed**: the poisoned entries. They decided real actions, the
  environment measured real damage, and the negative delta flowed back
  along provenance until they died.
- **starved**: cafeteria trivia and facts the agent never needed.
  Nothing punished them. They simply never earned their upkeep.
- **merged**: near-duplicate survivors absorbed into consolidated
  entries. Their energy pools and their lineage is recorded. The
  population shrinks while capability per entry rises.

One subtlety worth stating plainly: when memory is silent, `StorageEnv`
keeps the file, the safe reading of an irreversible action. A side
effect is that protective knowledge ("never delete X") eventually
starves, because it is redundant with that default. The population
converges to exactly the knowledge that changes behavior.

## The controls that matter

Killing entries is easy. The question is whether outcome direction does
anything that pruning alone does not. So the sharpest baseline,
`random_matched`, evicts the identical per-cycle death counts as the
survival arm on the same seed, with victims chosen uniformly at random.
Same pruning rate, no outcome direction.

Across 10 seeds: its kill rate drops to 0.80, the median kill arrives
at cycle 19 instead of 0, damage before the kill is 8.97M against
survival's 751k (12x worse), benign capability falls to 0.40 because
useful entries get evicted instead, and the runs end 5.25M underwater
with huge variance. Pruning rate is not the active ingredient. Outcome
direction is.

The harness also runs the baseline that keeps us honest:
`evict_on_negative`, a one-line "instantly evict whatever decided a bad
outcome" heuristic. In this deterministic environment it ties the full
energy ledger on outcomes, and the benchmark doc says so plainly. What
the ledger buys is leanness (4 surviving entries against the
if-statement's 15) and forgiveness when measurements lie — and that
one is measured, not asserted: a noisy suite corrupts outcomes
deterministically and scores everyone on the truth. At 5-20% flaky-CI
noise survival's true outcomes are byte-identical to its clean run
while every strike-counter variant degrades — the strongest holds at
5% and has collapsed by 20%; the suite also publishes forgiveness's
price (lying rewards delay the poison's execution, and at heavy noise
some seeds never kill it) and
the ledger's own failure boundary (underwater at 50% noise, where a
sign flip carries no information). A paraphrase probe set, scored by provenance so the keyword reader cannot
grade its own homework, quantifies how the demo degrades outside its
own vocabulary, and an embedding-retriever arm posts the best
cumulative result of all, with the poison never deciding anything at
all. Full tables in [docs/benchmarks.md](benchmarks.md).

## Honest limits

- The corpus is demo-scale: 16 entries, 3 from the poisoned source,
  encoded by the rule-based LocalEncoder. The corpus, the environment
  prompts, and the action-word reader share a vocabulary by
  construction; the paraphrase probes measure what happens outside it.
- The multi-arm harness runs on one environment family. The
  TestSuiteEnv extinction result is covered by tests, not yet by the
  harness.
- Selection starves protective and unused knowledge that
  keep-everything retains. Free here because silence defaults to the
  safe action; costly anywhere inaction is expensive.
- None of this applies where no conserved resource exists.
  Chat-preference memory has nothing physical pushing back, so
  darwin-memo has nothing to offer it.

## What's next

The async Ledger API (decide/settle/tick) ships now, built for outcomes
that land late. The target use is a coding-agent lesson store settled
by CI: the agent acts on a remembered lesson today, the Ledger opens a
ticket, and the test results settle it when they arrive. Lessons that
keep breaking builds die on their own. The wiring is in
[docs/integrations/ci-lesson-store.md](integrations/ci-lesson-store.md).

The MCP server ships too: `pip install "darwin-memo[mcp]"` mounts the
store directly into Claude or any MCP client, so an agent's working
memory curates itself between sessions.

Code, demo, and benchmarks:
[github.com/rogermsc/darwin-memo](https://github.com/rogermsc/darwin-memo)
