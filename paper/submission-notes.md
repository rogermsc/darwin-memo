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
