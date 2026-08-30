"""Cohen's κ and percent agreement vs author-proposed labels."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


def _norm_label(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    if token in {"pass", "true", "yes", "ok"}:
        return "pass"
    if token in {"fail", "false", "no"}:
        return "fail"
    return None


def cohen_kappa(human: list[str], judge: list[str]) -> float | None:
    """Cohen's κ for two raters, binary or small-label. None if N < 2."""
    if len(human) != len(judge) or len(human) < 2:
        return None
    n = len(human)
    agree = sum(1 for a, b in zip(human, judge) if a == b)
    p_o = agree / n
    human_counts = Counter(human)
    judge_counts = Counter(judge)
    labels = set(human_counts) | set(judge_counts)
    p_e = sum((human_counts[lab] / n) * (judge_counts[lab] / n) for lab in labels)
    if abs(1.0 - p_e) < 1e-12:
        return 1.0 if p_o >= 1.0 - 1e-12 else 0.0
    return (p_o - p_e) / (1.0 - p_e)


def percent_agree(human: list[str], judge: list[str]) -> float | None:
    if not human or len(human) != len(judge):
        return None
    return sum(1 for a, b in zip(human, judge) if a == b) / len(human)


def collect_pairs(
    records: Iterable[dict[str, Any]],
) -> dict[str, tuple[list[str], list[str]]]:
    """Per-dimension (human, judge) lists from case records with labels + scores."""
    buckets: dict[str, tuple[list[str], list[str]]] = {}
    for rec in records:
        labels = rec.get("labels")
        judge = rec.get("judge") or {}
        scores = judge.get("scores") if isinstance(judge, dict) else None
        if not isinstance(labels, dict) or not isinstance(scores, dict):
            continue
        for dim, raw_h in labels.items():
            h = _norm_label(raw_h)
            j = _norm_label(scores.get(dim))
            if h is None or j is None:
                continue
            human_list, judge_list = buckets.setdefault(dim, ([], []))
            human_list.append(h)
            judge_list.append(j)
    return buckets


def summarize_agreement(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    pairs = collect_pairs(records)
    by_dim: dict[str, Any] = {}
    for dim, (human, judge) in sorted(pairs.items()):
        pct = percent_agree(human, judge)
        kappa = cohen_kappa(human, judge)
        by_dim[dim] = {
            "n": len(human),
            "percent_agree": None if pct is None else round(pct, 4),
            "cohens_kappa": None if kappa is None else round(kappa, 4),
        }
    return {
        "note": (
            "Labels are author-proposed pending independent double-label. "
            "Informational only — not a ship gate."
        ),
        "dimensions": by_dim,
        "labeled_with_scores": sum(1 for r in records if r.get("labels") and (r.get("judge") or {}).get("scores")),
    }
