from typing import List, Dict, Any
from agent_core.services.vector_store import get_similar_claims
from agent_core.schemas.models import SimilarClaimMetadata, SimilarClaimsOutput

def run_similar_claims_agent(user_claim: str, claim_object: str) -> SimilarClaimsOutput:
    # 1. Fetch similar claims from vector store
    results = get_similar_claims(user_claim, top_k=2)
    
    similar_list = []
    comparisons = []
    
    for doc in results:
        # Convert dictionary to schema
        meta = SimilarClaimMetadata(
            user_id=doc.get("user_id", "unknown"),
            claim_object=doc.get("claim_object", "unknown"),
            issue_type=doc.get("issue_type", "unknown"),
            object_part=doc.get("object_part", "unknown"),
            claim_status=doc.get("claim_status", "unknown"),
            similarity_score=float(doc.get("similarity_score", 0.0)),
            justification=doc.get("claim_status_justification", "")
        )
        similar_list.append(meta)
        
        comparisons.append(
            f"Case for {meta.user_id} ({meta.claim_object} {meta.object_part} {meta.issue_type}) was resolved as '{meta.claim_status}' "
            f"because: {meta.justification} (Similarity score: {meta.similarity_score})"
        )
        
    if not comparisons:
        reasoning = "No relevant similar historical claims could be found in the database."
    else:
        reasoning = "Found similar historical claims:\n" + "\n".join([f"- {c}" for c in comparisons])
        
    return SimilarClaimsOutput(
        similar_claims=similar_list,
        reasoning_context=reasoning
    )
