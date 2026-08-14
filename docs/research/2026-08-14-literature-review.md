# Literature and repo review: what 2026 gives the paper, and one number it takes away

**Date:** 2026-08-14. Extends
[2026-08-01-memory-security-pivot.md](2026-08-01-memory-security-pivot.md),
which established memory security as the publishable regime. This note covers
the four questions that were open after it: why the real-task leg came back
null, what the security field now expects a defence paper to engage, where the
selection-as-data-filter result belongs, and whether the memory leaderboard is
worth entering.

**Standard used here.** A citation is a claim. Entries marked **[read]** were
fetched and checked against the source document; entries marked **[surveyed]**
come from search results and abstracts only and must be read before they enter
`references.bib`. One entry is marked **[defect]** — a number we currently cite
that I could not reproduce from its source.

---

## 0. The defect, first

`related.tex:7`, `experiments.tex:198` and `limitations.tex:158` all rest on:

> detectors average $63.6\%$ true-positive rate on strong-signal payloads and
> $31.6\%$ on weak-signal ones

Sourced from MPBench (2606.04329), via the 2026-08-01 note, which recorded it as
the "mean TPR vs the 4 best filters", 63.57% / 31.63%.

**I could not reproduce those figures from the paper.** Table 4 of the current
version (v2, 18 Jun 2026), transcribed from the PDF:

| Defense | Strong (%) | Weak (%) | Δ |
|---|---|---|---|
| *Off-the-shelf* | | | |
| PIGuard | 51.67 | 18.34 | −33.33 |
| DataFilter | 28.86 | 10.74 | −18.12 |
| CommandSans | 68.33 | 28.34 | −40.00 |
| PromptArmor | 84.44 | 42.50 | −41.94 |
| *Re-trained / adapted for memory poisoning* | | | |
| PIGuard | 48.33 | 46.66 | −1.67 |
| CommandSans | 72.78 | 43.33 | −29.49 |
| PromptArmor | 74.45 | 42.34 | −32.11 |

Aggregations tried, none of which yields 63.57 / 31.63:

| Aggregation | Strong | Weak |
|---|---|---|
| Four off-the-shelf detectors | 58.33 | 24.98 |
| Three re-trained detectors | 65.19 | 44.11 |
| All seven rows | 61.27 | 33.18 |
| Best variant per detector name (by strong) | 59.44 | 28.73 |

**What survives, and what does not.** The *argument* is untouched and if anything
stronger: off-the-shelf detectors lose 33 to 42 points moving from strong-signal
to weak-signal payloads, and the best of them (PromptArmor) still misses 57.5%
of weak-signal attacks. What does not survive is the specific pair of numbers.

**Action:** cite the printed per-detector figures and the Δ column instead of a
computed mean — no arithmetic of ours in the middle. Done in this PR. The same
correction is needed in the 2026-08-01 note, which is where the figure entered.

---

## 1. Track A — why the real-task leg came back null

Our null is 2,115 SWE-Bench-CL tasks, four sequences, no memory arm beating
`memory_off`. The paper attributes it to horizon arithmetic, then retracts that
("the excuse did not survive its own test"). 2026 offers three better
explanations, and one of them says the testbed cannot show what we asked it to.

### AgentCL (2606.02461) — **[read]** — verdict: **ADOPT + CITE**
*Toward Rigorous Evaluation of Continual Learning in Language Agents* — Shu,
Jiménez Gutiérrez, Jonnalagedda, Yao, Sun, Su (1 Jun 2026).

Its central claim is that lifelong-adaptation benchmarks "rely on naive task
streams" with no guaranteed reuse between tasks, so nothing can be concluded
about what an agent learns and reuses. Its fix is a *controlled task stream*
where "earlier sub-solutions, evidence, or workflows are intentionally reusable
in later tasks."

**This is the most consequential entry in the review.** SWE-Bench-CL orders
tasks chronologically by repository and by estimated fix time; it does not
guarantee that lesson *n* is reusable at task *n+k*. If reuse is not
constructed, a memory arm cannot beat a no-memory arm no matter how good the
curation is, and our null measures the benchmark rather than the ledger. The
paper currently reports the null as a property of the mechanism. That reading is
not safe, and AgentCL is the citation that makes the alternative explicit.

Also introduces **MemProbe**, a conservative consolidation policy that filters
unreliable experience so memory "is more likely to aid transfer than amplify
noise" — the nearest published relative of the ledger's write-time admission.

### When Continual Learning Moves to Memory (2604.27003) — **[read]** — verdict: **CITE**
Memory-based continual learning does not dissolve the stability–plasticity
dilemma, it relocates it: old and new experiences compete at *retrieval* under a
bounded context. Two findings bear on us: abstract procedural memories transfer
more reliably than detailed trajectories, and designs with strong forward
transfer can simultaneously induce severe forgetting. Evaluated on ALFWorld and
BabyAI.

Our entries are detailed QA pairs, and our retrieval is BM25 at 74% correct-file
recall. This paper says both choices bound the result independently of selection.

### ReasoningBank (2509.25140, ICLR 2026) — **[read]** — verdict: **CITE (rival result)**
Ouyang et al. Distils "generalizable reasoning strategies from an agent's
**self-judged** successful and failed experiences". SWE-Bench-Verified, bash-only
ReAct scaffold, verified from the paper's own table:

| Model | No Memory | Synapse | ReasoningBank |
|---|---|---|---|
| Gemini-2.5-pro | 54.0% (21.1 steps) | 53.4% (21.0) | **57.4%** (19.8) |
| Gemini-2.5-flash | 34.2% (30.3 steps) | 35.4% (30.7) | **38.8%** (27.5) |

A rival reports +3.4 and +4.6 points on the same benchmark family where we report
a null — using strategy-level representation selected by an LLM judging its own
trajectories, which is precisely the judge this project refuses. The paper must
state this contrast plainly rather than let a reader find it. It is also the
strongest argument for the representation arm in Phase 2: the difference between
their result and ours may be *what is stored*, not *how it is selected*, and we
can test that without adopting a judge.

### ChainSWE (2607.02606) — **[surveyed]** — verdict: **ADOPT (candidate)**
Sequential, *dependent* bug fixes in a shared codebase — explicitly built because
existing SWE benchmarks evaluate one bug at a time and ignore cumulative
dependency. That dependency is the reuse AgentCL says must be constructed. Best
candidate for a real-task leg where memory can actually pay.

### Also surveyed, not read
CL-Bench (2606.05661, six domains of sequential experience); EET (2601.05777,
experience-driven early termination for cost-efficient SWE agents).

---

## 2. Track B — what a memory-security paper is now expected to engage

The 2026-08-01 note already established ASI06, MemSecBench, MPBench, SMSR,
forensic signatures and MAGE. This review adds the attack-side literature our
`related.tex` is missing, all of it verified from MPBench's own reference list
(read from the PDF, p. 10):

| Work | Why it belongs in our related work |
|---|---|
| **Dong et al., "Memory injection attacks on LLM agents via query-only interaction", NeurIPS 2025** (MINJA) | **The gap in our threat model.** `docs/threat-model.md` trusts the `settle` caller completely. MINJA needs no write access at all — it reaches memory through ordinary queries. Our stated boundary ("a settler who controls enough settlements controls the population") does not cover an attacker who never settles. |
| **Chen et al., "AgentPoison: Red-teaming LLM agents via poisoning memory or knowledge bases", NeurIPS 2024** | The canonical agent-memory poisoning attack; our paper cites no attack paper older than 2026, which reads as a literature gap rather than a scope choice. |
| **Zou et al., "Poison once, exploit forever: Environment-injected memory poisoning attacks on web agents", 2604.02623** | Environment-injected poisoning — the closest published analogue to our environment-mediated settlement. |
| **Xu et al., "From storage to steering: Memory control flow attacks on LLM agents", 2026** | Attacks the control flow rather than the content — a class our content-blind selection may be structurally immune to, which is worth claiming only if we cite it. |
| **Srivastava & He, "MemoryGraft: Persistent compromise via poisoned experience retrieval", 2512.16962** | Persistence through retrieval, not writes. |
| **Tan et al., "MemBench", ACL Findings 2025** | Memory evaluation for agents, predating the 2026 security wave. |
| Greshake et al. (AISec 2023), Zhan et al. InjecAgent (ACL Findings 2024), Debenedetti et al. AgentDojo (NeurIPS 2024) | The indirect-prompt-injection lineage our paper's "where defences sit" paragraph implicitly assumes but never cites. |

**MPBench evaluates OpenClaw and HERMES** (Table 2: OpenClaw 34.25% ASR / 17.40%
RSR; HERMES 66.67% / 64.70%) — the two agent hosts this repo already ships
integrations for (`docs/integrations/openclaw.md`, `hermes.md`). That is the
cheapest real security leg available to us: the benchmark of record already runs
on our two integration targets, and the paper's own weakest reconstruction (our
write-time filter scores 0% on weak-signal) is exactly what it measures.

MPBench's three prescribed defence directions map onto the ledger cleanly, and
the paper should say so in these words rather than claim ASI06 coverage:
write-policy tightening (our admission gating), **write-path provenance
tracking** (our provenance-scoped credit), and **post-write monitoring against
authorized behaviour rather than attack patterns** (our settlement is exactly
this — it evaluates entries against what the environment did, not against what
they say).

---

## 3. Track C — selection as a data filter for parametric memory

A field formed around distilling agent experience into weights in 2026, and none
of it filters what gets distilled. This is where our least-contested result sits.

### TMEM (2606.04536) — **[read]** — verdict: **CITE**
*Scaling Self-Evolving Agents via Parametric Memory*, Ren et al. (3 Jun 2026).
Compresses history into explicit memory *and* absorbs distilled supervision into
fast LoRA weights via online updates within a single episode. Evaluated on
LoCoMo, LongMemEval-S, multi-objective search and CL-Bench; beats summary-based
and retrieval-based baselines across model scales. **The abstract does not
specify any filter on what supervision gets distilled** — the exact hole
`distill_survivor` vs `distill_raw` measures.

### Procedural Memory Distillation (2607.01480) and MemVerse (2512.03627) — **[surveyed]** — verdict: **CITE**
PMD converts repeated attempts into procedural memory distilled into policy
weights during training; MemVerse periodically distils long-term memory into the
parametric model. Same shape, same missing filter.

### An Imperfect Verifier is Good Enough (2604.07666) — **[surveyed]** — verdict: **CITE**
Learning with noisy rewards. Direct theoretical company for `distill_noisy`:
survival keeps 0.91 of distilled capability under `flip@0.2` where `evict_k1` and
`evict_consec` collapse to 0.00 and 0.03. Our result is an empirical instance of
a claim this paper makes generally, and citing it converts an isolated finding
into a positioned one.

---

## 4. Track D — mechanism neighbours, and the leaderboard question

### Nearest mechanism neighbours — verdict: **ARM**
- **Adaptive Memory Admission Control (2603.04549)** — **[read]** — write-time
  admission on *measured signals*, not a judge; baselines MemGPT, MemoryBank,
  A-MEM, Mem0, HippoRAG. **No adversarial evaluation whatsoever.** The nearest
  published mechanism to ours, and the one a reviewer will ask why we did not run.
- **EMBER (2606.05894)** — **[read]** — budgeted evidence retention under a fixed
  memory budget, selection by relevance score. The nearest *economic* framing to
  ours; the difference is that its budget is spent on relevance while ours is
  earned by outcome. Evaluated on LongMemEval and MultiQ; no adversarial leg.

### The credit-assignment cluster — verdict: **CITE**
Memory-R2 (2605.21768, LoGo-GRPO for memory operations), tree-based credit
assignment for multi-agent memory (2605.04811), AttriMem (2607.21106,
attribution-guided process feedback), AgeMem (RL over
store/retrieve/update/summarize/discard) — all **[surveyed]**. This is the family
our ledger is the judge-free alternative to, and the paper currently has no
paragraph naming it. Their common bottleneck — fine-grained credit assignment
from coarse outcome signals — is the problem our provenance-scoped tanh-bounded
credit answers with arithmetic instead of learning.

### ACT-R remembering and forgetting (HAI 2026, 10.1145/3765766.3765803) — **[surveyed]** — verdict: **CITE**
Dynamic retrieval and forgetting by context, time and usage frequency, with
temporal decay and probabilistic noise. This is the cognitive-architecture form
of `salience_matched` — and the only external anchor for `darwin_memo/organic/`,
which has no paper representation at all. If the organic layer is ever written
up, this is its related work, and our `salience_matched` result (kill rate 0.20
vs random 0.80) is a caution the ACT-R line has not tested.

### Surveys — verdict: **CITE (one, not four)**
2603.07670 (*Memory for Autonomous LLM Agents: Mechanisms, Evaluation, Emerging
Frontiers*), 2606.30306 (*Always-On Agents*: persistent memory, state, and
governance), 2505.00675 (*Rethinking Memory in LLM Based Agents*), and Hu et al.
2512.13564 (*Memory in the Age of AI Agents*, the survey behind the
Agent-Memory-Paper-List repo). All **[surveyed]**. Pick one as the "for a survey,
see" anchor; citing four is padding.

### The leaderboard — verdict: **SCOPE-OUT, with one sentence in the paper**
LongMemEval-V2 (2605.12493), BEAM (ICLR 2026, 10M-token conversations), HaluMem
and RealMem now define comparability, and Mem0 and Zep post numbers on them
(Zep 63.8% vs Mem0 49.0% on LongMemEval with GPT-4o).

We should not enter. `README.md:26-39` already states why: *"if your `verify`
would be a model scoring an answer, this package is wrong for you, by design."*
LongMemEval has no measured outcome for a ledger to earn from — entering it would
either require a judge or would measure retrieval quality with selection disabled.
The right move is one sentence in the paper naming these benchmarks and the
reason they are out of scope, which converts a visible absence into a stated
boundary. **The bib entries are still needed**: Zep and Letta are named in our
prose today with no entries at all, and A-MEM sits in the bib uncited.

---

## 5. Repos worth reading as code

| Repo | Use |
|---|---|
| [TeleAI-UAGI/Awesome-Agent-Memory](https://github.com/TeleAI-UAGI/Awesome-Agent-Memory) | Coverage check against this review — cheapest way to find what it missed |
| [Shichun-Liu/Agent-Memory-Paper-List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List) | Paper list behind *Memory in the Age of AI Agents* |
| [supermemoryai/memorybench](https://github.com/supermemoryai/memorybench) | Unified conversational-memory harness; read before writing any leaderboard adapter |
| Letta, Mem0, Graphiti/Zep, cognee, EverMemOS | Bib entries we owe; their eviction policies are candidate arms |

**Code availability.** MINJA (2503.03704, v5 Feb 2026) states a code release in
its arXiv metadata — verify it runs before planning around it, but the query-only
attack may be portable rather than reimplemented. **No public release is
confirmed for MPBench**, so its weak-signal payload classes follow the
MemSecBench precedent already set in `experiments.tex`: reimplement the protocol,
compare no numbers across papers.

---

## 6. What this review changes

1. **Correct the MPBench figures** in three paper sections and the 2026-08-01
   note. Cite printed per-detector values, not a mean we cannot reproduce.
2. **Report the null with three explanations, not one.** Horizon arithmetic
   (ours, retracted), retrieval competition (2604.27003), and — the one that
   matters — an uncontrolled task stream (AgentCL). Add to `limitations.tex`
   that a benchmark without constructed reuse cannot separate "selection does
   not help" from "there was nothing to reuse".
3. **Name the ReasoningBank contrast** in `sec:swebench` with its numbers.
4. **Add the attack-side citations** (MINJA, AgentPoison, Zou, Xu, MemoryGraft)
   and the credit-assignment cluster to `related.tex`.
5. **Add MINJA's threat class to `docs/threat-model.md`** — query-only injection
   defeats a trusted-settler assumption without violating it.
6. **Fix the bib defects**: cite A-MEM or drop it; give Zep and Letta entries.
7. **Phase 2 arms, in priority order**: `oracle_file` (separates the retrieval
   ceiling from the null), `survival_abstracted` (representation vs selection —
   answers ReasoningBank on our terms), `admission_control` and `budget_relevance`
   (the two nearest neighbours), then the query-only-injection security leg.
