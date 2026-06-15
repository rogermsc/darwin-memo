"""LoRA distillation of a survivor set into a parametric memory model.

Shared by the user-facing CLI (``training/train_memory_model.py``) and the
``distill`` benchmark arm, so there is one trainer and no drift. Heavy deps
(torch/transformers/peft/datasets) are imported lazily inside ``train_lora``:
importing this module stays cheap and the zero-dep core is untouched.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from darwin_memo import MemoryEntry

# Label id the HF loss ignores; masks prompt tokens so the next-token
# objective lands only on the answer (internalize answer-given-question).
PROMPT_IGNORE = -100


def _ids(enc: Any) -> list[int]:
    """Token ids from apply_chat_template, across transformers versions.

    transformers 5.x returns a BatchEncoding (dict-like) from
    ``apply_chat_template(tokenize=True)``; 4.x returns a plain list of ints.
    """
    if isinstance(enc, dict) or hasattr(enc, "keys"):
        return list(enc["input_ids"])
    return list(enc)


def _format(
    tokenizer: Any, entry: MemoryEntry, mask_prompt: bool
) -> dict[str, list[int]]:
    """Tokenize one QA pair into input_ids + labels, masking the prompt."""
    prompt_msgs = [{"role": "user", "content": entry.question}]
    full_msgs = [*prompt_msgs, {"role": "assistant", "content": entry.answer}]
    prompt_ids = _ids(
        tokenizer.apply_chat_template(
            prompt_msgs, tokenize=True, add_generation_prompt=True
        )
    )
    full_ids = _ids(
        tokenizer.apply_chat_template(
            full_msgs, tokenize=True, add_generation_prompt=False
        )
    )
    labels = list(full_ids)
    if mask_prompt:
        for i in range(min(len(prompt_ids), len(labels))):
            labels[i] = PROMPT_IGNORE
    return {"input_ids": list(full_ids), "labels": labels}


def count_trainable_params(model: Any) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def train_lora(
    survivors: Sequence[MemoryEntry],
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
    out_dir: str | Path = "memory-model",
    *,
    epochs: int = 3,
    lr: float = 2e-4,
    mask_prompt: bool = True,
    seed: int = 0,
) -> dict[str, Any]:
    """Fine-tune ``base_model`` on ``survivors`` with LoRA.

    Returns ``{"out_dir", "n_train", "trainable_params", "train_wall_s"}``.
    """
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    if not survivors:
        raise ValueError("no surviving entries to distill")
    set_seed(seed)
    out_dir = Path(out_dir)

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # bf16 only on CUDA; CPU/MPS default to float32 (the from_pretrained
    # dtype kwarg name has churned across versions, so we set it only where
    # we control the wheel — the RunPod CUDA box).
    model_kwargs: dict[str, Any] = {}
    if torch.cuda.is_available():
        model_kwargs["dtype"] = torch.bfloat16
    model = AutoModelForCausalLM.from_pretrained(base_model, **model_kwargs)
    model = get_peft_model(
        model,
        LoraConfig(
            r=16, lora_alpha=32, target_modules="all-linear", task_type="CAUSAL_LM"
        ),
    )
    trainable = count_trainable_params(model)

    dataset = Dataset.from_list([_format(tokenizer, e, mask_prompt) for e in survivors])
    # Seq2Seq collator pads BOTH input_ids and labels (label pad = -100);
    # the LM collator does not pad labels and would crash on masked rows.
    collator = DataCollatorForSeq2Seq(
        tokenizer, model=model, label_pad_token_id=PROMPT_IGNORE
    )

    trainer = Trainer(
        model=model,
        train_dataset=dataset,
        args=TrainingArguments(
            output_dir=str(out_dir),
            num_train_epochs=epochs,
            learning_rate=lr,
            per_device_train_batch_size=4,
            logging_steps=10,
            save_strategy="no",
            report_to="none",
            seed=seed,
        ),
        data_collator=collator,
    )
    start = time.perf_counter()
    trainer.train()
    wall = time.perf_counter() - start

    trainer.save_model(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    return {
        "out_dir": str(out_dir),
        "n_train": len(survivors),
        "trainable_params": int(trainable),
        "train_wall_s": round(wall, 4),
    }
