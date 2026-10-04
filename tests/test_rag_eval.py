"""
The retrieval metrics and the golden set behind `evaluation/rag/report.md`.

A metric with an off-by-one reports a number nobody can trust, and the numbers in the
report are the reason the embedding model was chosen. So each metric is checked against a
hand-computed value, and the golden set against the policy it labels.
"""
from __future__ import annotations

import math

import pytest

from agent_core.evaluation.evaluate_rag import (
    best_threshold,
    leave_one_out,
    load_golden,
    ndcg_at,
    recall_at,
    reciprocal_rank,
)
from agent_core.retrieval.policy_corpus import parse_policy


def test_recall_at_k_is_the_share_of_gold_found():
    assert recall_at(["A", "B", "C"], ["B"], 1) == 0.0
    assert recall_at(["A", "B", "C"], ["B"], 3) == 1.0
    assert recall_at(["A", "B", "C"], ["A", "C", "Z"], 3) == pytest.approx(2 / 3)


def test_reciprocal_rank_uses_the_first_gold_hit():
    assert reciprocal_rank(["A", "B", "C"], ["C", "B"]) == 0.5
    assert reciprocal_rank(["A"], ["Z"]) == 0.0


def test_ndcg_matches_a_hand_computation():
    # gold at ranks 1 and 3 of 2 gold: (1 + 1/log2(4)) / (1 + 1/log2(3))
    expected = (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert ndcg_at(["A", "X", "B"], ["A", "B"], 5) == pytest.approx(expected)
    assert ndcg_at(["A", "B"], ["A", "B"], 5) == pytest.approx(1.0)


def test_the_threshold_separates_when_it_can_and_prefers_not_refusing():
    scores = [0.9, 0.8, 0.3, 0.2]
    labels = [True, True, False, False]
    t, correct = best_threshold(scores, labels)
    assert correct == 4 and 0.3 < t <= 0.8
    # Overlap: no cut is perfect; the best one is reported honestly.
    _, correct = best_threshold([0.9, 0.4, 0.5, 0.2], [True, True, False, False])
    assert correct == 3


def test_leave_one_out_never_beats_in_sample():
    scores = [0.9, 0.85, 0.62, 0.61, 0.6, 0.3, 0.2]
    labels = [True, True, True, False, True, False, False]
    _, in_sample = best_threshold(scores, labels)
    assert leave_one_out(scores, labels) <= in_sample


def test_the_golden_set_is_the_shape_the_report_claims():
    rows = load_golden()
    assert len(rows) == 40
    assert sum(1 for r in rows if not r["gold"]) == 8
    assert {r["type"] for r in rows} == {"exact", "paraphrase", "multi", "unanswerable"}
    assert len({r["id"] for r in rows}) == 40
    clause_ids = {c.clause_id for c in parse_policy()}
    assert {g for r in rows for g in r["gold"]} <= clause_ids
    assert all(len(r["gold"]) >= 2 for r in rows if r["type"] == "multi")


def test_the_live_evaluation_refuses_to_spend_without_the_flag(monkeypatch, capsys):
    import sys
    from agent_core.evaluation import evaluate_copilot
    monkeypatch.setattr(sys, "argv", ["evaluate_copilot"])
    assert evaluate_copilot.main() == 2
    assert "Refusing" in capsys.readouterr().out
