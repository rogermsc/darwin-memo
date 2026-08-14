from __future__ import annotations


def selection_scores(true_labels: list[bool], kept: list[bool]) -> dict:
    """Quality of the retained SFT set: precision/recall/F1 of kept-vs-true."""
    tp = sum(1 for t, k in zip(true_labels, kept, strict=True) if k and t)
    kept_n = sum(kept)
    pos_n = sum(true_labels)
    precision = tp / kept_n if kept_n else 0.0
    recall = tp / pos_n if pos_n else 0.0
    f1 = (
        (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    )
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "kept_n": kept_n,
        "true_pos_yield": tp,
    }
