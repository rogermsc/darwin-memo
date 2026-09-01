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
