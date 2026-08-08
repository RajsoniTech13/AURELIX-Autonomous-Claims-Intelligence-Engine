"""
AURELIX — evaluation harness.

Every number this module writes is computed from the two CSVs it is given. Nothing is
asserted that was not measured.

That is a change in kind from the previous version, whose "Operational & Cost Analysis"
and "High-Load Production Strategies" sections were hardcoded string literals. The report
on disk claimed a model the project does not use (`gpt-4o-mini`), a per-claim latency an
order of magnitude below the measured value, a token-bucket rate limiter that did not
exist, and a retry-and-escalate path that could not execute. For an insurance product
those are audit-trail claims, so they are gone rather than corrected: if we do not measure
it here, this file does not say it.
"""
from __future__ import annotations

import csv
import os
from collections import Counter
from typing import Any, Dict, List, Tuple

CLASSES = ("supported", "contradicted", "not_enough_information")


def _join_key(row: Dict[str, str]) -> Tuple[str, str]:
    """
    Join on (user_id, image_paths).

    The previous key was `user_id + claim_object`, which is not unique — the same user
    files multiple car claims — so rows silently overwrote each other before scoring.
    """
    return row.get("user_id", ""), row.get("image_paths", "")


def _load(path: str) -> Tuple[Dict[Tuple[str, str], Dict[str, str]], int, int]:
    """Return (indexed rows, total rows read, duplicate-key count)."""
    with open(path, mode="r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    indexed: Dict[Tuple[str, str], Dict[str, str]] = {}
    duplicates = 0
    for row in rows:
        key = _join_key(row)
        if key in indexed:
            duplicates += 1
        indexed[key] = row
    return indexed, len(rows), duplicates


def _norm(row: Dict[str, str], field: str) -> str:
    return (row.get(field) or "").strip().lower()


def evaluate_predictions(
    sample_path: str | None = None,
    output_path: str | None = None,
    report_path: str | None = None,
) -> Dict[str, Any]:
    """Score predictions against labelled ground truth. Returns the metrics dict."""
    here = os.path.dirname(__file__)
    sample_path = sample_path or os.path.abspath(os.path.join(here, "../data/sample_claims.csv"))
    output_path = output_path or os.path.abspath(os.path.join(here, "../output/output.csv"))
    report_path = report_path or os.path.abspath(os.path.join(here, "../output/evaluation_report.md"))

    print("--- AURELIX evaluation ---")
    if not os.path.exists(sample_path) or not os.path.exists(output_path):
        print(f"Cannot evaluate: missing {sample_path} or {output_path}")
        return {}

    truth, truth_rows, truth_dupes = _load(sample_path)
    preds, pred_rows, pred_dupes = _load(output_path)

    matched_keys = sorted(set(truth) & set(preds))
    missing = sorted(set(truth) - set(preds))

    # Coverage is reported prominently and separately from accuracy. A run that emitted
    # one row out of twenty could otherwise report 100% and look healthy.
    coverage = len(matched_keys) / len(truth) if truth else 0.0

    confusion = {gt: Counter() for gt in CLASSES}
    correct_status = correct_severity = correct_evidence = 0
    mistakes: List[Dict[str, str]] = []

    for key in matched_keys:
        gt_row, pr_row = truth[key], preds[key]

        gt_status = _norm(gt_row, "claim_status")
        pr_status = _norm(pr_row, "claim_status")
        gt_status = gt_status if gt_status in CLASSES else "not_enough_information"
        pr_status = pr_status if pr_status in CLASSES else "not_enough_information"
        confusion[gt_status][pr_status] += 1

        if gt_status == pr_status:
            correct_status += 1
        else:
            mistakes.append({
                "user_id": gt_row.get("user_id", ""),
                "claim_object": gt_row.get("claim_object", ""),
                "expected": gt_status,
                "predicted": pr_status,
                "predicted_severity": _norm(pr_row, "severity"),
                "expected_severity": _norm(gt_row, "severity"),
                "justification": (pr_row.get("claim_status_justification") or "")[:160],
            })

        if _norm(gt_row, "severity") == _norm(pr_row, "severity"):
            correct_severity += 1
        if _norm(gt_row, "evidence_standard_met") == _norm(pr_row, "evidence_standard_met"):
            correct_evidence += 1

    n = len(matched_keys)
    per_class: Dict[str, Dict[str, float]] = {}
    for c in CLASSES:
        tp = confusion[c][c]
        fp = sum(confusion[o][c] for o in CLASSES if o != c)
        fn = sum(confusion[c][o] for o in CLASSES if o != c)
        support = sum(confusion[c].values())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[c] = {
            "tp": tp, "fp": fp, "fn": fn, "support": support,
            "precision": precision, "recall": recall, "f1": f1,
        }

    macro_f1 = sum(m["f1"] for m in per_class.values()) / len(CLASSES)
    metrics = {
        "n_ground_truth": len(truth),
        "n_predictions": len(preds),
        "n_matched": n,
        "coverage": coverage,
        "status_accuracy": correct_status / n if n else 0.0,
        "severity_accuracy": correct_severity / n if n else 0.0,
        "evidence_accuracy": correct_evidence / n if n else 0.0,
        "macro_f1": macro_f1,
        "per_class": per_class,
        "confusion": {gt: dict(row) for gt, row in confusion.items()},
        "mistakes": mistakes,
    }

    _write_report(report_path, metrics, sample_path, output_path,
                  truth_rows, pred_rows, truth_dupes, pred_dupes, missing)

    print(
        f"Coverage {coverage:.0%} ({n}/{len(truth)}). "
        f"Status accuracy {metrics['status_accuracy']:.1%}, macro-F1 {macro_f1:.1%}."
    )
    print(f"Report: {report_path}")
    return metrics


def _write_report(
    path: str, m: Dict[str, Any], sample_path: str, output_path: str,
    truth_rows: int, pred_rows: int, truth_dupes: int, pred_dupes: int,
    missing: List[Tuple[str, str]],
) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pc = m["per_class"]

    lines = [
        "# AURELIX — Evaluation Report",
        "",
        "Every figure below is computed from the two files named here. Latency, token, and",
        "cost figures are deliberately absent: this harness does not observe the pipeline",
        "running, so it does not report on it. See `PERFORMANCE.md` for measured runtime data.",
        "",
        f"- Ground truth: `{os.path.relpath(sample_path)}` ({truth_rows} rows)",
        f"- Predictions: `{os.path.relpath(output_path)}` ({pred_rows} rows)",
        "",
        "## Coverage",
        "",
        f"| Matched | Ground truth | Coverage |",
        f"| ---: | ---: | ---: |",
        f"| {m['n_matched']} | {m['n_ground_truth']} | **{m['coverage']:.1%}** |",
        "",
    ]

    if m["coverage"] < 1.0:
        lines += [
            f"> **{len(missing)} ground-truth claim(s) have no prediction** and are excluded from",
            "> every accuracy figure below. Accuracy is conditional on coverage — read them together.",
            "",
        ]
    if truth_dupes or pred_dupes:
        lines += [
            f"> Duplicate join keys collapsed: {truth_dupes} in ground truth, {pred_dupes} in predictions.",
            "",
        ]

    lines += [
        "## Classification performance",
        "",
        "| Metric | Score | Correct | Scored |",
        "| :--- | ---: | ---: | ---: |",
        f"| Claim verdict accuracy | **{m['status_accuracy']:.1%}** | {round(m['status_accuracy'] * m['n_matched'])} | {m['n_matched']} |",
        f"| Severity accuracy | {m['severity_accuracy']:.1%} | {round(m['severity_accuracy'] * m['n_matched'])} | {m['n_matched']} |",
        f"| Evidence-standard accuracy | {m['evidence_accuracy']:.1%} | {round(m['evidence_accuracy'] * m['n_matched'])} | {m['n_matched']} |",
        "",
        "### Per class",
        "",
        "| Class | Support | TP | FP | FN | Precision | Recall | F1 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in CLASSES:
        d = pc[c]
        lines.append(
            f"| {c} | {d['support']} | {d['tp']} | {d['fp']} | {d['fn']} | "
            f"{d['precision']:.1%} | {d['recall']:.1%} | {d['f1']:.1%} |"
        )

    lines += [
        "",
        f"**Macro F1: {m['macro_f1']:.1%}**",
        "",
        f"> Support is small (n={m['n_matched']}) and imbalanced. A single flipped claim moves",
        "> per-class F1 by double digits, so treat these as directional, not precise.",
        "",
        "### Confusion matrix",
        "",
        "Rows are ground truth, columns are predictions.",
        "",
        "| actual \\ predicted | " + " | ".join(CLASSES) + " |",
        "| :--- | " + " | ".join("---:" for _ in CLASSES) + " |",
    ]
    for gt in CLASSES:
        row = m["confusion"][gt]
        lines.append(f"| **{gt}** | " + " | ".join(str(row.get(p, 0)) for p in CLASSES) + " |")

    lines += ["", "## Misclassified claims", ""]
    if not m["mistakes"]:
        lines.append("None among the scored claims.")
    else:
        lines += [
            "| user_id | object | expected | predicted | severity (exp/pred) | justification |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for mistake in m["mistakes"]:
            just = mistake["justification"].replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {mistake['user_id']} | {mistake['claim_object']} | {mistake['expected']} | "
                f"{mistake['predicted']} | {mistake['expected_severity']}/{mistake['predicted_severity']} | {just} |"
            )

    with open(path, mode="w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    evaluate_predictions()
