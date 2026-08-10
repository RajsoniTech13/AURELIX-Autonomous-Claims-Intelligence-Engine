"""
The deterministic image-quality gate.

These tests exist because of a specific failure: the model was asked whether the photo it
had just analysed was good enough to analyse, said yes, and the rule engine believed it.
The gate takes that judgement away from the model. What must never regress is the
*direction* of the override — measurement can only make the assessment worse, never better.

Hermetic: images are constructed in memory or read from the committed fixture set. No API.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from agent_core.agents.image_quality import (
    QUALITY_RANK,
    UNMEASURED,
    assess_images,
    load_quality_config,
    measure_image,
    merge_quality,
)
from agent_core.agents.image_validator import preflight
from agent_core.rules_engine import decide, effective_quality
from agent_core.schemas.perception import (
    ClaimIntent,
    ClaimPerception,
    DamageAnalysis,
    ImageQualityFinding,
    ObservedDamage,
)
from agent_core.agents.alignment import compute_alignment

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


# ─── Image builders ─────────────────────────────────────────────────────────

def sharp_image(size=(600, 600), seed=0) -> Image.Image:
    """High-frequency noise: maximally in focus, mid-grey, correctly exposed."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(40, 215, (*size[::-1], 3), dtype=np.uint8), "RGB")


def flat_image(value: int, size=(600, 600)) -> Image.Image:
    """A single constant colour: zero detail, so zero Laplacian variance."""
    return Image.fromarray(np.full((*size[::-1], 3), value, dtype=np.uint8), "RGB")


# ─── Measurement ────────────────────────────────────────────────────────────

def test_sharp_well_exposed_image_measures_good():
    m = measure_image(sharp_image())
    assert m.band == "good"
    assert m.issues == []
    assert m.blur_variance > load_quality_config()["blur"]["poor_below"]


def test_uniform_image_is_unusable_for_blur():
    m = measure_image(flat_image(128))
    assert m.band == "unusable"
    assert "blurry" in m.issues
    assert m.blur_variance == pytest.approx(0.0)


def test_underexposed_image_is_unusable():
    m = measure_image(Image.eval(sharp_image(), lambda p: int(p * 0.15)))
    assert m.band == "unusable"
    assert "too_dark" in m.issues


def test_overexposed_image_is_unusable():
    m = measure_image(Image.eval(sharp_image(), lambda p: min(255, int(p * 0.3 + 220))))
    assert m.band == "unusable"
    assert "too_bright" in m.issues


def test_small_image_is_demoted_for_resolution():
    m = measure_image(sharp_image(size=(220, 220)))
    assert m.band == "poor"
    assert "low_resolution" in m.issues


def test_a_dark_subject_with_bright_highlights_is_not_called_underexposed():
    """
    The percentile guard earns its place here. A night photo of a dark car under a street
    lamp is correctly exposed; only a frame with no highlights at all is underexposed.
    """
    arr = np.asarray(sharp_image(), dtype=np.int16)
    arr = (arr * 0.28).astype(np.uint8)
    arr[:, :80] = 250                              # a small blown-out highlight region
    m = measure_image(Image.fromarray(arr, "RGB"))
    assert "too_dark" not in m.issues


# ─── Aggregation ────────────────────────────────────────────────────────────

def test_claim_quality_is_the_best_image_not_the_worst():
    """One clear photo is enough. Uploading extra bad ones must not be penalised."""
    q = assess_images([flat_image(128), sharp_image()], ["img_1", "img_2"])
    assert q.overall == "good"
    assert len(q.per_image) == 2


def test_no_images_yields_an_unmeasured_result():
    q = assess_images([], [])
    assert q.measured is False
    assert q is UNMEASURED


# ─── Override direction: the property that must never regress ───────────────

def test_gate_downgrades_an_over_confident_model():
    overall, score, issues = merge_quality("good", 95, ["none"], measure_image_quality_of_flat())
    assert overall == "unusable"
    assert score <= 10
    assert "blurry" in issues


def test_gate_never_upgrades_the_model():
    """
    The model can see things the gate cannot — a finger over the lens, a screenshot, the
    wrong object entirely. A sharp, well-exposed photograph of the wrong car is still
    unusable evidence, and optics must not promote it.
    """
    good_measurement = assess_images([sharp_image()], ["img_1"])
    assert good_measurement.overall == "good"

    overall, score, _ = merge_quality("unusable", 5, ["wrong_subject"], good_measurement)
    assert overall == "unusable"
    assert score == 5


def test_unmeasured_quality_changes_nothing():
    overall, score, issues = merge_quality("fair", 70, ["cropped"], UNMEASURED)
    assert (overall, score, issues) == ("fair", 70, ["cropped"])


def test_missing_perception_reads_as_unusable():
    assert effective_quality(None, None)[0] == "unusable"


def measure_image_quality_of_flat():
    return assess_images([flat_image(128)], ["img_1"])


# ─── End-to-end through the rule engine ─────────────────────────────────────

def _perception(quality: str, score: int) -> ClaimPerception:
    return ClaimPerception(
        claim_id="C1",
        observed_object="car",
        image_quality=ImageQualityFinding(overall=quality, score=score, issues=["none"]),
        claim_understanding=ClaimIntent(
            object_category="car", claimed_part="front_bumper",
            claimed_issue="dent", claimed_severity="medium",
        ),
        damage_analysis=DamageAnalysis(damage_detected=True, damaged_parts=[
            ObservedDamage(part="front_bumper", issue_type="dent", severity="medium",
                           image_id="img_1", visual_confidence=90),
        ]),
        claimed_part_visible=True,
        supporting_image_ids=["img_1"],
    )


def test_measured_unusable_overrides_a_confident_model_verdict():
    """
    Without the gate this is `supported`: the model reports good quality and damage on
    exactly the claimed part. With it, R003 fires and we admit we could not see.
    """
    perception = _perception("good", 95)
    alignment = compute_alignment(perception, "car")

    without = decide(alignment, perception)
    assert without.claim_status == "supported"

    with_gate = decide(alignment, perception, preflight_quality=measure_image_quality_of_flat())
    assert with_gate.claim_status == "not_enough_information"
    assert "R003_image_quality_unusable" in with_gate.rule_ids
    assert "blurry_image" in with_gate.risk_flags


def test_good_measurement_cannot_rescue_a_model_reported_failure():
    perception = _perception("unusable", 5)
    alignment = compute_alignment(perception, "car")
    verdict = decide(alignment, perception,
                     preflight_quality=assess_images([sharp_image()], ["img_1"]))
    assert verdict.claim_status == "not_enough_information"


def test_gate_lowers_confidence_rather_than_silently_passing():
    perception = _perception("good", 95)
    alignment = compute_alignment(perception, "car")
    gated = decide(alignment, perception, preflight_quality=measure_image_quality_of_flat())
    assert gated.confidence < decide(alignment, perception).confidence
    assert gated.manual_review_required


# ─── Thresholds live in config, not code ────────────────────────────────────

def test_thresholds_come_from_config(monkeypatch, tmp_path):
    """A tightened config must change behaviour without touching a line of Python."""
    cfg = tmp_path / "image_quality.yaml"
    cfg.write_text(
        "version: 1\n"
        "blur: {unusable_below: 100000.0, poor_below: 100000.0}\n"
        "exposure:\n"
        "  too_dark: {unusable_mean_below: 0.0, unusable_p95_below: 0.0, poor_mean_below: 0.0}\n"
        "  too_bright: {unusable_mean_above: 999.0, unusable_p05_above: 999.0, poor_mean_above: 999.0}\n"
        "resolution: {poor_min_side_below: 0}\n"
        "scores: {good: 90, fair: 70, poor: 35, unusable: 10}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AURELIX_IMAGE_QUALITY_CONFIG", str(cfg))
    load_quality_config.cache_clear()
    try:
        assert measure_image(sharp_image()).band == "unusable"
    finally:
        load_quality_config.cache_clear()


# ─── Regression guards on the dataset ───────────────────────────────────────

@pytest.mark.parametrize("claim_id,expected_band", [
    ("SYN-031", "unusable"),   # very_blurry
    ("SYN-032", "unusable"),   # dark
    ("SYN-033", "unusable"),   # low_res
    ("SYN-001", "good"),       # an ordinary, undegraded case
])
def test_degraded_fixtures_are_measurably_degraded(claim_id, expected_band):
    """
    Guards the render fix as much as the gate. `low_res` was previously produced by a
    NEAREST-filter upscale, whose blocky edges measure as *sharper* than the original —
    so an image labelled low resolution scored as a perfectly focused photograph.
    """
    path = REPO_ROOT / f"agent_core/data/synthetic/images/{claim_id}_img_1.jpg"
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    assert measure_image(Image.open(path)).band == expected_band


def test_preflight_returns_unmeasured_when_nothing_loads():
    validation, images, quality = preflight("does/not/exist.jpg", base_dir=str(REPO_ROOT))
    assert validation.valid is False
    assert images == []
    assert quality.measured is False


def test_quality_rank_ordering_is_total():
    assert QUALITY_RANK["unusable"] < QUALITY_RANK["poor"] < QUALITY_RANK["fair"] < QUALITY_RANK["good"]
