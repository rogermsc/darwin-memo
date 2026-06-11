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
  think blocks before parsing the `SOURCES:` line, so reasoning text
  can never count as a citation.
- Hermes 4/4.3 have no official Ollama listing yet; community GGUF
  uploads vary in template quality, which is the main breakage vector.
  `hermes3:8b` is the safe official baseline; the 3B tier is where the
  even-spread citation fallback earns its keep.
- For repeatable citation extraction run the temperature low; the
  Ollama client defaults to 0.

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
