"""Optional: distill a surviving memory store into a parametric memory model.

MeMo's memory is a small LLM trained on the reflection QA dataset, not a
retrieval store. This script closes that gap for anyone with a GPU: it takes a
store that has been through survival selection (so the poison and the dead
weight are already gone) and LoRA-fine-tunes a small model on the surviving QA
pairs, conditioning on questions only. The actual trainer lives in
``bench/distill/train.py`` so this CLI and the ``distill`` benchmark arm share
one implementation and cannot drift.

Requires: pip install transformers peft datasets torch accelerate

    python training/train_memory_model.py memory.json --model Qwen/Qwen2.5-0.5B-Instruct
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bench.distill.train import train_lora  # noqa: E402
from darwin_memo import MemoryStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store_path", help="memory.json produced by MemoryStore.save")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--output", default="memory-model")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    args = parser.parse_args()

    store = MemoryStore.load(args.store_path)
    survivors = store.alive()
    if not survivors:
        raise SystemExit("Store has no surviving entries. Run a survival loop first.")
    print(f"Distilling {len(survivors)} surviving entries from {args.store_path}")
    result = train_lora(
        survivors,
        base_model=args.model,
        out_dir=args.output,
        epochs=args.epochs,
        lr=args.lr,
    )
    print(f"Saved LoRA memory model to {result['out_dir']}/")


if __name__ == "__main__":
    main()
