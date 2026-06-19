from typing import TypedDict, List, Dict, Any, Annotated
from operator import add
from langgraph.graph import StateGraph, END
from datetime import datetime, timezone

def get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# Import agent modules
from agent_core.agents.claim_understanding import run_claim_understanding_agent
from agent_core.agents.vision_analysis import run_vision_analysis_agent
from agent_core.agents.image_quality import run_image_quality_agent
from agent_core.agents.evidence_compliance import run_evidence_retrieval_agent
from agent_core.agents.similar_claims import run_similar_claims_agent
from agent_core.agents.user_risk import run_user_risk_agent
from agent_core.agents.fraud_intelligence import run_fraud_intelligence_agent
from agent_core.agents.confidence import run_confidence_agent
from agent_core.agents.decision import run_decision_agent
from agent_core.agents.human_review import run_human_review_agent

# Define Agent State
class ClaimsState(TypedDict):
    user_id: str
    image_paths: str
    user_claim: str
    claim_object: str
    
    # Decoupled inputs passed in state
    user_history: Dict[str, Any]
    evidence_rules: Dict[str, Any]
    images: List[Any]  # PIL images passed for true vision analysis
    
    # Agent outputs
    understanding: Dict[str, Any]
    quality: Dict[str, Any]
    vision: Dict[str, Any]
    compliance: Dict[str, Any]
    similar_claims: Dict[str, Any]
    user_risk: Dict[str, Any]
    fraud: Dict[str, Any]
    confidence: Dict[str, Any]
    decision: Dict[str, Any]
    escalation: Dict[str, Any]
    
    # Audit trail & timeline
    audit_logs: Annotated[List[Dict[str, Any]], add]
    timeline: Annotated[List[str], add]

# Define Node functions
def node_claim_understanding(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Claim Understanding executing...")
    t_start = get_now_iso()
    res = run_claim_understanding_agent(
        conversation=state["user_claim"],
        claim_object=state["claim_object"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Claim Understanding Agent",
        "timestamp": t_start,
        "inputs": {"user_claim": state["user_claim"], "claim_object": state["claim_object"]},
        "outputs": out,
        "reasoning": f"Extracted object: {res.object}, part: {res.claimed_part}, issue: {res.claimed_issue}."
    }
    
    return {
        "understanding": out,
        "audit_logs": [audit],
        "timeline": ["✓ Claim Parsed"]
    }

def node_image_quality(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Image Quality executing...")
    t_start = get_now_iso()
    claimed_part = state["understanding"]["claimed_part"]
    claimed_object = state["understanding"]["object"]
    
    res = run_image_quality_agent(
        claimed_object=claimed_object,
        claimed_part=claimed_part,
        conversation=state["user_claim"],
        images=state.get("images"),
        image_paths_str=state["image_paths"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Image Quality Agent",
        "timestamp": t_start,
        "inputs": {"image_paths": state["image_paths"], "claimed_object": claimed_object, "claimed_part": claimed_part},
        "outputs": out,
        "reasoning": res.reason
    }
    
    return {
        "quality": out,
        "audit_logs": [audit],
        "timeline": ["✓ Image Quality Checked"]
    }

def node_vision_analysis(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Vision Analysis executing...")
    t_start = get_now_iso()
    claimed_part = state["understanding"]["claimed_part"]
    claimed_object = state["understanding"]["object"]
    
    res = run_vision_analysis_agent(
        claimed_object=claimed_object,
        claimed_part=claimed_part,
        user_claim_text=state["user_claim"],
        images=state.get("images"),
        image_paths_str=state["image_paths"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Vision Analysis Agent",
        "timestamp": t_start,
        "inputs": {"image_paths": state["image_paths"], "claimed_object": claimed_object, "claimed_part": claimed_part},
        "outputs": out,
        "reasoning": res.justification
    }
    
    return {
        "vision": out,
        "audit_logs": [audit],
        "timeline": ["✓ Vision Analysed"]
    }

def node_evidence_retrieval(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Evidence Retrieval executing...")
    t_start = get_now_iso()
    claimed_part = state["understanding"]["claimed_part"]
    claimed_object = state["understanding"]["object"]
    quality_flags = state["quality"]["quality_flags"]
    
    # Decoupled evidence retrieval
    res = run_evidence_retrieval_agent(
        claim_object=claimed_object,
        claimed_part=claimed_part,
        image_paths=state["image_paths"],
        quality_flags=quality_flags,
        evidence_rules=state.get("evidence_rules")
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Evidence Retrieval Agent",
        "timestamp": t_start,
        "inputs": {"claimed_object": claimed_object, "claimed_part": claimed_part, "image_paths": state["image_paths"]},
        "outputs": out,
        "reasoning": res.reason
    }
    
    return {
        "compliance": out,
        "audit_logs": [audit],
        "timeline": ["✓ Evidence Standards Checked"]
    }

def node_similar_claims_retrieval(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Similar Claims Retrieval executing...")
    t_start = get_now_iso()
    
    res = run_similar_claims_agent(
        user_claim=state["user_claim"],
        claim_object=state["understanding"]["object"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Similar Claims Retrieval Agent",
        "timestamp": t_start,
        "inputs": {"query_text": state["user_claim"]},
        "outputs": out,
        "reasoning": res.reasoning_context
    }
    
    return {
        "similar_claims": out,
        "audit_logs": [audit],
        "timeline": ["✓ Historical Similar Claims Found"]
    }

def node_user_risk(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] User Risk executing...")
    t_start = get_now_iso()
    
    # Decoupled user risk check
    res = run_user_risk_agent(
        user_id=state["user_id"],
        user_history=state.get("user_history")
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "User Risk Agent",
        "timestamp": t_start,
        "inputs": {"user_id": state["user_id"]},
        "outputs": out,
        "reasoning": res.explanation
    }
    
    return {
        "user_risk": out,
        "audit_logs": [audit],
        "timeline": ["✓ User Risk Evaluated"]
    }

def node_fraud_intelligence(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Fraud Intelligence executing...")
    t_start = get_now_iso()
    
    res = run_fraud_intelligence_agent(
        claim_text=state["user_claim"],
        claim_understanding=state["understanding"],
        vision_analysis=state["vision"],
        quality_flags=state["quality"]["quality_flags"],
        user_risk_score=state["user_risk"]["user_risk_score"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Fraud Intelligence Agent",
        "timestamp": t_start,
        "inputs": {"user_claim": state["user_claim"]},
        "outputs": out,
        "reasoning": res.explanation
    }
    
    return {
        "fraud": out,
        "audit_logs": [audit],
        "timeline": ["✓ Fraud Checked"]
    }

def node_confidence(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Confidence score calculating...")
    t_start = get_now_iso()
    
    res = run_confidence_agent(
        image_valid=state["quality"]["image_valid"],
        quality_flags=state["quality"]["quality_flags"],
        evidence_standard_met=state["compliance"]["evidence_standard_met"],
        fraud_score=state["fraud"]["fraud_score"],
        user_risk_score=state["user_risk"]["user_risk_score"],
        damage_detected=state["vision"]["damage_detected"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Confidence Agent",
        "timestamp": t_start,
        "inputs": {},
        "outputs": out,
        "reasoning": res.explanation
    }
    
    return {
        "confidence": out,
        "audit_logs": [audit],
        "timeline": ["✓ Confidence Calculated"]
    }

def node_decision(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Final Decision generating...")
    t_start = get_now_iso()
    
    res = run_decision_agent(
        claim_understanding=state["understanding"],
        vision_analysis=state["vision"],
        quality_flags=state["quality"]["quality_flags"],
        image_valid=state["quality"]["image_valid"],
        evidence_standard_met=state["compliance"]["evidence_standard_met"],
        evidence_compliance_reason=state["compliance"]["reason"],
        fraud_score=state["fraud"]["fraud_score"],
        user_risk_score=state["user_risk"]["user_risk_score"],
        similar_claims_context=state["similar_claims"]["reasoning_context"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Decision Agent",
        "timestamp": t_start,
        "inputs": {},
        "outputs": out,
        "reasoning": res.justification
    }
    
    return {
        "decision": out,
        "audit_logs": [audit],
        "timeline": ["✓ Decision Generated"]
    }

def node_human_review(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Escalation rules checking...")
    t_start = get_now_iso()
    
    res = run_human_review_agent(
        confidence_score=state["confidence"]["confidence_score"],
        fraud_score=state["fraud"]["fraud_score"],
        image_valid=state["quality"]["image_valid"],
        quality_flags=state["quality"]["quality_flags"],
        user_risk_score=state["user_risk"]["user_risk_score"],
        claim_status=state["decision"]["claim_status"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Human Review Agent",
        "timestamp": t_start,
        "inputs": {},
        "outputs": out,
        "reasoning": f"Manual review required: {res.manual_review_required}. Reason: {res.escalation_reason}"
    }
    
    return {
        "escalation": out,
        "audit_logs": [audit],
        "timeline": ["✓ Escalated to Human review"]
    }

# Build LangGraph workflow
def build_graph():
    workflow = StateGraph(ClaimsState)
    
    # Add Nodes
    workflow.add_node("claim_understanding", node_claim_understanding)
    workflow.add_node("image_quality", node_image_quality)
    workflow.add_node("vision_analysis", node_vision_analysis)
    workflow.add_node("evidence_retrieval", node_evidence_retrieval)
    workflow.add_node("similar_claims_retrieval", node_similar_claims_retrieval)
    workflow.add_node("user_risk", node_user_risk)
    workflow.add_node("fraud_intelligence", node_fraud_intelligence)
    workflow.add_node("confidence", node_confidence)
    workflow.add_node("decision", node_decision)
    workflow.add_node("human_review", node_human_review)
    
    # Define Entry and Edges
    workflow.set_entry_point("claim_understanding")
    workflow.add_edge("claim_understanding", "image_quality")
    workflow.add_edge("image_quality", "vision_analysis")
    workflow.add_edge("vision_analysis", "evidence_retrieval")
    workflow.add_edge("evidence_retrieval", "similar_claims_retrieval")
    workflow.add_edge("similar_claims_retrieval", "user_risk")
    workflow.add_edge("user_risk", "fraud_intelligence")
    workflow.add_edge("fraud_intelligence", "confidence")
    workflow.add_edge("confidence", "decision")
    workflow.add_edge("decision", "human_review")
    workflow.add_edge("human_review", END)
    
    return workflow.compile()

compiled_graph = build_graph()

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
    Public API interface to run claims analysis graph.
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
        "understanding": {},
        "quality": {},
        "vision": {},
        "compliance": {},
        "similar_claims": {},
        "user_risk": {},
        "fraud": {},
        "confidence": {},
        "decision": {},
        "escalation": {},
        "audit_logs": [],
        "timeline": []
    }
    
    return compiled_graph.invoke(initial_state)

def run_claims_orchestrator(claim_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Backward-compatible entrypoint.
    """
    return process_claim(
        user_id=claim_data["user_id"],
        image_paths=claim_data["image_paths"],
        user_claim=claim_data["user_claim"],
        claim_object=claim_data["claim_object"],
        user_history=claim_data.get("user_history"),
        evidence_rules=claim_data.get("evidence_rules"),
        images=claim_data.get("images")
    )
