"""
Confidence intervals and the regression gate on the synthetic benchmark.

The interval is only meaningful if it is computed from the same metric the headline reports,
and the CI gate only protects anything if it fails when it should. Both are checked here,
from stored perception — no API calls.
"""
from __future__ import annotations

import pytest

from agent_core.evaluation.evaluate_synthetic import bootstrap_ci, main, score


def test_score_is_accuracy_and_three_class_macro_f1():
    pairs = [("supported", "supported"), ("contradicted", "contradicted"),
             ("not_enough_information", "supported")]
    accuracy, macro = score(pairs)
    assert accuracy == pytest.approx(2 / 3)
    # supported: p=1/2 r=1 f1=2/3; contradicted: f1=1; NEI: f1=0  → mean 5/9
    assert macro == pytest.approx((2 / 3 + 1 + 0) / 3)


def test_the_interval_contains_the_estimate_and_is_reproducible():
    pairs = [("supported", "supported")] * 18 + [("contradicted", "contradicted")] * 16 \
        + [("not_enough_information", "not_enough_information")] * 7 \
        + [("contradicted", "supported"), ("contradicted", "not_enough_information"),
           ("supported", "contradicted")]
    accuracy, macro = score(pairs)
    a = bootstrap_ci(pairs, resamples=2000, seed=3)
    b = bootstrap_ci(pairs, resamples=2000, seed=3)
    assert a == b
    assert a["accuracy"][0] <= accuracy <= a["accuracy"][1]
    assert a["macro_f1"][0] <= macro <= a["macro_f1"][1]
    assert a["accuracy"][1] - a["accuracy"][0] > 0.05      # 44 cases cannot give a tight interval


def test_a_perfect_sample_has_a_degenerate_interval():
    pairs = [("supported", "supported"), ("contradicted", "contradicted"),
             ("not_enough_information", "not_enough_information")] * 5
    ci = bootstrap_ci(pairs, resamples=500)
    assert ci["accuracy"] == (1.0, 1.0)


def test_the_regression_gate_passes_and_fails(capsys):
    assert main(["--min-macro-f1", "0.93"]) == 0
    assert main(["--min-macro-f1", "0.999"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_the_committed_report_carries_no_absolute_path():
    from pathlib import Path
    report = (Path(__file__).resolve().parents[1] / "agent_core/output/evaluation_report.md").read_text()
    assert "/Users/" not in report and "/home/" not in report
