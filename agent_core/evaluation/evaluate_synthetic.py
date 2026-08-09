"""
Evaluate pipeline output against the synthetic ground truth.

Reports overall and per-class precision/recall/F1, the confusion matrix, and — the part
that actually drives the next iteration — **per-category** performance. Aggregate accuracy
hides which failure mode is broken; a system that is perfect on honest claims and blind to
part mismatches can still post a respectable overall number.

Ground truth is loaded here and only here. It never touches a prompt.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

CLASSES = ("supported", "contradicted", "not_enough_information")


def load_ground_truth(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return {r["claim_id"]: r for r in csv.DictReader(f)}


def load_predictions(results_json: Path) -> Dict[str, Dict[str, Any]]:
    data = json.loads(results_json.read_text(encoding="utf-8"))
    return {r["claim_id"]: r for r in data}


def evaluate(gt_path: Path, results_path: Path, report_path: Path) -> Dict[str, Any]:
    truth = load_ground_truth(gt_path)
    preds = load_predictions(results_path)

    scored, unscored = [], []
    for cid, g in truth.items():
        p = preds.get(cid)
        if not p or p.get("error"):
            unscored.append((cid, g, (p or {}).get("error", "no prediction")))
            continue
        scored.append((cid, g, p))

    confusion = {a: Counter() for a in CLASSES}
    by_category: Dict[str, List[bool]] = defaultdict(list)
    failures: List[Dict[str, str]] = []

    for cid, g, p in scored:
        expected = g["expected_status"]
        got = p["verdict"]["claim_status"]
        confusion[expected][got] += 1
        ok = expected == got
        by_category[g["category"]].append(ok)
        if not ok:
            al = p.get("alignment") or {}
            failures.append({
                "claim_id": cid, "category": g["category"],
                "expected": expected, "got": got,
                "truth_part": g["truth_part"], "truth_severity": g["truth_severity"],
                "part_match": al.get("part_match", "-"),
                "object_match": al.get("object_match", "-"),
                "severity_delta": str(al.get("severity_delta")),
                "observed": ",".join(al.get("observed_parts") or []) or "-",
                "rules": ",".join(p["verdict"].get("rule_ids") or []),
            })

    n = len(scored)
    correct = sum(confusion[c][c] for c in CLASSES)

    per_class = {}
    for c in CLASSES:
        tp = confusion[c][c]
        fp = sum(confusion[o][c] for o in CLASSES if o != c)
        fn = sum(confusion[c][o] for o in CLASSES if o != c)
        support = sum(confusion[c].values())
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[c] = {"tp": tp, "fp": fp, "fn": fn, "support": support,
                        "precision": prec, "recall": rec, "f1": f1}

    macro_f1 = sum(m["f1"] for m in per_class.values()) / len(CLASSES)
    weighted_f1 = (
        sum(m["f1"] * m["support"] for m in per_class.values()) / n if n else 0.0
    )

    metrics = {
        "n_total": len(truth), "n_scored": n, "n_unscored": len(unscored),
        "accuracy": correct / n if n else 0.0,
        "macro_f1": macro_f1, "weighted_f1": weighted_f1,
        "per_class": per_class,
        "confusion": {a: dict(row) for a, row in confusion.items()},
        "by_category": {k: (sum(v), len(v)) for k, v in sorted(by_category.items())},
        "failures": failures,
        "unscored": [(c, e) for c, _, e in unscored],
        "confidence": [p["verdict"]["confidence"] for _, _, p in scored],
        "fraud": [p["verdict"]["fraud_score"] for _, _, p in scored],
    }
    _write(report_path, metrics, gt_path, results_path)
    return metrics


def _write(path: Path, m: Dict[str, Any], gt_path: Path, results_path: Path) -> None:
    pc, L = m["per_class"], []
    A = L.append

    A("# AURELIX — Evaluation Report (synthetic benchmark)")
    A("")
    A("> **SYNTHETIC DEVELOPMENT/EVALUATION DATA.** Every claim narrative is invented and")
    A("> every image is a procedurally generated illustration. These figures measure the")
    A("> pipeline against known labels; they are **not** a prediction of accuracy on real")
    A("> claim photographs, which bring lighting, occlusion, reflections and motion blur")
    A("> that this set does not contain.")
    A("")
    A(f"- Ground truth: `{gt_path}`")
    A(f"- Predictions: `{results_path}`")
    A("")
    A("## Headline")
    A("")
    A("| metric | value |")
    A("| :--- | ---: |")
    A(f"| Cases scored | {m['n_scored']} / {m['n_total']} |")
    A(f"| **Accuracy** | **{m['accuracy']:.1%}** |")
    A(f"| Macro F1 | {m['macro_f1']:.1%} |")
    A(f"| Weighted F1 | {m['weighted_f1']:.1%} |")
    if m["confidence"]:
        A(f"| Mean confidence | {sum(m['confidence']) / len(m['confidence']):.0f} |")
        A(f"| Mean fraud score | {sum(m['fraud']) / len(m['fraud']):.0f} |")
    A("")
    if m["n_unscored"]:
        A(f"> {m['n_unscored']} case(s) produced no usable prediction and are excluded from")
        A("> every figure above. They are listed at the end.")
        A("")

    A("## Per class")
    A("")
    A("| class | support | TP | FP | FN | precision | recall | F1 |")
    A("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for c in CLASSES:
        d = pc[c]
        A(f"| {c} | {d['support']} | {d['tp']} | {d['fp']} | {d['fn']} | "
          f"{d['precision']:.1%} | {d['recall']:.1%} | {d['f1']:.1%} |")
    A("")

    A("## Confusion matrix")
    A("")
    A("Rows are ground truth, columns are predictions.")
    A("")
    A("| actual \\ predicted | " + " | ".join(CLASSES) + " |")
    A("| :--- | " + " | ".join("---:" for _ in CLASSES) + " |")
    for a in CLASSES:
        A(f"| **{a}** | " + " | ".join(str(m["confusion"][a].get(p, 0)) for p in CLASSES) + " |")
    A("")

    A("## By failure category")
    A("")
    A("The number that matters: aggregate accuracy hides which specific failure mode is broken.")
    A("")
    A("| category | correct | total | rate |")
    A("| :--- | ---: | ---: | ---: |")
    for cat, (ok, tot) in m["by_category"].items():
        A(f"| {cat} | {ok} | {tot} | {ok / tot:.0%} |")
    A("")

    A("## Notable failures")
    A("")
    if not m["failures"]:
        A("None among the scored cases.")
    else:
        A("| claim | category | expected | got | part_match | object_match | Δsev | observed | rules |")
        A("| :--- | :--- | :--- | :--- | :--- | :--- | ---: | :--- | :--- |")
        for f in m["failures"]:
            A(f"| {f['claim_id']} | {f['category']} | {f['expected']} | {f['got']} | "
              f"{f['part_match']} | {f['object_match']} | {f['severity_delta']} | "
              f"{f['observed']} | {f['rules']} |")
    A("")

    if m["unscored"]:
        A("## Unscored cases")
        A("")
        A("| claim | reason |")
        A("| :--- | :--- |")
        for cid, err in m["unscored"]:
            A(f"| {cid} | {str(err)[:150]} |")
        A("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    m = evaluate(
        root / "agent_core/data/synthetic/ground_truth.csv",
        root / "agent_core/output/results_detail.json",
        root / "agent_core/output/evaluation_report.md",
    )
    print(f"Scored {m['n_scored']}/{m['n_total']}  accuracy {m['accuracy']:.1%}  "
          f"macro-F1 {m['macro_f1']:.1%}")
    for cat, (ok, tot) in m["by_category"].items():
        print(f"  {cat:26s} {ok}/{tot}")


if __name__ == "__main__":
    main()
