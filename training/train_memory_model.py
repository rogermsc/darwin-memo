"""Optional: distill a surviving memory store into a parametric memory model.

MeMo's memory is a small LLM trained on the reflection QA dataset, not a
retrieval store. This script closes that gap for anyone with a GPU: it
takes a store that has been through survival selection (so the poison and
the dead weight are already gone) and fine-tunes a small model on the
surviving QA pairs with LoRA, the same supervised next-token objective
the paper uses. LoRA adapters per corpus also line up with the paper's
task-vector merging story for continual learning.

Requires: pip install transformers peft datasets torch

    python training/train_memory_model.py memory.json --model Qwen/Qwen2.5-0.5B-Instruct
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from darwin_memo import MemoryStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store_path", help="memory.json produced by MemoryStore.save")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--output", default="memory-model")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    args = parser.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    store = MemoryStore.load(args.store_path)
    survivors = store.alive()
    if not survivors:
        raise SystemExit("Store has no surviving entries. Run a survival loop first.")
    print(f"Distilling {len(survivors)} surviving entries from {args.store_path}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
    )
    model = get_peft_model(
        model,
        LoraConfig(r=16, lora_alpha=32, target_modules="all-linear", task_type="CAUSAL_LM"),
    )

    def to_text(entry) -> dict:
        # Condition on the question only, never on source documents:
        # the model must internalize the knowledge parametrically.
        messages = [
            {"role": "user", "content": entry.question},
            {"role": "assistant", "content": entry.answer},
        ]
        return {"text": tokenizer.apply_chat_template(messages, tokenize=False)}

    dataset = Dataset.from_list([to_text(e) for e in survivors]).map(
        lambda row: tokenizer(row["text"], truncation=True, max_length=512),
        remove_columns=["text"],
    )

    trainer = Trainer(
        model=model,
        train_dataset=dataset,
        args=TrainingArguments(
            output_dir=args.output,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            per_device_train_batch_size=4,
            logging_steps=10,
            save_strategy="epoch",
            report_to="none",
        ),
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )
    trainer.train()
    trainer.save_model(args.output)
    print(f"Saved LoRA memory model to {args.output}/")


if __name__ == "__main__":
    main()
