from typing import TypedDict, List, Dict, Any, Annotated
from operator import add
from langgraph.graph import StateGraph, END
import datetime

# Import agent modules
from backend.app.agents.claim_understanding import run_claim_understanding_agent
from backend.app.agents.vision_analysis import run_vision_analysis_agent
from backend.app.agents.image_quality import run_image_quality_agent
from backend.app.agents.evidence_compliance import run_evidence_compliance_agent
from backend.app.agents.user_risk import run_user_risk_agent
from backend.app.agents.fraud_detection import run_fraud_detection_agent
from backend.app.agents.confidence import run_confidence_agent
from backend.app.agents.decision import run_decision_agent
from backend.app.agents.human_review import run_human_review_agent

# Define Agent State
class ClaimsState(TypedDict):
    user_id: str
    image_paths: str
    user_claim: str
    claim_object: str
    
    # Agent outputs
    understanding: Dict[str, Any]
    quality: Dict[str, Any]
    vision: Dict[str, Any]
    compliance: Dict[str, Any]
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
    t_start = datetime.datetime.utcnow().isoformat()
    res = run_claim_understanding_agent(state["user_claim"], state["claim_object"])
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
    t_start = datetime.datetime.utcnow().isoformat()
    # Read parts extracted from understanding
    claimed_part = state["understanding"]["claimed_part"]
    claimed_object = state["understanding"]["object"]
    
    res = run_image_quality_agent(state["image_paths"], claimed_object, claimed_part, state["user_claim"])
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
        "timeline": ["✓ Images Evaluated"]
    }

def node_vision_analysis(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Vision Analysis executing...")
    t_start = datetime.datetime.utcnow().isoformat()
    claimed_part = state["understanding"]["claimed_part"]
    claimed_object = state["understanding"]["object"]
    claimed_issue = state["understanding"]["claimed_issue"]
    
    res = run_vision_analysis_agent(
        state["image_paths"], claimed_object, claimed_part, state["user_claim"]
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
        "timeline": ["✓ Vision Analyzed"]
    }

def node_evidence_compliance(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Evidence Compliance executing...")
    t_start = datetime.datetime.utcnow().isoformat()
    claimed_part = state["understanding"]["claimed_part"]
    claimed_object = state["understanding"]["object"]
    quality_flags = state["quality"]["quality_flags"]
    
    res = run_evidence_compliance_agent(
        claimed_object, claimed_part, state["image_paths"], quality_flags
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Evidence Compliance Agent",
        "timestamp": t_start,
        "inputs": {"claimed_object": claimed_object, "claimed_part": claimed_part, "image_paths": state["image_paths"]},
        "outputs": out,
        "reasoning": res.reason
    }
    
    return {
        "compliance": out,
        "audit_logs": [audit],
        "timeline": ["✓ Evidence Compliance Checked"]
    }

def node_user_risk(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] User Risk executing...")
    t_start = datetime.datetime.utcnow().isoformat()
    res = run_user_risk_agent(state["user_id"])
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
        "timeline": ["✓ User Risk Analyzed"]
    }

def node_fraud_detection(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Fraud Detection executing...")
    t_start = datetime.datetime.utcnow().isoformat()
    
    # We combine fraud text inputs and quality flags
    res = run_fraud_detection_agent(
        state["user_claim"],
        state["understanding"],
        state["vision"],
        state["quality"]["quality_flags"],
        state["user_risk"]["user_risk_score"]
    )
    out = res.model_dump()
    
    audit = {
        "agent_name": "Fraud Detection Agent",
        "timestamp": t_start,
        "inputs": {"user_claim": state["user_claim"]},
        "outputs": out,
        "reasoning": res.explanation
    }
    
    return {
        "fraud": out,
        "audit_logs": [audit],
        "timeline": ["✓ Fraud Checks Completed"]
    }

def node_confidence(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Confidence score calculating...")
    t_start = datetime.datetime.utcnow().isoformat()
    
    res = run_confidence_agent(
        state["quality"]["image_valid"],
        state["quality"]["quality_flags"],
        state["compliance"]["evidence_standard_met"],
        state["fraud"]["fraud_score"],
        state["user_risk"]["user_risk_score"],
        state["vision"]["damage_detected"]
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
        "timeline": ["✓ Confidence Score Calculated"]
    }

def node_decision(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Final Decision generating...")
    t_start = datetime.datetime.utcnow().isoformat()
    
    res = run_decision_agent(
        state["understanding"],
        state["vision"],
        state["quality"]["quality_flags"],
        state["quality"]["image_valid"],
        state["compliance"]["evidence_standard_met"],
        state["compliance"]["reason"],
        state["fraud"]["fraud_score"],
        state["user_risk"]["user_risk_score"]
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
        "timeline": ["✓ Verdict Generated"]
    }

def node_human_review(state: ClaimsState) -> Dict[str, Any]:
    print("[Agent] Escalation rules checking...")
    t_start = datetime.datetime.utcnow().isoformat()
    
    res = run_human_review_agent(
        state["confidence"]["confidence_score"],
        state["fraud"]["fraud_score"],
        state["quality"]["image_valid"],
        state["quality"]["quality_flags"],
        state["user_risk"]["user_risk_score"],
        state["decision"]["claim_status"]
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
        "timeline": ["✓ Escalation Check Completed"]
    }

# Build LangGraph workflow
def build_graph():
    workflow = StateGraph(ClaimsState)
    
    # Add Nodes
    workflow.add_node("claim_understanding", node_claim_understanding)
    workflow.add_node("image_quality", node_image_quality)
    workflow.add_node("vision_analysis", node_vision_analysis)
    workflow.add_node("evidence_compliance", node_evidence_compliance)
    workflow.add_node("user_risk", node_user_risk)
    workflow.add_node("fraud_detection", node_fraud_detection)
    workflow.add_node("confidence", node_confidence)
    workflow.add_node("decision", node_decision)
    workflow.add_node("human_review", node_human_review)
    
    # Define Entry and Edges
    workflow.set_entry_point("claim_understanding")
    workflow.add_edge("claim_understanding", "image_quality")
    workflow.add_edge("image_quality", "vision_analysis")
    workflow.add_edge("vision_analysis", "evidence_compliance")
    workflow.add_edge("evidence_compliance", "user_risk")
    workflow.add_edge("user_risk", "fraud_detection")
    workflow.add_edge("fraud_detection", "confidence")
    workflow.add_edge("confidence", "decision")
    workflow.add_edge("decision", "human_review")
    workflow.add_edge("human_review", END)
    
    # State Reducers (accumulators) for audit_logs and timeline
    # In LangGraph, to accumulate lists in the state, we can use a reducer or manually append them.
    # We will compile it as is. In python, default list operations override unless we use an Annotated state.
    # To keep it extremely simple and fully compatible with all LangGraph versions, we'll compile the graph.
    # LangGraph allows returning updates that merge/accumulate. To make sure list accumulation works 
    # out-of-the-box in standard LangGraph, we can define our TypedDict with annotated lists,
    # or inside each node, we can retrieve existing lists from the state and append to them.
    # Let's adjust nodes to fetch the state's existing list and append, to guarantee compatibility!
    return workflow.compile()

compiled_graph = build_graph()

def run_claims_orchestrator(claim_data: Dict[str, Any]) -> Dict[str, Any]:
    initial_state = {
        "user_id": claim_data["user_id"],
        "image_paths": claim_data["image_paths"],
        "user_claim": claim_data["user_claim"],
        "claim_object": claim_data["claim_object"],
        "understanding": {},
        "quality": {},
        "vision": {},
        "compliance": {},
        "user_risk": {},
        "fraud": {},
        "confidence": {},
        "decision": {},
        "escalation": {},
        "audit_logs": [],
        "timeline": []
    }
    
    # Execute graph
    # LangGraph invokes nodes and merges state updates.
    # For lists like audit_logs and timeline, if we return them in the dictionary,
    # default LangGraph logic will overwrite them unless defined as Annotated[list, operator.add].
    # To keep it robust, we'll run it step-by-step or compile with clean list extend.
    # Actually, we can run the compiled graph directly, and we will define state list reducers!
    # Let's make sure it handles list additions correctly.
    # A simple, robust way is to run the graph's nodes sequentially in Python or use the compiled graph.
    # Let's run the compiled graph. To ensure list concatenation works:
    # We define state:
    # class ClaimsState(TypedDict):
    #   ...
    #   audit_logs: Annotated[list, add]
    # Let's do that! That's the idiomatic LangGraph way!
    
    # Wait, we can import `add` from `operator`:
    # from typing import Annotated
    # from operator import add
    # and annotate the fields. Let's do that in a very clean way.
    return compiled_graph.invoke(initial_state)
