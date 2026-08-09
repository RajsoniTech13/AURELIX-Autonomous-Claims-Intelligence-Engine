"""
Deterministic rule engine: fraud score, confidence, verdict, escalation.

No LLM is involved in any decision here. Given the same perception record, this produces
the same verdict every time, and every verdict names the rule that produced it. That is what
makes an insurance decision defensible: "R040_part_mismatch fired because damage was observed
on the rear bumper while the claim named the front bumper" is an answer; "the model said so"
is not.

Thresholds live in `config/decision_rules.yaml`, so tuning them is a config change and can be
grid-searched against a labelled set rather than argued about.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from agent_core.agents.alignment import AlignmentResult
from agent_core.agents.image_quality import PreflightQuality, merge_quality
from agent_core.schemas.contract import normalise_risk_flags
from agent_core.schemas.perception import ClaimPerception

_RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "decision_rules.yaml"


def effective_quality(
    perception: Optional[ClaimPerception],
    preflight_quality: Optional[PreflightQuality] = None,
) -> tuple[str, int, List[str]]:
    """
    The image quality the rules actually act on: the model's self-report, floored by the
    deterministic preflight measurement.

    Everything below reads quality through this function rather than off `perception`
    directly. The model's own words stay untouched in the perception record — that is the
    audit trail of what it claimed to see — but they never get the final say on whether it
    could see at all.
    """
    quality = perception.image_quality if perception else None
    return merge_quality(
        quality.overall if quality else None,
        quality.score if quality else None,
        quality.issues if quality else None,
        preflight_quality,
    )


@lru_cache(maxsize=1)
def load_rules(path: str | None = None) -> Dict[str, Any]:
    with open(path or _RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class Verdict:
    claim_status: str
    confidence: int
    fraud_score: int
    rule_ids: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    justification: str = ""
    manual_review_required: bool = False
    escalation_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "claim_status": self.claim_status,
            "confidence": self.confidence,
            "fraud_score": self.fraud_score,
            "rule_ids": self.rule_ids,
            "risk_flags": self.risk_flags,
            "justification": self.justification,
            "manual_review_required": self.manual_review_required,
            "escalation_reason": self.escalation_reason,
        }


# ─── Facts ──────────────────────────────────────────────────────────────────

def build_facts(
    alignment: Optional[AlignmentResult],
    perception: Optional[ClaimPerception],
    *,
    no_usable_image: bool = False,
    perception_failed: bool = False,
    duplicate_image_reuse: bool = False,
    user_history_risk: bool = False,
    fraud_score: int = 0,
    preflight_quality: Optional[PreflightQuality] = None,
) -> Dict[str, Any]:
    """Flatten everything the rules may test into one dict."""
    quality, _, _ = effective_quality(perception, preflight_quality)
    return {
        "no_usable_image": no_usable_image,
        "perception_failed": perception_failed,
        "image_quality": quality,
        "object_match": alignment.object_match if alignment else "unknown",
        "part_match": alignment.part_match if alignment else "unknown",
        "severity_delta": alignment.severity_delta if alignment else None,
        "damage_detected": alignment.damage_detected if alignment else False,
        "duplicate_image_reuse": duplicate_image_reuse,
        "user_history_risk": user_history_risk,
        "instruction_like_text": bool(perception and perception.instruction_like_text_present),
        "fraud_score": fraud_score,
    }


def _matches(condition: Dict[str, Any], facts: Dict[str, Any]) -> bool:
    """
    Evaluate one rule condition. All clauses must hold.

    Supported forms: `always`, direct equality, `<field>_in` (membership),
    `<field>_gte` / `<field>_lte` (numeric, None never matches).
    """
    for key, expected in condition.items():
        if key == "always":
            continue
        if key.endswith("_in"):
            if facts.get(key[:-3]) not in expected:
                return False
        elif key.endswith("_gte"):
            actual = facts.get(key[:-4])
            if actual is None or actual < expected:
                return False
        elif key.endswith("_lte"):
            actual = facts.get(key[:-4])
            if actual is None or actual > expected:
                return False
        else:
            if facts.get(key) != expected:
                return False
    return True


# ─── Fraud ──────────────────────────────────────────────────────────────────

def compute_fraud_score(
    alignment: Optional[AlignmentResult],
    perception: Optional[ClaimPerception],
    *,
    duplicate_image_reuse: bool = False,
    user_history_risk: bool = False,
    preflight_quality: Optional[PreflightQuality] = None,
) -> tuple[int, List[str]]:
    """Additive score over objective signals only. Returns (score, signal names)."""
    cfg = load_rules()["fraud"]
    weights = cfg["signals"]
    score = cfg["base_score"]
    fired: List[str] = []

    def add(signal: str) -> None:
        nonlocal score
        score += weights.get(signal, 0)
        fired.append(signal)

    if duplicate_image_reuse:
        add("duplicate_image_reuse")
    if user_history_risk:
        add("user_history_risk")
    if perception and perception.instruction_like_text_present:
        add("instruction_like_text")
    quality, _, _ = effective_quality(perception, preflight_quality)
    if perception and quality in ("poor", "unusable"):
        add("poor_image_quality")

    if alignment:
        if alignment.object_match == "mismatch":
            add("object_mismatch")
        if alignment.part_match == "mismatch" and alignment.damage_detected:
            add("part_mismatch_with_damage_elsewhere")
        if alignment.severity_inflated:
            add("severity_inflation")

    return min(score, 100), fired


# ─── Confidence ─────────────────────────────────────────────────────────────

_QUALITY_SCORE = {"good": 100, "fair": 70, "poor": 35, "unusable": 0}

# Quality diagnostics -> the frozen 10-value risk_flags vocabulary. The grader has one
# flag for "the photograph itself is the problem", so exposure and resolution faults
# land on `blurry_image` alongside genuine defocus. Losing that distinction in the CSV
# is acceptable; inventing an eleventh flag value is not.
_QUALITY_ISSUE_FLAGS: Dict[str, tuple[str, ...]] = {
    "blurry": ("blurry_image",),
    "too_dark": ("blurry_image",),
    "too_bright": ("blurry_image",),
    "low_resolution": ("blurry_image",),
    "cropped": ("cropped_or_obstructed",),
    "obstructed": ("cropped_or_obstructed",),
    "screenshot": ("possible_manipulation",),
    "wrong_subject": ("claim_mismatch",),
}


def compute_confidence(
    alignment: Optional[AlignmentResult],
    perception: Optional[ClaimPerception],
    *,
    no_usable_image: bool = False,
    perception_failed: bool = False,
    preflight_quality: Optional[PreflightQuality] = None,
) -> int:
    """
    Documented weighted blend. Low confidence routes to human review rather than
    silently weakening a verdict.
    """
    cfg = load_rules()["confidence"]
    if perception_failed:
        return 0
    if no_usable_image or perception is None or alignment is None:
        return max(0, 100 - cfg["penalties"]["no_usable_image"])

    w = cfg["weights"]

    damages = perception.damage_analysis.damaged_parts
    visual = (sum(d.visual_confidence for d in damages) / len(damages)) if damages else 50.0
    quality_band, quality_score, _ = effective_quality(perception, preflight_quality)
    quality = float(quality_score or _QUALITY_SCORE.get(quality_band, 50))
    part_strength = float(cfg["part_match_strength"].get(alignment.part_match, 50))

    if alignment.severity_delta is None:
        severity_agreement = 30.0      # unmeasurable, not agreeing
    else:
        severity_agreement = max(0.0, 100.0 - abs(alignment.severity_delta) * 35.0)

    score = (
        visual * w["visual_confidence"]
        + quality * w["image_quality"]
        + part_strength * w["part_match_strength"]
        + severity_agreement * w["severity_agreement"]
    )
    return int(round(max(0.0, min(100.0, score))))


# ─── Decision ───────────────────────────────────────────────────────────────

def decide(
    alignment: Optional[AlignmentResult],
    perception: Optional[ClaimPerception],
    *,
    no_usable_image: bool = False,
    perception_failed: bool = False,
    duplicate_image_reuse: bool = False,
    user_history_risk: bool = False,
    extra_risk_flags: Optional[List[str]] = None,
    preflight_quality: Optional[PreflightQuality] = None,
) -> Verdict:
    """Run the ordered rules. First match wins; its rule_id is recorded."""
    rules = load_rules()

    fraud_score, fraud_signals = compute_fraud_score(
        alignment, perception,
        duplicate_image_reuse=duplicate_image_reuse,
        user_history_risk=user_history_risk,
        preflight_quality=preflight_quality,
    )
    confidence = compute_confidence(
        alignment, perception,
        no_usable_image=no_usable_image, perception_failed=perception_failed,
        preflight_quality=preflight_quality,
    )
    facts = build_facts(
        alignment, perception,
        no_usable_image=no_usable_image, perception_failed=perception_failed,
        duplicate_image_reuse=duplicate_image_reuse, user_history_risk=user_history_risk,
        fraud_score=fraud_score, preflight_quality=preflight_quality,
    )

    matched = next(r for r in rules["rules"] if _matches(r["when"], facts))

    risk_flags = list(matched.get("risk_flags") or []) + list(extra_risk_flags or [])
    if user_history_risk:
        risk_flags.append("user_history_risk")
    if perception and perception.instruction_like_text_present:
        risk_flags.append("text_instruction_present")
    if perception:
        _, _, quality_issues = effective_quality(perception, preflight_quality)
        for issue in quality_issues:
            risk_flags.extend(_QUALITY_ISSUE_FLAGS.get(issue, ()))

    # ── escalation ──
    esc = rules["escalation"]
    reasons: List[str] = []
    if confidence < esc["confidence_below"]:
        reasons.append(f"confidence {confidence} below {esc['confidence_below']}")
    if matched["verdict"] in esc["always_review_verdicts"]:
        reasons.append(f"verdict '{matched['verdict']}' always requires review")
    for flag in esc["always_review_flags"]:
        if flag in risk_flags:
            reasons.append(f"risk flag '{flag}' present")
    if fraud_score >= rules["fraud"]["review_threshold"]:
        reasons.append(f"fraud score {fraud_score} at or above review threshold")

    needs_review = bool(reasons)
    if needs_review:
        risk_flags.append("manual_review_required")

    # ── justification ──
    parts = [matched["reason"]]
    if alignment and alignment.notes:
        parts.append(" ".join(n[0].upper() + n[1:] + "." for n in alignment.notes[:2]))
    if perception and perception.supporting_image_ids:
        parts.append(f"Evidence: {', '.join(perception.supporting_image_ids)}.")
    parts.append(f"[{matched['id']}]")

    return Verdict(
        claim_status=matched["verdict"],
        confidence=confidence,
        fraud_score=fraud_score,
        rule_ids=[matched["id"]] + [f"FRAUD:{s}" for s in fraud_signals],
        risk_flags=normalise_risk_flags(risk_flags),
        justification=" ".join(parts),
        manual_review_required=needs_review,
        escalation_reason="; ".join(reasons) if reasons else None,
    )
