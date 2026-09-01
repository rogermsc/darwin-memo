# AGENTS.md / CLAUDE.md: the file nothing prunes

`AGENTS.md` is the cross-tool convention for what an agent should know about
a repository, and every major coding agent reads it or an equivalent
(`CLAUDE.md`, Cursor rules, OpenHands microagents). It has no schema, no
required fields, no expiry, no pruning, and **no signal that decides whether
an entry stays**. Files only grow. Nothing ever leaves.

That is not a small gap. Gloaguen et al. measured what the convention costs:
across four models and two task sets, context files raised inference cost by
over 20% on average *without generally improving task success*, and
repository overviews — the section every provider's init prompt recommends —
did not help ([arXiv:2602.11988](https://arxiv.org/abs/2602.11988)). Read it
carefully before quoting it: the comparison is against *no context file*, and
developer-written files did beat model-written ones. The finding is not "written
memory is worthless". It is that **memory nobody prunes is priced and unproven**.

darwin-memo is the pruning half. Lessons live in a store, earn from measured
CI outcomes, starve when nothing consults them, and get executed when they
cause damage. `darwin-memo render` then projects the survivors into the file
your agent already reads.

## The loop

```bash
# 1. The agent works. It opens a PR whose body carries a ticket id.
darwin-memo ledger .darwin-memo/lessons.json decide "is this patch safe to ship?"

# 2. CI settles that ticket with a measured delta, not an opinion.
darwin-memo settle-ci .darwin-memo/lessons.json \
  --base-xml base.xml --head-xml head.xml

# 3. Project the survivors into the file the agent reads next session.
darwin-memo render .darwin-memo/lessons.json -o AGENTS.md --budget 25kb
```

Step 3 is the only new thing here; steps 1 and 2 are the
[CI lesson store](ci-lesson-store.md), which is the same guide with a
different output file. `--split-dir` writes an index plus topic files if your
agent prefers that shape, and `--budget` is a hard byte ceiling, so the file
cannot silently grow past what a model will actually read.

Wire step 3 into the same workflow that settles:

```yaml
- name: Project the store into AGENTS.md
  run: |
    darwin-memo render .darwin-memo/lessons.json -o AGENTS.md --budget 25kb
    git add AGENTS.md && git diff --cached --quiet || \
      git commit -m "memory: re-render AGENTS.md"
```

## Read what you are about to ship

This repository's own store is the worked example, and it currently contains
a lesson that is **false**:

> *Should bench result JSON files be committed?*
> "No. `bench/results` is regenerated, not committed."

`bench/results` holds 132 committed files and the entire reproduction
architecture depends on that. The entry is still alive at balance 1.05, and
the mechanism is behaving exactly as documented: an entry only dies by
starving or by being executed for damage, and this one advises nothing CI
ever acts on, so nothing has ever charged it. It is inert, and inert entries
can only starve.

Two things follow, and both are the point of this page rather than caveats to
it. First, `render` is a projection, not an audit: check the diff the way you
would check any generated file entering your prompt. Second, if a lesson is
wrong and nothing will ever execute it, say so directly —
`darwin-memo ledger STORE forget <id>` — because selection cannot reach what
selection never touches.

## What this does not do

It does not read `AGENTS.md` back. The file is an output; the store is the
source of truth, and hand-edits to the rendered file are lost on the next
render. If you want to keep hand-written guidance, keep it in a separate file
your agent also reads, or add it to the store with
`darwin-memo ledger STORE add` so it pays upkeep like everything else.

It also does not decide anything about your repository on its own. The
settlement signal is whatever your CI measures; if that measurement is a
model scoring an answer, this package is the wrong tool, by design.
