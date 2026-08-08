"""
AURELIX v2 — LangGraph StateGraph orchestrator.

Topology (fan-out/fan-in with conditional routing):

    Image Validator
         │
         ├── (if invalid) → short-circuit to rejected DecisionOutput
         │
         ▼
    Claim Ingestion
         │
         ├────────────┬────────────┬────────────┐
         ▼            ▼            ▼            ▼
    Vision       Policy       Similar       User Risk
    Analysis     Verification Claims        
         │            │            │            │
         └────────────┴─────┬──────┴────────────┘
                            ▼
                      Fraud Review
                            │
                            ▼
                        Decision
                            │
                            ▼
                           END

Design decisions:
- Conditional edge after Image Validator: if validation fails, skip everything (feedback #2).
- Parallel fan-out: Vision, Policy, Similar Claims, User Risk run simultaneously.
- Branch failure handling: each parallel node is wrapped in try/except and returns a
  BranchFailureOutput on error. Fraud/Decision prompts are told to treat "failed" branches
  as unknown (feedback #4).
- No node mutates another node's prior output.
"""
from typing import TypedDict, List, Dict, Any, Annotated
from operator import add
import traceback
from datetime import datetime, timezone

from langgraph.graph import StateGraph, END

from agent_core.schemas.models import BranchFailureOutput, DecisionOutput
from agent_core.services.gemini_client import LLMUnavailableError

# Agent imports
from agent_core.agents.image_validator import run_image_validator
from agent_core.agents.vision_analysis import cannot_assess
from agent_core.agents.claim_ingestion import run_claim_ingestion_agent
from agent_core.agents.vision_analysis import run_vision_analysis_agent
from agent_core.agents.policy_verification import run_policy_verification_agent
from agent_core.agents.similar_claims import run_similar_claims_agent
from agent_core.agents.user_risk import run_user_risk_agent
from agent_core.agents.fraud_review import run_fraud_review_agent
from agent_core.agents.decision import run_decision_agent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── LangGraph State ────────────────────────────────────────────────────────

class ClaimsState(TypedDict):
    # Inputs
    user_id: str
    image_paths: str
    user_claim: str
    claim_object: str
    user_history: Dict[str, Any]
    evidence_rules: Dict[str, Any]
    images: List[Any]  # PIL Image objects
    image_base_dir: str  # root that relative image_paths resolve against

    # Agent outputs
    image_validation: Dict[str, Any]
    ingestion: Dict[str, Any]
    vision: Dict[str, Any]
    policy: Dict[str, Any]
    similar_claims: Dict[str, Any]
    user_risk: Dict[str, Any]
    fraud: Dict[str, Any]
    decision: Dict[str, Any]

    # Audit trail (append-only)
    audit_logs: Annotated[List[Dict[str, Any]], add]
    timeline: Annotated[List[str], add]
    # Real failures, surfaced rather than swallowed. Non-empty means the verdict is degraded.
    pipeline_errors: Annotated[List[str], add]


# ─── Node: Image Validator ──────────────────────────────────────────────────

def node_image_validator(state: ClaimsState) -> Dict[str, Any]:
    print("[Utility] Image Validator executing...")
    t = _now()
    res = run_image_validator(
        images=state.get("images"),
        image_paths_str=state["image_paths"],
        base_dir=state.get("image_base_dir", ""),
    )
    out = res.model_dump()
    return {
        "image_validation": out,
        "audit_logs": [{
            "agent_name": "Image Validator",
            "timestamp": t,
            "outputs": out,
            "reasoning": f"Validated {res.file_count} files. Issues: {res.issues or 'none'}",
        }],
        "timeline": ["✓ Images Validated"],
    }


# ─── Conditional edge: route after validation (feedback #2) ─────────────────

def route_after_validation(state: ClaimsState) -> str:
    """
    Short-circuit when there is no usable image evidence.

    This is the single biggest cost control in the pipeline: a claim with nothing to look
    at cannot produce a grounded verdict, so spending four LLM calls to discover that is
    pure waste.

    The previous condition also required `file_count == 0`, which meant a claim declaring
    five image paths that all failed to load was treated as fully evidenced and sent down
    the full pipeline. `valid` now means "at least one image genuinely loaded", so this
    routes on the thing that actually matters.
    """
    validation = state.get("image_validation", {})
    if validation.get("valid", False):
        return "claim_ingestion"

    # Escape hatch: with text-only inference explicitly enabled, continue without images.
    from agent_core.services.config import evidence_config
    if evidence_config()["allow_text_only_inference"]:
        return "claim_ingestion"

    return "short_circuit_decision"


# ─── Node: Short-circuit Decision (no usable evidence) ──────────────────────

def node_short_circuit_decision(state: ClaimsState) -> Dict[str, Any]:
    """
    Terminal state for claims with no usable image evidence.

    Note what this deliberately does NOT do: it does not conclude the claim is false. It
    concludes we cannot tell, routes to a human, and says exactly why.
    """
    print("[Decision] Short-circuit: no usable image evidence, skipping LLM pipeline.")
    validation = state.get("image_validation", {})
    issues = validation.get("issues", [])
    declared = validation.get("file_count", 0)

    if declared == 0:
        reason = "no image evidence was submitted with this claim."
    else:
        detail = ", ".join(issues[:5]) if issues else "none of the declared images could be read"
        reason = (
            f"all {declared} declared image(s) were unusable ({detail}); "
            f"the claimant must resubmit readable evidence."
        )

    decision = DecisionOutput.from_failure(reason)
    out = decision.model_dump()

    return {
        "decision": out,
        # Populate vision with the explicit "could not look" finding so the output row is
        # complete and honest rather than carrying empty cells.
        "vision": cannot_assess(reason).model_dump(),
        "audit_logs": [{
            "agent_name": "Decision Agent (Short-Circuit)",
            "timestamp": _now(),
            "outputs": out,
            "reasoning": "No usable image evidence; skipped all LLM calls.",
        }],
        "timeline": ["✗ Short-circuited: no usable image evidence"],
    }


# ─── Node: Claim Ingestion ──────────────────────────────────────────────────

def node_claim_ingestion(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent 1] Claim Ingestion executing...")
    t = _now()
    try:
        res = run_claim_ingestion_agent(
            conversation=state["user_claim"],
            claim_object=state["claim_object"],
            user_id=state["user_id"],
        )
    except LLMUnavailableError as e:
        # We do not guess the claimed part. Every downstream comparison is claimed-vs-observed;
        # a fabricated `claimed_part` would corrupt the verdict while looking authoritative.
        print(f"[Agent 1] Claim Ingestion UNAVAILABLE: {e}")
        out = BranchFailureOutput(
            summary="Claim intake could not be completed.",
            error=str(e),
            error_type=type(e).__name__,
        ).model_dump()
        return {
            "ingestion": out,
            "pipeline_errors": [f"claim_ingestion: {e}"],
            "audit_logs": [{
                "agent_name": "Claim Ingestion Agent",
                "timestamp": t,
                "outputs": out,
                "reasoning": f"Branch failed: {e}",
            }],
            "timeline": ["✗ Claim Parsing Failed"],
        }

    out = res.model_dump()
    return {
        "ingestion": out,
        "audit_logs": [{
            "agent_name": "Claim Ingestion Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": f"Extracted: {res.object} — {res.claimed_part} — {res.claimed_issue}",
        }],
        "timeline": ["✓ Claim Parsed"],
    }


# ─── Parallel branches ──────────────────────────────────────────────────────
#
# Each branch is isolated: a failure degrades the verdict toward
# not_enough_information, it never takes the whole claim down, and it never silently
# reads as a passing check. Downstream prompts are explicit that `status: failed`
# means UNKNOWN, not OK.

def _branch_failure(node: str, exc: BaseException) -> Dict[str, Any]:
    """Uniform failure payload for a parallel branch."""
    print(f"[{node}] FAILED: {exc}")
    if not isinstance(exc, LLMUnavailableError):
        traceback.print_exc()
    return BranchFailureOutput(
        summary=f"{node} failed: {exc}",
        error=str(exc),
        error_type=type(exc).__name__,
    ).model_dump()


def node_vision_analysis(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent 2] Vision Analysis executing...")
    t = _now()
    try:
        ingestion = state.get("ingestion", {})
        res = run_vision_analysis_agent(
            claimed_object=ingestion.get("object", state["claim_object"]),
            claimed_part=ingestion.get("claimed_part", "unknown"),
            user_claim_text=state["user_claim"],
            user_id=state["user_id"],
            images=state.get("images"),
            image_paths_str=state["image_paths"],
        )
        out = res.model_dump()
        reasoning = res.justification
        errors: List[str] = []
    except Exception as e:
        out = _branch_failure("Vision Analysis", e)
        reasoning = f"Branch failed with error: {e}"
        errors = [f"vision_analysis: {e}"]

    return {
        "vision": out,
        "pipeline_errors": errors,
        "audit_logs": [{
            "agent_name": "Vision Analysis Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": reasoning,
        }],
        "timeline": ["✓ Vision Analyzed" if out.get("status") != "failed" else "✗ Vision Failed"],
    }


def node_policy_verification(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent 3] Policy Verification executing...")
    t = _now()
    try:
        ingestion = state.get("ingestion", {})
        validation = state.get("image_validation", {})
        res = run_policy_verification_agent(
            claim_object=ingestion.get("object", state["claim_object"]),
            claimed_part=ingestion.get("claimed_part", "unknown"),
            image_paths=state["image_paths"],
            image_valid=validation.get("valid", True),
            image_issues=validation.get("issues", []),
            evidence_rules=state.get("evidence_rules"),
        )
        out = res.model_dump()
        reasoning = res.reason
        errors = []
    except Exception as e:
        out = _branch_failure("Policy Verification", e)
        reasoning = f"Branch failed with error: {e}"
        errors = [f"policy_verification: {e}"]

    return {
        "policy": out,
        "pipeline_errors": errors,
        "audit_logs": [{
            "agent_name": "Policy Verification Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": reasoning,
        }],
        "timeline": ["✓ Policy Verified" if out.get("status") != "failed" else "✗ Policy Check Failed"],
    }


def node_similar_claims(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent 4] Similar Claims executing...")
    t = _now()
    try:
        ingestion = state.get("ingestion", {})
        res = run_similar_claims_agent(
            user_claim=state["user_claim"],
            claim_object=ingestion.get("object", state["claim_object"]),
        )
        out = res.model_dump()
        reasoning = res.summary
        errors = []
    except Exception as e:
        out = _branch_failure("Similar Claims", e)
        reasoning = f"Branch failed with error: {e}"
        errors = [f"similar_claims: {e}"]

    return {
        "similar_claims": out,
        "pipeline_errors": errors,
        "audit_logs": [{
            "agent_name": "Similar Claims Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": reasoning,
        }],
        "timeline": ["✓ Similar Claims Found" if out.get("status") != "failed" else "✗ Similar Claims Failed"],
    }


def node_user_risk(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent 5] User Risk executing...")
    t = _now()
    try:
        res = run_user_risk_agent(
            user_id=state["user_id"],
            user_history=state.get("user_history"),
        )
        out = res.model_dump()
        reasoning = res.summary
        errors = []
    except Exception as e:
        out = _branch_failure("User Risk", e)
        reasoning = f"Branch failed with error: {e}"
        errors = [f"user_risk: {e}"]

    return {
        "user_risk": out,
        "pipeline_errors": errors,
        "audit_logs": [{
            "agent_name": "User Risk Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": reasoning,
        }],
        "timeline": ["✓ User Risk Evaluated" if out.get("status") != "failed" else "✗ User Risk Failed"],
    }


# ─── Node: Fraud Review ─────────────────────────────────────────────────────

def node_fraud_review(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent 6] Fraud Review executing...")
    t = _now()
    try:
        res = run_fraud_review_agent(
            claim_text=state["user_claim"],
            ingestion=state.get("ingestion", {}),
            vision=state.get("vision", {}),
            policy=state.get("policy", {}),
            user_risk=state.get("user_risk", {}),
            user_id=state["user_id"],
        )
        out = res.model_dump()
        reasoning = res.reasoning
        errors = []
    except Exception as e:
        # A fraud check we could not run is not a clean bill of health. It is recorded as
        # unknown, and the decision node is told to treat it that way.
        out = _branch_failure("Fraud Review", e)
        reasoning = f"Fraud review unavailable: {e}"
        errors = [f"fraud_review: {e}"]

    return {
        "fraud": out,
        "pipeline_errors": errors,
        "audit_logs": [{
            "agent_name": "Fraud Review Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": reasoning,
        }],
        "timeline": ["✓ Fraud Reviewed" if out.get("status") != "failed" else "✗ Fraud Review Failed"],
    }


# ─── Node: Decision ─────────────────────────────────────────────────────────

def node_decision(state: ClaimsState) -> Dict[str, Any]:
    """
    Final verdict.

    If the model is unavailable here, we emit the honest error state — a
    `not_enough_information` verdict, confidence 0, flagged for human review, carrying the
    real reason. We never synthesise an approval. The old client returned a hardcoded
    `supported`/85 for exactly this case.
    """
    print("[Agent 7] Decision executing...")
    t = _now()
    try:
        res = run_decision_agent(
            ingestion=state.get("ingestion", {}),
            vision=state.get("vision", {}),
            policy=state.get("policy", {}),
            similar_claims=state.get("similar_claims", {}),
            user_risk=state.get("user_risk", {}),
            fraud=state.get("fraud", {}),
            user_id=state["user_id"],
            claim_text=state["user_claim"],
        )
        errors = []
    except Exception as e:
        print(f"[Agent 7] Decision UNAVAILABLE: {e}")
        res = DecisionOutput.from_failure(
            f"the decision model could not be reached ({type(e).__name__}: {e})."
        )
        errors = [f"decision: {e}"]

    out = res.model_dump()
    return {
        "decision": out,
        "pipeline_errors": errors,
        "audit_logs": [{
            "agent_name": "Decision Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": res.justification,
        }],
        "timeline": ["✓ Decision Generated" if not errors else "✗ Decision Unavailable"],
    }


# ─── Build the Graph ────────────────────────────────────────────────────────

def build_graph():
    workflow = StateGraph(ClaimsState)

    # Add all nodes
    workflow.add_node("image_validator", node_image_validator)
    workflow.add_node("short_circuit_decision", node_short_circuit_decision)
    workflow.add_node("claim_ingestion", node_claim_ingestion)
    workflow.add_node("vision_analysis", node_vision_analysis)
    workflow.add_node("policy_verification", node_policy_verification)
    workflow.add_node("similar_claims", node_similar_claims)
    workflow.add_node("user_risk", node_user_risk)
    workflow.add_node("fraud_review", node_fraud_review)
    workflow.add_node("decision", node_decision)

    # Entry point
    workflow.set_entry_point("image_validator")

    # Conditional routing after validation (feedback #2: fail fast on bad input)
    workflow.add_conditional_edges(
        "image_validator",
        route_after_validation,
        {
            "short_circuit_decision": "short_circuit_decision",
            "claim_ingestion": "claim_ingestion",
        },
    )
    workflow.add_edge("short_circuit_decision", END)

    # After ingestion: fan-out to 4 parallel branches
    workflow.add_edge("claim_ingestion", "vision_analysis")
    workflow.add_edge("claim_ingestion", "policy_verification")
    workflow.add_edge("claim_ingestion", "similar_claims")
    workflow.add_edge("claim_ingestion", "user_risk")

    # All 4 branches join into fraud review
    workflow.add_edge("vision_analysis", "fraud_review")
    workflow.add_edge("policy_verification", "fraud_review")
    workflow.add_edge("similar_claims", "fraud_review")
    workflow.add_edge("user_risk", "fraud_review")

    # Fraud → Decision → END
    workflow.add_edge("fraud_review", "decision")
    workflow.add_edge("decision", END)

    return workflow.compile()


# ─── Compiled graph singleton ────────────────────────────────────────────────

compiled_graph = build_graph()


# ─── Public API ──────────────────────────────────────────────────────────────

def process_claim(
    user_id: str,
    image_paths: str | list[str],
    user_claim: str,
    claim_object: str,
    user_history: dict | None = None,
    evidence_rules: dict | None = None,
    images: list | None = None,
    image_base_dir: str = "",
) -> dict:
    """
    Run the claims analysis graph over one claim. Returns the final state dict.

    `image_base_dir` is the root that relative entries in `image_paths` resolve against.
    Supply decoded `images` directly (web upload path) or let the validator load them
    from disk (CSV batch path).
    """
    if isinstance(image_paths, list):
        image_paths = ";".join(image_paths)

    initial_state = {
        "user_id": user_id,
        "image_paths": image_paths,
        "user_claim": user_claim,
        "claim_object": claim_object,
        "user_history": user_history or {},
        "evidence_rules": evidence_rules or {},
        "images": images or [],
        "image_base_dir": image_base_dir,
        # Agent output slots (initialized empty)
        "image_validation": {},
        "ingestion": {},
        "vision": {},
        "policy": {},
        "similar_claims": {},
        "user_risk": {},
        "fraud": {},
        "decision": {},
        "audit_logs": [],
        "timeline": [],
        "pipeline_errors": [],
    }

    return compiled_graph.invoke(initial_state)


def run_claims_orchestrator(claim_data: Dict[str, Any]) -> Dict[str, Any]:
    """Backward-compatible entrypoint."""
    return process_claim(
        user_id=claim_data["user_id"],
        image_paths=claim_data["image_paths"],
        user_claim=claim_data["user_claim"],
        claim_object=claim_data["claim_object"],
        user_history=claim_data.get("user_history"),
        evidence_rules=claim_data.get("evidence_rules"),
        images=claim_data.get("images"),
        image_base_dir=claim_data.get("image_base_dir", ""),
    )
