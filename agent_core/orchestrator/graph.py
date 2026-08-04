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

# Agent imports
from agent_core.agents.image_validator import run_image_validator
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


# ─── Node: Image Validator ──────────────────────────────────────────────────

def node_image_validator(state: ClaimsState) -> Dict[str, Any]:
    print("[Utility] Image Validator executing...")
    t = _now()
    res = run_image_validator(
        images=state.get("images"),
        image_paths_str=state["image_paths"],
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
    """If images are invalid AND we have no path fallback, short-circuit."""
    validation = state.get("image_validation", {})
    if not validation.get("valid", True) and validation.get("file_count", 0) == 0:
        return "short_circuit_decision"
    return "claim_ingestion"


# ─── Node: Short-circuit Decision (bad input fast-fail) ─────────────────────

def node_short_circuit_decision(state: ClaimsState) -> Dict[str, Any]:
    """Skip the entire pipeline when images are fundamentally broken."""
    print("[Decision] Short-circuit: invalid images, skipping pipeline.")
    validation = state.get("image_validation", {})
    issues = validation.get("issues", [])
    out = {
        "status": "success",
        "summary": "Claim cannot be processed due to invalid image submission.",
        "confidence": 95,
        "claim_status": "not_enough_information",
        "manual_review_required": False,
        "escalation_reason": None,
        "justification": f"Image validation failed before pipeline execution. Issues: {', '.join(issues)}. "
                          f"The claimant must resubmit with valid image evidence.",
    }
    return {
        "decision": out,
        "audit_logs": [{
            "agent_name": "Decision Agent (Short-Circuit)",
            "timestamp": _now(),
            "outputs": out,
            "reasoning": "Fast-failed on invalid images to avoid wasting Gemini calls.",
        }],
        "timeline": ["✗ Short-circuited: invalid images"],
    }


# ─── Node: Claim Ingestion ──────────────────────────────────────────────────

def node_claim_ingestion(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent 1] Claim Ingestion executing...")
    t = _now()
    res = run_claim_ingestion_agent(
        conversation=state["user_claim"],
        claim_object=state["claim_object"],
        user_id=state["user_id"],
    )
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


# ─── Parallel Nodes (each wrapped in try/except for branch failure, feedback #4) ─

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
    except Exception as e:
        print(f"[Agent 2] Vision Analysis FAILED: {e}")
        traceback.print_exc()
        out = {"status": "failed", "summary": f"Vision analysis failed: {str(e)}", "error": str(e)}
        reasoning = f"Branch failed with error: {e}"

    return {
        "vision": out,
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
    except Exception as e:
        print(f"[Agent 3] Policy Verification FAILED: {e}")
        out = {"status": "failed", "summary": f"Policy check failed: {str(e)}", "error": str(e)}
        reasoning = f"Branch failed with error: {e}"

    return {
        "policy": out,
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
    except Exception as e:
        print(f"[Agent 4] Similar Claims FAILED: {e}")
        out = {"status": "failed", "summary": f"Similar claims retrieval failed: {str(e)}", "error": str(e)}
        reasoning = f"Branch failed with error: {e}"

    return {
        "similar_claims": out,
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
    except Exception as e:
        print(f"[Agent 5] User Risk FAILED: {e}")
        out = {"status": "failed", "summary": f"User risk check failed: {str(e)}", "error": str(e)}
        reasoning = f"Branch failed with error: {e}"

    return {
        "user_risk": out,
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
    res = run_fraud_review_agent(
        claim_text=state["user_claim"],
        ingestion=state.get("ingestion", {}),
        vision=state.get("vision", {}),
        policy=state.get("policy", {}),
        user_risk=state.get("user_risk", {}),
        user_id=state["user_id"],
    )
    out = res.model_dump()
    return {
        "fraud": out,
        "audit_logs": [{
            "agent_name": "Fraud Review Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": res.reasoning,
        }],
        "timeline": ["✓ Fraud Reviewed"],
    }


# ─── Node: Decision ─────────────────────────────────────────────────────────

def node_decision(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent 7] Decision executing...")
    t = _now()
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
    out = res.model_dump()
    return {
        "decision": out,
        "audit_logs": [{
            "agent_name": "Decision Agent",
            "timestamp": t,
            "outputs": out,
            "reasoning": res.justification,
        }],
        "timeline": ["✓ Decision Generated"],
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
) -> dict:
    """
    Public API to run the full 7-agent claims analysis graph.
    Returns the final ClaimsState dict.
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
    )
