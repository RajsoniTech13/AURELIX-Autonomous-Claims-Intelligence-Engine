"""
The public entry point for analysing a single claim on the batched pipeline.

`run_pipeline.py` is the offline CLI: many claims, three to a request, checkpointed. This
module is the other consumer — the web platform, where a claim arrives on its own and a
person is waiting. Both go through the *same* perception and judgement code. A batch of one
is still a batch, and that is deliberate: the alternative is a second inference path that
drifts away from the one the benchmark measures, which is exactly the situation this phase
was created to end.

**Shape of the work.** One multimodal LLM call, then arithmetic:

    preflight (deterministic)  -> validate, decode, measure blur/exposure
    perception (ONE LLM call)  -> what is in the images, what does the claimant assert
    policy_verification        -> deterministic, CSV rules
    user_risk                  -> deterministic, claim history
    alignment                  -> deterministic, claimed vs observed
    decision                   -> deterministic, fraud + confidence + ordered rules

Only the second step reaches the network. Everything after it is a pure function of stored
perception, which is why re-deriving a verdict costs nothing.

**One code path, two interfaces.** `analyse_claim` is defined in terms of
`analyse_claim_events` rather than duplicating the sequence. The previous backend kept its
own copy of the graph's routing logic for the progress stream, and the copy had already
drifted out of sync with the real router.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from PIL import Image

from agent_core.agents.alignment import AlignmentResult, compute_alignment
from agent_core.agents.image_quality import UNMEASURED, PreflightQuality, assess_images
from agent_core.agents.image_validator import preflight, run_image_validator
from agent_core.agents.perception import (
    BatchIsolationError,
    PreparedClaim,
    run_batch_perception,
)
from agent_core.agents.policy_verification import run_policy_verification_agent
from agent_core.agents.user_risk import run_user_risk_agent
from agent_core.rules_engine import Verdict, decide, effective_quality
from agent_core.schemas.contract import (
    ISSUE_TYPE_VALUES,
    OBJECT_PART_VALUES,
    SEVERITY_VALUES,
    coerce_to_vocabulary,
    image_id,
    join_multi,
    to_bool_str,
)
from agent_core.schemas.models import ImageValidatorOutput
from agent_core.schemas.perception import ClaimPerception
from agent_core.services.config import batching_config
from agent_core.services.gemini_client import DailyQuotaExhausted, LLMUnavailableError

# The ordered stages a caller can expect to see. Exported so the API and the UI cannot
# invent their own list and drift; the guardrail tests assert this is what actually runs.
PIPELINE_STAGES: tuple[str, ...] = (
    "preflight",
    "perception",
    "policy_verification",
    "user_risk",
    "alignment",
    "decision",
)

LLM_STAGES: frozenset[str] = frozenset({"perception"})
"""The stages that reach the network. Exactly one, and that is the point."""


@dataclass
class ClaimAnalysis:
    """Everything one claim produced, model observations and deterministic judgement alike."""
    claim_id: str
    verdict: Verdict
    output_row: Dict[str, str]
    perception: Optional[ClaimPerception] = None
    alignment: Optional[AlignmentResult] = None
    preflight_quality: PreflightQuality = field(default_factory=lambda: UNMEASURED)
    validation: Optional[ImageValidatorOutput] = None
    policy: Optional[Any] = None
    user_risk: Optional[Any] = None
    llm_requests: int = 0
    error: Optional[str] = None
    timeline: List[Dict[str, str]] = field(default_factory=list)


# ─── Judgement: a pure function of stored perception ────────────────────────

def judge(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Alignment + rules for one claim. No LLM, fully reproducible.

    Kept separate from perception because that separation is what lets a rule or ontology
    fix be evaluated across the whole benchmark without spending a single request.
    """
    perception = entry.get("perception")
    row = entry["row"]
    quality = entry.get("preflight_quality") or UNMEASURED

    alignment = compute_alignment(perception, row.get("claim_object", "")) if perception else None

    verdict = decide(
        alignment, perception,
        no_usable_image=entry.get("no_usable_image", False),
        perception_failed=entry.get("perception_failed", False),
        duplicate_image_reuse=entry.get("duplicate_image_reuse", False),
        user_history_risk=entry.get("user_history_risk", False),
        extra_risk_flags=list(getattr(entry.get("validation"), "risk_flags", []) or []),
        preflight_quality=quality,
    )

    return {
        "claim_id": entry["claim_id"],
        "row": row,
        "perception": perception,
        "preflight_quality": quality,
        "alignment": alignment,
        "verdict": verdict,
        "batch_id": entry.get("batch_id"),
        "model": entry.get("model"),
        "error": entry.get("error"),
    }


def to_output_row(result: Dict[str, Any]) -> Dict[str, str]:
    """Render one judged claim into the frozen 14-column contract."""
    row, perception, verdict = result["row"], result["perception"], result["verdict"]
    alignment = result["alignment"]

    issue_type, object_part, severity = "unknown", "unknown", "unknown"
    supporting: List[str] = []
    if perception:
        damages = perception.damage_analysis.damaged_parts
        chosen = None
        if alignment and alignment.matched_part:
            chosen = next((d for d in damages if d.part == alignment.matched_part), None)
        chosen = chosen or (damages[0] if damages else None)
        if chosen:
            issue_type = coerce_to_vocabulary(chosen.issue_type, ISSUE_TYPE_VALUES, "unknown")
            object_part = coerce_to_vocabulary(chosen.part, OBJECT_PART_VALUES, "unknown")
            severity = coerce_to_vocabulary(chosen.severity, SEVERITY_VALUES, "unknown")
        elif perception.claimed_part_visible:
            issue_type, severity = "none", "none"
        supporting = [s for s in perception.supporting_image_ids if s.startswith("img_")]

    # Quality here is the gated value, not the model's self-report: the CSV must agree with
    # the verdict, and the verdict was reached on the measured figure.
    band, score, _ = effective_quality(perception, result.get("preflight_quality"))
    evidence_met = bool(perception and band in ("good", "fair"))
    if not perception:
        evidence_reason = "No usable image evidence was submitted with this claim."
    elif band != perception.image_quality.overall:
        evidence_reason = (
            f"Image quality measured {band} (score {score}) by deterministic preflight, "
            f"overriding the model's assessment of {perception.image_quality.overall}."
        )
    else:
        evidence_reason = f"Image quality assessed {band} (score {score})."

    return {
        "user_id": row.get("user_id", ""),
        "image_paths": row.get("image_paths", ""),
        "user_claim": row.get("user_claim", ""),
        "claim_object": row.get("claim_object", ""),
        "evidence_standard_met": to_bool_str(evidence_met),
        "evidence_standard_met_reason": evidence_reason,
        "risk_flags": join_multi(verdict.risk_flags, empty="none"),
        "issue_type": issue_type,
        "object_part": object_part,
        "claim_status": verdict.claim_status,
        "claim_status_justification": verdict.justification,
        "supporting_image_ids": join_multi(supporting, empty="none"),
        "valid_image": to_bool_str(bool(perception)),
        "severity": severity,
    }


# ─── Single-claim analysis ──────────────────────────────────────────────────

def analyse_claim_events(
    *,
    user_id: str,
    user_claim: str,
    claim_object: str,
    image_paths: str = "",
    images: Optional[Sequence[Image.Image]] = None,
    image_base_dir: Optional[str] = None,
    user_history: Optional[Dict[str, Any]] = None,
    evidence_rules: Optional[Dict[str, Any]] = None,
    claim_id: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    """
    Analyse one claim, yielding a progress event per stage.

    Events are `{"stage": ..., "status": "running"|"complete"}` while work is in flight, and
    the final event is `{"stage": "done", "analysis": ClaimAnalysis}`. Callers that do not
    care about progress should use `analyse_claim`.

    Two image supply modes, matching the two front doors: decoded `images` for a web upload,
    or `image_paths` resolved against `image_base_dir` for a CSV row.
    """
    cid = claim_id or user_id
    row = {
        "user_id": user_id, "image_paths": image_paths,
        "user_claim": user_claim, "claim_object": claim_object,
    }
    timeline: List[Dict[str, str]] = []

    def emit(stage: str, status: str) -> Dict[str, Any]:
        event = {"stage": stage, "status": status}
        if status == "complete":
            timeline.append({"stage": stage, "status": status})
        return event

    # ── preflight: deterministic, and the only thing that can stop an LLM call ──
    yield emit("preflight", "running")
    max_images = batching_config()["max_images_per_claim"]
    if images:
        validation = run_image_validator(images=list(images))
        usable = list(images)[:max_images]
        quality = assess_images(usable, [image_id(i) for i in range(len(usable))])
    else:
        validation, usable, quality = preflight(
            image_paths, base_dir=image_base_dir, max_images=max_images,
        )
    yield emit("preflight", "complete")

    # ── perception: the one network call ──
    perception: Optional[ClaimPerception] = None
    perception_failed = False
    error: Optional[str] = None
    llm_requests = 0

    if not validation.valid:
        # No usable evidence means no grounded finding is possible, so a request here would
        # buy nothing. This is the single biggest quota saver in the system.
        yield emit("perception", "skipped")
    else:
        yield emit("perception", "running")
        prepared = PreparedClaim(
            claim_id=cid, claim_object=claim_object, claim_text=user_claim,
            images=usable, raw=row,
        )
        try:
            perception = run_batch_perception([prepared]).get(cid)
            llm_requests = 1
            if perception is None:
                perception_failed = True
                error = "perception returned no result for this claim"
        except (BatchIsolationError, LLMUnavailableError, DailyQuotaExhausted) as e:
            # Never fabricate. A failure here becomes a real not_enough_information with the
            # cause attached, which is what the rule engine turns into an honest verdict.
            perception_failed = True
            error = f"{type(e).__name__}: {e}"
        yield emit("perception", "complete" if not perception_failed else "failed")

    # ── deterministic context: neither of these has ever been an LLM call ──
    yield emit("policy_verification", "running")
    policy = run_policy_verification_agent(
        claim_object=claim_object,
        claimed_part=(perception.claim_understanding.claimed_part if perception else "unknown"),
        image_paths=image_paths,
        image_valid=validation.valid,
        image_issues=list(validation.issues),
        evidence_rules=evidence_rules,
    )
    yield emit("policy_verification", "complete")

    yield emit("user_risk", "running")
    user_risk = run_user_risk_agent(user_id=user_id, user_history=user_history)
    yield emit("user_risk", "complete")

    # ── judgement ──
    yield emit("alignment", "running")
    yield emit("alignment", "complete")

    yield emit("decision", "running")
    judged = judge({
        "claim_id": cid, "row": row, "perception": perception,
        "preflight_quality": quality, "validation": validation,
        "no_usable_image": not validation.valid,
        "perception_failed": perception_failed,
        "user_history_risk": "user_history_risk" in (user_risk.risk_flags or []),
        "error": error,
    })
    yield emit("decision", "complete")

    yield {
        "stage": "done",
        "status": "complete",
        "analysis": ClaimAnalysis(
            claim_id=cid,
            verdict=judged["verdict"],
            output_row=to_output_row(judged),
            perception=perception,
            alignment=judged["alignment"],
            preflight_quality=quality,
            validation=validation,
            policy=policy,
            user_risk=user_risk,
            llm_requests=llm_requests,
            error=error,
            timeline=timeline,
        ),
    }


def analyse_claim(**kwargs: Any) -> ClaimAnalysis:
    """Analyse one claim and return the result. Progress events are discarded."""
    analysis: Optional[ClaimAnalysis] = None
    for event in analyse_claim_events(**kwargs):
        if event["stage"] == "done":
            analysis = event["analysis"]
    assert analysis is not None, "analyse_claim_events must always finish with a done event"
    return analysis
