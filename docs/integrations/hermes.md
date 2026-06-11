# Hermes (Nous Research)

"Hermes" is two things in 2026, and darwin-memo connects to both.

## Hermes models, locally

The Hermes model family is built for structured output, which is
exactly what citation-based attribution needs. Through the zero
dependency Ollama client this works today:

```bash
ollama pull hermes3:8b
darwin-memo query memory.json "is the helper safe to remove?" --model ollama:hermes3:8b
```

```python
from darwin_memo import OllamaClient, QueryProtocol

protocol = QueryProtocol(store, OllamaClient(model="hermes3:8b"))
```

Notes from testing and the model cards:

- Hermes 4 and 4.3 are hybrid-reasoning models that may emit a
  `<think>...</think>` block before the answer. darwin-memo strips
  think blocks before parsing the `SOURCES:` line AND before JSON
  extraction in the encoding pipeline, so reasoning text can never
  count as a citation or poison a parsed array.
- Hermes 4/4.3 have no official Ollama library listing, but the
  official NousResearch GGUF pulls directly:
  `ollama pull hf.co/NousResearch/Hermes-4.3-36B-GGUF:Q4_K_M`.
- For repeatable citation extraction run the temperature low; the
  Ollama client defaults to 0.

## Measured: the verification matrix

`python -m bench.citation_probe --model NAME` runs 10 protocol queries
(the benchmark's standard + paraphrase probe sets) against the
headline store and classifies which attribution path each answer took,
then runs reflection-QA encoding over the demo corpus. Sampled output
at temperature 0, one machine, 2026-06-11; rerun the command for your
own numbers.

| | llama3.2 3B | hermes3:8b | qwen3:30b-a3b | Hermes 4.3 36B Q4 |
|---|---|---|---|---|
| SOURCES line emitted | 100% | 100% | 100% | 100% |
| cited (credit to named entries) | 40% | 70% | 20% | 80% |
| explicit `SOURCES: none` | 60% | 30% | 80% | 20% |
| even-spread fallback | 0% | 0% | 0% | 0% |
| think blocks emitted | 0% | 0% | 100% | 0% |
| unattributed action | 10% | 10% | 20% | 10% |
| encoding calls JSON-valid | 3/6 | 6/6 (30 entries) | 0/6 capped, 5/6 uncapped | 6/6 (33 entries) |

What the numbers say, measured rather than vibed:

- An earlier revision of this page predicted the 3B tier would "lean
  on the even-spread citation fallback". Wrong: the fallback never
  fired on any model. Every model emits a parseable SOURCES line on
  every query; small models prefer an explicit `SOURCES: none` over
  citing (llama3.2: 60%). Hermes 4.3 is the strongest citator
  measured (80% cited, 0% fallback, clean JSON).
- The differentiator is temperament, not parsing. hermes3:8b answers
  80% of probe queries as actions and obeys whatever retrieval
  surfaces — including the poisoned entry, which it cites and repeats
  confidently. llama3.2 hedges. In the survival suite that
  temperament gap is worth megabytes: hermes3:8b bleeds -5.9M over a
  12-cycle run while llama3.2 stays positive.
- The dangerous cell is the unattributed action (10-20% on every
  model): an answer that reads as an action while citing nothing. The
  environment acts on it; selection has nobody to charge. Local mode
  cannot produce this cell (silence is an empty answer there), and it
  is the main leak in the no-judge story under synthesis.
- Think-block handling is verified live: qwen3:30b-a3b emitted a
  think block on 10/10 queries and SOURCES parsing was unaffected.
  Encoding was a different story — reasoning brackets poisoned the
  JSON extractor's greedy match (0/6 valid calls) until
  `parse_json_array` learned to strip think blocks too (5/6 after,
  with generation uncapped). The Hermes 4.3 GGUF emitted no think
  blocks under this chat template; do not count on that holding
  across community quants.
- Generation budgets bite in two directions, both measured. llama3.2
  drifts into generating Python code on extraction prompts at
  temperature 0 and, unbounded, generates until the context fills —
  which presents as a timeout, not a bad answer. `OllamaClient` now
  caps at `max_tokens=1024` (like the other clients), turning the
  runaway into an honest 3/6 encoding score. The same cap starves
  thinking models on encoding: qwen3:30b-a3b spends the budget inside
  `<think>` and drops to 0/6 (2/6 at 4096). For reflection-QA
  encoding with a thinking model, pass
  `OllamaClient(max_tokens=8192)` or more; for the query protocol the
  default is right (answers are short and the survival loop wants
  them snappy).
- Selection under synthesis works, an order of magnitude slower:
  30-cycle `survival_llm` runs with llama3.2 kill the actionable
  poison at cycle 14 in 3/3 seeds (local mode: cycle 0), converge to
  5 entries, and end with full harmful-probe safety. At 12 cycles
  nothing has died yet — upkeep alone cannot kill before roughly
  cycle 20 — so short LLM runs say nothing about curation either way.

## Hermes Agent, via MCP

Hermes Agent (github.com/NousResearch/hermes-agent) supports MCP
servers natively in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  darwin_memo:
    command: darwin-memo-mcp
    args: ["--memory", "~/.hermes/darwin-memo.json"]
```

The tools surface as `mcp_darwin_memo_memory_query` and friends, and
Hermes Agent selects them during reasoning. Positioning that respects
what exists: Hermes Agent ships its own integrated memory (agent
curated notes, user modeling, session search) that is not pluggable
today. darwin-memo runs alongside it as the outcome-settled project
memory: lessons whose survival is decided by measured results rather
than by the agent's own curation. If upstream ever opens a memory
backend extension point (worth tracking), a deeper swap becomes
possible.

Caveats: Hermes Agent is pre-1.0 and moves fast (config schema may
churn), and it wants roughly 64k context for tool use, which rules out
small-context local setups.
