# Memory security is the publishable regime: outcome-grounded revocation

**Date:** 2026-08-01. Sources: 9 primary arXiv papers (2604.16548, 2606.04329,
2607.27080, 2606.30566, 2606.12703, 2605.03228, 2605.08442, 2601.05504,
2410.02644) + OWASP Agentic Top-10 2026. Supersedes the direction question left
open by [2026-06-30-self-improvement-landscape.md](2026-06-30-self-improvement-landscape.md).
**Re-pull before claiming a first: this subfield is publishing weekly.**

## What changed in the four weeks since the last landscape note

Agent-memory *security* went from scattered attacks to a named, benchmarked
subfield with a standards hook:

- **OWASP added Memory & Context Poisoning as ASI06** in the 2026 Agentic AI
  Top 10. Its five prescribed layers: input moderation, memory sanitization
  *with provenance*, trust-aware retrieval, behavioural monitoring, **forensic
  capability**.
- **MemSecBench** (2607.27080, ~1 week old) is now the lifecycle benchmark of
  record: 310 cases, 48 contexts, a **Write–Execute–Forget** protocol with seven
  checkpoints, run over a 24-config matrix — **harnesses OpenClaw + Hermes** ×
  backends **Native / Mem0 / Mem0-Graph / A-MEM** × 3 LLM backends.
- **MPBench** (2606.04329): 3,240 attacks / 2,997 benign, six attack classes
  split into *strong-signal* and *weak-signal*.
- Defences arrived, all of them content-based: PromptArmor/PIGuard/CommandSans/
  DataFilter (write-time filters), MAGE shadow memory (2605.03228), SMSR
  certified runtime blocking (2606.12703), Forensic Trajectory Signatures
  (2606.30566), non-malleable origin-bound authority (2606.24322).

## The gap, stated as numbers

| Evidence | Number | Reading |
|---|---|---|
| MPBench, weak-signal vs strong-signal, per off-the-shelf detector | PromptArmor **42.50%** (vs 84.44%); CommandSans 28.34% (68.33%); PIGuard 18.34% (51.67%); DataFilter 10.74% (28.86%) — a **18–42 point** drop for every detector | Content detection fails exactly where the payload is written to look benign |
| MemSecBench F1 Repair | 86.3% | Removing poison is largely solved |
| MemSecBench **F2 Benign Preservation** | **62.5% — a 30.2-point gap** | Repair is *collateral*: fixing memory destroys good memory |
| MemSecBench SRSR (selective repair) | 56.1% | The Forget stage is the open bottleneck |
| Forensic Trajectory Signatures | AUC 0.99 detect, **P(FP \| signature)=100%** on ground-then-act models; **does not revoke** | Detection ≠ remediation |
| SMSR | blocks at retrieval | Does **not** remove already-persisted poison |
| Survey 2604.16548 defence taxonomy | detection classifiers, similarity filters, LLM verification | **No defence in the taxonomy uses measured environment outcomes to revoke** |

So: everyone defends at **write** (does this text look malicious?) and at
**retrieval** (should this be injected?). Nobody defends at **consequence**.
And the one stage the benchmark says is broken — selective repair without
collateral loss — is the stage a provenance-scoped energy ledger does natively,
because credit flows to *the entry that decided*, not to a semantic
neighbourhood.

## Why this specific pivot, and why it rescues the June NO-GOs

Three pre-gates in June killed the "better estimator" story: the ledger is
matched-or-beaten by threshold-k under i.i.d. noise, by a buffer frontier, and
by a tuned EWMA count under drift. The commit was blunt: *no generalizable
algorithmic edge over simple counting in estimation settings; the only
demonstrated edge is adversarial poison-removal where entries ACT.*

That NO-GO is not a dead end — **it is the scoping result that points here.**
This pivot claims exactly and only what survived: an adversarial, acting-memory
regime. Nothing in the flaky-selection sweeps contradicts it, and the paper gets
to cite its own negative results as the reason for the narrow claim, which is
the most defensible shape a preprint can have.

## The paper

**Title (working):** *Poison Dies of Its Own Consequences: Outcome-Grounded,
Judge-Free Revocation of Poisoned Agent Memory*

**Claim.** Content is the wrong observable for weak-signal and dormant memory
poisoning; consequence is the right one. A memory entry that pays upkeep and is
settled only by a conserved, measured resource delta along its provenance
extinguishes actionable poison without a classifier, a judge, or a label — and,
because settlement is provenance-scoped rather than similarity-scoped, it does
so without the collateral benign loss that defines MemSecBench's Forget
bottleneck.

**Three contributions:**

1. **A new defence class** — post-hoc, outcome-grounded, detection-free
   revocation. Slots into OWASP ASI06 layers 2 and 5 (sanitisation *with
   provenance*, forensics: `obituary()` is a machine-readable answer to "why did
   this memory die?").
2. **A new threat model the field has not defined: curation-targeted attacks.**
   Every proposed defence is itself an attack surface. If a defence deletes on
   negative evidence, an adversary who can induce false-bad signals can
   **starve the defender's benign memory** — a denial-of-memory attack.
   darwin-memo already has the measured answer (one-sided-noise suite: byte-
   identical true outcomes at 5% lying measurement where every strike counter
   collapses; published failure boundary at ~1 lie in 3). Formalising
   *attacks on the curator* is the most novel thing in this plan and nobody
   owns it yet.
3. **The regime map, on real tasks** — where consequence-grounded revocation
   wins, ties a one-line heuristic, and loses (dormant poison that never acts;
   harm with no conserved measurement).

**What makes it credible rather than another mechanism paper:** it reports where
it loses, it runs the literature's own controls on its own harness, every number
is seed-level with permutation tests and a CI-validated manifest, and it now has
a real-benchmark leg instead of two synthetic environment families.

## The experiment

Three tiers. Ship tier 1 alone if budget bites; tier 2 is what makes it a paper.

**Tier 1 — Selective repair on the standard protocol (the headline).**
Reimplement the MemSecBench Write–Execute–Forget checkpoints (W1,W2,E1,E2,E3,
F1,F2) against OpenClaw + Hermes, both of which already have shipped
darwin-memo integrations. Backends compared: Native, Mem0, A-MEM (the paper's
own set) + darwin-memo as the fifth. Attack split from MPBench's taxonomy:
strong-signal vs **weak-signal** (the split where filters collapse) + dormant/
context-triggered.
*Primary metric:* SRSR **and** F2 Benign Preservation, reported jointly — the
30.2-point gap is the thing being closed. *Pre-registered hypothesis:* the
ledger loses on F1 speed against a write-time filter for strong-signal attacks,
and wins on the weak-signal/dormant split and on F2 everywhere.

**Tier 2 — Curation-targeted adversary (the novelty). DONE 2026-08-01.**
Shipped as `bench/adversary.py` + `--suite adversary`, 30 seeds, results
committed and manifest-bound. Headline: at one corrupted measurement per cycle
the ledger keeps benign capability 1.00 and 99.4% of its unattacked outcome
while absorbing 30 fired lies; every strike counter and quarantine loses all
benign capability, `evict_on_negative` k=1 after **three** lies. 30/30 seeds,
Holm p = 0.0015. The ledger's own boundary is between 2 and 4 lies/cycle, and
past it the only arms retaining capability are the ones that never delete (and
never kill poison). Full tables in `docs/benchmarks.md`, write-up in
`paper/sections/experiments.tex` §Curation-targeted attack.
**This is the answer to June's "no edge over EWMA": the edge is not estimation
quality, it is adversarial robustness of the curator.**

Original plan, for the record:
An adaptive attacker that does not inject poison at all: it induces false-bad
settlements to evict the defender's benign lessons (denial-of-memory), and
false-good settlements to keep its own alive. Arms: darwin-memo ledger,
`evict_on_negative` (the one-liner that ties in the deterministic case — it
should shatter here), strike-k, quarantine, Thompson bandit. This is where the
tanh-bounded buffer with earn-back stops being ornamental, and it is the
experiment that answers June's "no edge over EWMA" honestly: **the edge is not
estimation quality, it is adversarial robustness of the curator.**

**Tier 3 — Real software-engineering harm.**
Reuse `bench/swebench_cl/` as-is: it already mints lessons, retrieves over real
repos, executes real tests, and ships `poison.py` (authority-misdirection
lessons that defend buggy code). Arms already exist: `memory_on`,
`memory_off`, `random_matched`, `keep_everything`, `evict_on_negative`.
*Metric:* resolve-rate learning curve with and without poison, plus
time-to-extinction and **harm integral** (cumulative failed tasks before
revocation). This converts the outstanding SWE-Bench-CL TODO in the draft into
the security paper's real-task leg — one run serves both.

**A metric contribution worth stating on its own:** ASR/RSR are one-shot metrics
borrowed from prompt injection, and they are wrong for persistent memory. For a
memory that lives for months the honest quantities are **time-to-extinction**
and the **harm integral** before revocation. A defence with ASR 100% and
extinction at cycle 1 beats a defence with ASR 40% and a survivor that acts
forever. Say that plainly; it reframes the whole comparison in the paper's
favour without overclaiming.

## Build list (what exists vs what is new)

Exists and reusable: energy ledger + provenance credit, `Ledger` decide/settle/
tick with escrow, `obituary()`, MCP server, OpenClaw memory-slot plugin, Hermes
integration, `bench/swebench_cl/` executor + `poison.py` + arms, the noisy suite
(one-sided/symmetric lying measurement), permutation tests + manifest CI.

New, and it is a short list:
1. `bench/memsec/` — the W/E/F checkpoint harness + attack corpus in the six
   MPBench classes (build it against our own harness; assume MemSecBench code
   is not released and do not block on it).
2. Backend adapters so Mem0 / A-MEM / native run as arms in the same harness.
3. The curation-targeted adversary (tier 2) — a settlement-corrupting
   environment wrapper; the noisy suite is 80% of it already.
4. `harm_integral` + `time_to_extinction` metrics in the report module.

## Risks and kill criteria

- **MemSecBench code may not be released.** Mitigation: implement the protocol,
  cite it as the protocol source, do not claim their numbers. Fallback substrate
  if reimplementation stalls: **ASB is released** (github.com/agiresearch/ASB,
  memory-poisoning attack + 11 defences + 13 backbones).
- **Someone publishes outcome-grounded revocation first.** Non-trivial risk at
  this cadence. Mitigation: tier 2 (curation-targeted attacks) is the harder
  thing to scoop, so lead with the threat model, not the mechanism.
- **Kill criterion, pre-registered:** if darwin-memo does not beat the 62.5% F2
  benign-preservation baseline on the weak-signal split, the defence claim is
  dead and the paper reverts to the regime map with a negative security result.
  Say so in the pre-registration.
- **Frontier-model spend.** Keep the matrix small: 1 harness (OpenClaw) × 3
  backends × 1 local + 1 frontier LLM, ≥5 seeds. Local Ollama carries tiers 2–3.

## The product this justifies

Not a competitor to Mem0/Zep/Letta — a **sidecar under** them: an outcome-
grounded revocation layer that any memory backend can mount, which is the one
ASI06 layer none of them ship (mem0 has an open feature request for exactly this,
mem0ai/mem0#5331). Positioning stays consistent with the README's scoping rule:
we do not do chat-preference memory; we make whatever memory you already have
*die correctly when it causes harm*, with a forensic trail.
