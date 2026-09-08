# Submission notes

Working notes for placing *Attacking the Curator*. Everything here is from a
direct-fetch research pass over primary sources (arXiv abstract pages, venue
CFPs); the venue **dates are time-sensitive and must be re-checked** before
acting, and one target (USENIX/S&P) did not fetch and is unconfirmed.

## The novelty cell (for related work and the rebuttal)

Every prior selection/eviction mechanism sits in a different cell than ours,
confirmed against the primary sources:

| system | eviction / retention signal | judge? |
|---|---|---|
| Voyager | append-only, never evicts | GPT-4 critic admits skills |
| Reflexion | recency window Ω=1–3 (context limit) | LLM writes the content |
| Generative Agents | recency + importance + relevance, retrieval only, no delete | LLM assigns importance |
| A-MEM | LLM-decided links, LLM rewrites neighbours | LLM throughout |
| MemGPT | token-budget FIFO paging (not destruction) | LLM chooses what to save |
| Titans | learned "surprise" gradient gate | internal loss, not environment |
| DGM / AlphaEvolve | selects *agents/programs*, not memory | benchmark / evaluator score |
| Forget to Improve (2606.25115) | **conserved byte/energy budget** — nearest | value-minus-harm-per-byte **score** |

The unclaimed cell — and the one sentence the paper defends — is: entries
evicted under a conserved resource whose value is settled **only** by a
measured environment outcome, with **no** judge, learned score, or recency
heuristic. "Forget to Improve" is the blocking citation (conserved but scored);
it is now in `related.tex`. Cite MemGPT, Titans, and Generative Agents as the
budget-but-paged, learned-forgetting, and importance-scored neighbours (already
present).

## Venue shortlist (re-verify dates)

1. **NeurIPS "Evaluations & Datasets"** (renamed for 2026;
   neurips.cc/Conferences/2026/CallForEvaluationsDatasets) — **strongest fit.**
   Explicitly solicits benchmarking tools, RL environments, red-teaming, and
   "failure modes of existing benchmarks or evaluation practices." The
   harness-plus-attack framing is its remit, and it welcomes evaluation-as-
   contribution, which suits the honest-negative-results posture.
2. **IEEE SaTML** — good under the *attack* framing ("Novel attacks on ML",
   "ML system security"); its CFP is silent on negative results and synthetic
   environments, neither for nor against.
3. **CCS 2027 / NDSS 2028** — strong ML-security scope (dedicated tracks) but
   every 2026 deadline has passed; nearest CCS abstract lands ~Jan 2027.
4. **MLSys** — plausible, secondary.
5. **USENIX Security / IEEE S&P** — unconfirmed (fetch failed); check the cycle.

## Literature signal (for PaperClaimEnv, if it graduates into the paper)

"Verify a paper's own numbers against its own released data" is not an
established named task. Closest: SciFact (claim vs abstract), TabFact
(statement vs Wikipedia table), SEM-TAB-FACTS (generated statement vs
scientific table). PaperQA2 detects contradictions but settles them with human
experts (~30% false positive). So `PaperClaimEnv`'s signal is a novel task
framing, not a hedge — positioned that way in its module docstring.

## Body length: DONE. The venue body is 13 pages.

`tools/body-pages.sh [LIMIT]` measures it and CI runs it at 13.

| build | command | what it is |
|---|---|---|
| preprint | `tectonic paper/main.tex` | 11pt single-column A4; every block typeset where it is written, appendix after it |
| venue | `tectonic paper/body.tex` | 10pt two-column letter; supporting blocks moved into the appendix. **Body 13 pages**, appendix from p14 |

**Two things had to change, and only one of them was prose.**

The first was the measurement. A 13-page security-venue limit is written
against a two-column 10pt layout; the preprint is 11pt single-column A4,
which fits roughly half as much per page. Measuring one against the other
is what made a 13-page target look 26 pages away. `body.tex` swaps the
class and geometry block, exactly as `main.tex`'s opening comment always
said a venue build would, and nothing else differs.

The second was placement. Roughly a third of the body moved into the
appendix -- neighbouring literature, the remaining regime axes, the
SWE-Bench-CL protocol and both matrices, the Mem0 analysis, the strike
counter's two shapes, the persistence provenance counts, the CI
channel's three writers, the reporting-rule definitions, the disclosure
exchange, and thirteen further threats to validity. **Nothing was
deleted.** Each block lives in `paper/sections/detail/` and is typeset
exactly once per build: in place in the preprint, in the appendix in the
venue build. `\pointer{...}` carries the sentence that names where a
block went and appears only in the build where it moved.

`tests/test_paper_deferred_blocks.py` holds that invariant, because the
failure mode is silence -- drop the appendix line and the venue PDF still
compiles, still looks finished, and is missing a page of threats to
validity. It caught exactly that on its first run: `regime-axes` had been
moved out of the body and never wired back into the preprint, so
`main.tex` was building without four axes of the regime map.

Prose was tightened throughout, but tightening alone never accounted for
more than a page or two: the body was long because it reported roughly
twenty experiments, and the fix for that is placement.

**What the body keeps**, end to end with nothing load-bearing removed:
intro, related work (with the blocking citation and every neighbour's
citation), method including \S`sec:whocanlie`, the headline, forgiveness
under lying measurements, the curation-targeted attack, the counter-family
sweep and its refutation, persistence vs destruction, the Mem0 transfer
result, the SWE-Bench-CL null, the attack on real tasks, the regime map's
two deciding axes and its summary, the three load-bearing limitations,
ethics, conclusion.

**For a 9-page NeurIPS D&B body**, the next tier to move is the Mem0
transfer result and the SWE-Bench-CL leg, which would take the paper down
to the synthetic attack and its sweep. That is a decision about which
results *are* the paper, so it is written here rather than made.

**When executing further:** `bench/claims.paper_sections()` enumerates
every `.tex` under `paper/sections/`, so a table may move anywhere in the
tree without losing its binding to the runs. `tests/test_paper_figures.py`
and both evidence-test modules use it.

## How the body got to 39 pages, and the split that got it there

Done. `paper/sections/appendix.tex` exists, `main.tex` wires it behind
`\ifdefined\bodyonly`, and both builds are measured with tectonic:

| build | pages |
|---|---|
| full (body + appendix) | 57 |
| body alone (`\def\bodyonly{}`) | **39** |

Two moves were made. The first is the split this file planned: rent
tiers, the confound control, the 60-cycle horizon grid, the
defence/attack matrix, the model-in-the-loop arm, literature controls,
the second environment, the corpus-or-merge question, moving the floor,
and parametric memory. The second moved another tier when 43 pages was
still nowhere near a limit: the retention attack, MemoryOS, withholding,
and the long-context frontier.

**The residual is not a moving problem.** At 39 body pages against a
9-page NeurIPS D&B limit or ~13 at a security venue, no further
reshuffling closes the gap: the body is long because the paper reports
roughly twenty experiments and a venue paper reports five or six. The
remaining decision is editorial and is the author's -- which results
*are* the paper -- so it is written down here rather than made silently.

**A 13-page body, if a security venue is the target.** Keep: intro,
related, method (including \S\ref{sec:whocanlie}, which answers the
first question a security reviewer asks), the headline, the
curation-targeted attack, the counter-family sweep, persistence vs
destruction, the SWE-Bench-CL null and the attack on real tasks, the
regime map, limitations, ethics, conclusion. That is the argument end to
end with nothing load-bearing removed. Everything else is already in the
appendix and stays reachable.

Getting *that* set to 13 pages needs prose compression rather than
further cuts -- the experiments section still carries long paragraph
titles and multi-sentence justifications that a venue draft states once.
Budget roughly a 40% prose reduction across the body, concentrated in
`experiments.tex` and `limitations.tex`, which are the two longest files.

**When executing further:** `bench/claims.py`, both evidence-test
modules and `bench/paperclaim_env.py` already search body *and* appendix
for a labelled table, so a table may move between them freely without
losing its binding to the runs. That was verified by perturbing a cell
in a moved table and watching the test fail.

## Original split plan (superseded by the section above)
## Main-body / appendix split (ready to execute; gated on a venue page limit)

The built PDF is ~53 pages. The split target is venue-specific -- NeurIPS
Evaluations & Datasets is ~9 body pages, a security venue ~13 + unlimited
appendix -- so the boundary below is drawn at "contribution + negative
results in the body, exhaustive grids in the appendix" and the exact cut is
tuned once a venue is fixed. Not executed yet because a blind split against an
unknown page target, moving tables that the evidence tests parse out of
`experiments.tex`, would risk a paper that currently builds clean and passes
274 evidence tests.

**Body** (the contribution and the results a reviewer must see): intro,
related, method, regime, ethics, conclusion, and from `experiments.tex` the
subsections Headline; Forgiveness under lying measurements; Curation-targeted
attack (denial of memory); A retention attack that never writes; Does the
threat transfer (Mem0); MemoryOS; Withholding; the SWE-Bench-CL protocol and
its null; The attack on real tasks. Plus the load-bearing half of
`limitations.tex`.

**Appendix** (move to a new `paper/sections/appendix.tex`, wired with
`\appendix\input{sections/appendix}` after the conclusion): The price of
standing still (rent tiers); The confound removed; Every 30-cycle grid at 60
(horizon); Where each defence catches each attack; A model in the loop;
Literature controls; Second environment; Was it the corpus or the merge;
Moving the floor; Parametric memory (secondary); and the exhaustive-detail
paragraphs of `limitations.tex`.

**When executing:** update `EXPERIMENTS` in
`tests/test_paper_matches_evidence.py` and
`tests/test_paper_tables_match_evidence.py` (and `bench/claims.py`'s callers)
to search both `experiments.tex` and `appendix.tex` for a labelled table, so
the number-vs-evidence checks still bind every moved table. Then rebuild and
confirm zero undefined `\ref`s (a moved `\ref` resolves across files, but a
"shown above" that now points into the appendix needs rewording).
