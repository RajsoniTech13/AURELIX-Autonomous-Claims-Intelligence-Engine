import os
os.environ["MOCK_LLM"] = "true"
import json
from agent_core.orchestrator.graph import compiled_graph

initial_state = {
    "user_id": "test_1",
    "image_paths": "test.jpg",
    "user_claim": "test claim",
    "claim_object": "car",
    "user_history": {},
    "evidence_rules": {},
    "images": [],
    "image_validation": {}, "ingestion": {}, "vision": {}, "policy": {}, 
    "similar_claims": {}, "user_risk": {}, "fraud": {}, "decision": {},
    "audit_logs": [], "timeline": [],
}

print("Starting stream...")
for event in compiled_graph.stream(initial_state):
    print("Received event:", list(event.keys())[0])

print("Stream finished successfully!")
