"""Citation-fidelity probe: how well does a model carry provenance?

Selection in LLM mode is only as honest as the citations: credit flows
to the entries the model says it used. This probe measures, per model,
how often that attribution chain actually works, plus the one hazard
local-mode never has: answers that READ as an action (so the
environment acts) while citing nothing (so nobody pays for the
outcome). The first LLM-mode benchmark runs showed exactly that
failure dominating, which is why these rates are measured rather than
assumed.

    python -m bench.citation_probe --model llama3.2 --out bench/results/cit.json

Sampled, model-dependent, never in CI. Per query the probe records
which path the protocol took:

- cited: a parseable SOURCES line carrying bracket numbers; credit
  flows to the cited entries. The fidelity success case.
- explicit_none: the model declared SOURCES: none; counted as silence,
  no provenance. Honest, if the answer is also non-actionable.
- fallback: no parseable SOURCES line; credit spreads evenly over
  everything consulted, diluting punishment across innocents.
- unattributed_action: the answer reads as an action under
  decision_polarity but carries NO provenance. The environment acts,
  selection cannot assign the outcome to anything. The dangerous cell.

It also runs the reflection-QA encoding pipeline over the demo corpus
and reports JSON-validity rates, and counts think-blocks to verify the
stripping path on hybrid-reasoning models.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from darwin_memo import (
    OllamaClient,
    QueryProtocol,
    ReflectionEncoder,
    decision_polarity,
    demo_corpus,
)
from darwin_memo.llm import parse_json_array
from darwin_memo.protocol import _SOURCES_RE, _THINK_RE

from .fixtures import PARAPHRASE_PROBES, PROBES, build_headline_store

# Encoding prompts carry whole documents and queue behind anything else
# the server is doing; the default 120s client timeout is too twitchy
# for a probe whose only job is to finish.
PROBE_TIMEOUT = 600.0


class RecordingClient:
    """Wraps a client, keeping every raw completion for classification."""

    def __init__(self, inner: OllamaClient) -> None:
        self.inner = inner
        self.calls: list[dict[str, str]] = []

    def complete(self, prompt: str, system: str = "") -> str:
        raw = self.inner.complete(prompt, system)
        self.calls.append({"prompt": prompt, "raw": raw})
        return raw


def classify_answer(raw_final: str, answer: Any) -> dict[str, Any]:
    """Which attribution path did the protocol take for this answer?"""
    had_think = bool(_THINK_RE.search(raw_final))
    stripped = _THINK_RE.sub("", raw_final)
    matches = list(_SOURCES_RE.finditer(stripped))
    has_sources_line = bool(matches)
    explicit_none = bool(matches) and bool(
        re.search(r"\bnone\b", matches[-1].group(1), re.IGNORECASE)
    )
    has_provenance = bool(answer.deciding_entry or answer.supporting_entries)
    cited = has_sources_line and not explicit_none and has_provenance
    polarity = decision_polarity(answer.text)
    return {
        "had_think_block": had_think,
        "sources_line": has_sources_line,
        "explicit_none": explicit_none,
        "cited": cited,
        "fallback": not has_sources_line and has_provenance,
        "actionable": polarity is True,
        "unattributed_action": polarity is True and not has_provenance,
    }


def probe_protocol(model: str) -> dict[str, Any]:
    store = build_headline_store()
    client = RecordingClient(OllamaClient(model=model, timeout=PROBE_TIMEOUT))
    protocol = QueryProtocol(store, client)

    per_query: list[dict[str, Any]] = []
    for probe in [*PROBES, *PARAPHRASE_PROBES]:
        before = len(client.calls)
        answer = protocol.answer(probe.query)
        raw_final = client.calls[-1]["raw"] if len(client.calls) > before else ""
        record = classify_answer(raw_final, answer)
        record["query"] = probe.query
        record["answer"] = answer.text[:200]
        per_query.append(record)

    n = len(per_query)
    rates = {
        key: sum(1 for r in per_query if r[key]) / n
        for key in (
            "sources_line",
            "explicit_none",
            "cited",
            "fallback",
            "had_think_block",
            "actionable",
            "unattributed_action",
        )
    }
    return {"queries": n, "rates": rates, "per_query": per_query}


def probe_encoding(model: str) -> dict[str, Any]:
    client = RecordingClient(OllamaClient(model=model, timeout=PROBE_TIMEOUT))
    entries = ReflectionEncoder(client, max_workers=1).encode(demo_corpus())
    calls = len(client.calls)
    valid = sum(1 for c in client.calls if parse_json_array(c["raw"]))
    return {
        "calls": calls,
        "json_valid_calls": valid,
        "json_valid_rate": valid / calls if calls else 0.0,
        "entries_produced": len(entries),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Ollama model name")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--skip-encoding", action="store_true", help="protocol fidelity only"
    )
    args = parser.parse_args(argv)

    from darwin_memo import ollama_available

    if not ollama_available():
        print("error: needs a running Ollama server (https://ollama.com)")
        return 1

    result: dict[str, Any] = {"model": args.model}
    result["protocol"] = probe_protocol(args.model)
    if not args.skip_encoding:
        # A model that times out or mangles the encoding prompts should
        # cost the encoding section, not the protocol numbers above.
        try:
            result["encoding"] = probe_encoding(args.model)
        except Exception as error:
            result["encoding_error"] = str(error)

    rates = result["protocol"]["rates"]
    print(f"\n{args.model}: {result['protocol']['queries']} protocol queries")
    for key, value in rates.items():
        print(f"  {key:>22}: {value:.0%}")
    if "encoding" in result:
        enc = result["encoding"]
        print(
            f"  encoding: {enc['json_valid_calls']}/{enc['calls']} calls valid "
            f"JSON ({enc['json_valid_rate']:.0%}), "
            f"{enc['entries_produced']} entries"
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
