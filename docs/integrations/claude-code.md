# Claude Code

Claude Code keeps per-project auto memory in a `MEMORY.md` it loads at
session start, and it loads only the first 200 lines / 25KB of that
file. Anything past the cutoff exists but is never read unless the
agent follows a link to a topic file in the same directory. That
ceiling is exactly the shape darwin-memo's selection produces: a small
population of entries that have earned their place, ranked by balance.
`darwin-memo render` projects a store into that file format.

## Usage

```bash
# Single file: top-balance survivors, hard-capped at 25KB (the default)
darwin-memo render .darwin-memo/lessons.json -o MEMORY.md --budget 25kb

# Split: MEMORY.md becomes a one-line-per-topic index, one file per
# kind written into the directory, each under a proportional share
darwin-memo render .darwin-memo/lessons.json -o MEMORY.md --split-dir memory
```

`--budget` accepts `25kb`, `25KB`, or a bare byte count like `8000`
(kb and mb are 1024-based). The output never exceeds the budget: entries
are packed greedily in balance order against the fully rendered
document, so the header, group headings, and counts are all charged to
the cap. The same admission also charges a hard line cap (`--max-lines`,
default 200), because Claude Code stops reading at whichever ceiling it
hits first; the shown count never includes an entry past either one.
Ties in balance break on entry id and nothing reads a clock, so the
same store renders byte-identically every time.

Each entry is one tight block: the lesson text plus a one-line
provenance annotation (id prefix, balance, last settle tick), grouped
by kind, with the strongest group first. The highest-balance entry is
always the first block in the file, and the file never exceeds the 200
lines Claude Code actually reads, so everything the header counts is
content the host loads.

## Where MEMORY.md lives

Claude Code's auto memory directory is per project:

```
~/.claude/projects/<project-slug>/memory/MEMORY.md
```

Render straight into it, with the topic files alongside:

```bash
darwin-memo render .darwin-memo/lessons.json \
  -o ~/.claude/projects/<project-slug>/memory/MEMORY.md \
  --split-dir ~/.claude/projects/<project-slug>/memory
```

A missing store or a store with zero living entries renders a minimal
honest file saying so, and a re-render deletes topic files for kinds
with nothing left to show, so dead lessons never linger in the memory
directory. An unreadable store (empty, truncated, locked, or not a
store payload) exits with a one-line error and leaves the previous
render untouched. Either way there is never a traceback, so the command
is safe to run from hooks and cron jobs unconditionally.

## Why a budget instead of a summary

The budget is a token SLO. Claude Code will read at most 25KB of
memory per session, so the question is never "how do we fit everything"
but "which 25KB earns its place". darwin-memo already answers that
continuously: every entry pays upkeep each tick and earns balance only
from measured outcomes, so weak memories starve and die long before
rendering happens. render is a projection of that selection, never a
summarizer. There is no compression step, no model call, and no judge
deciding what matters; the energy ledger decided already, and the
greedy packer just cuts the ranked list where the bytes run out. Active
memory therefore never exceeds the budget, and what is in the budget is
exactly what has survived contact with real outcomes.

This is the same framing as the other hosts (see
[openclaw.md](openclaw.md)): darwin-memo owns selection, the host owns
the reading surface.

## Coming next

A full Claude Code plugin with lifecycle hooks is planned: decide at
session start (ticket opened), settle from the session's measured
outcome, tick on a daily cadence, and re-render MEMORY.md after every
settle. Until then, the loop is the `ledger` CLI plus a render call,
the same shape this repo dogfoods in
[ci-lesson-store.md](ci-lesson-store.md).
