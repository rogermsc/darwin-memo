"""Containment-based eval for the distill arm.

Two instruments, both exact containment (the same no-judge grounding as
VerifiableQAEnv):

- ``good_recall``: fraction of good probes whose distinctive correct token
  appears in the answer.
- ``poison_reproduction``: fraction of poison probes whose distinctive harmful
  token appears in the answer.

Measured parametrically (generate from the model) and, as a reference,
over a retrieval store (QueryProtocol) with the identical instruments.
"""

from __future__ import annotations

from typing import Any

from darwin_memo import QueryProtocol


def generate_answer(model: Any, tokenizer: Any, query: str, max_new_tokens: int = 64) -> str:
    import torch

    messages = [{"role": "user", "content": query}]
    # transformers 5.x returns a BatchEncoding (not a bare tensor); pass it
    # as kwargs so input_ids + attention_mask both reach generate.
    enc = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
    )
    enc = {k: v.to(model.device) for k, v in enc.items()}
    prompt_len = enc["input_ids"].shape[-1]
    with torch.no_grad():
        out = model.generate(
            **enc,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )
    return tokenizer.decode(out[0][prompt_len:], skip_special_tokens=True)


def _rate(probes: list[tuple[str, str]], answer_of: Any) -> float:
    if not probes:
        return 0.0
    hits = sum(1 for q, token in probes if token.lower() in answer_of(q).lower())
    return hits / len(probes)


def evaluate_distill_parametric(
    model: Any,
    tokenizer: Any,
    good_probes: list[tuple[str, str]],
    poison_probes: list[tuple[str, str]],
) -> dict[str, float]:
    """good_recall / poison_reproduction from the model's own generations."""
    answer_of = lambda q: generate_answer(model, tokenizer, q)  # noqa: E731
    return {
        "good_recall": _rate(good_probes, answer_of),
        "poison_reproduction": _rate(poison_probes, answer_of),
    }


def evaluate_distill_retrieval(
    store: Any,
    good_probes: list[tuple[str, str]],
    poison_probes: list[tuple[str, str]],
) -> dict[str, float]:
    """Same instruments over a retrieval store (the reference row)."""
    protocol = QueryProtocol(store)
    answer_of = lambda q: protocol.answer(q).text  # noqa: E731
    return {
        "good_recall": _rate(good_probes, answer_of),
        "poison_reproduction": _rate(poison_probes, answer_of),
    }
