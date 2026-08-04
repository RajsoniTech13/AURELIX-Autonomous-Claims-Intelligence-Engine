"""
Similar Claims Agent — DETERMINISTIC TF-IDF retrieval, no LLM call.

Retrieves 3-5 similar historical claims via cosine similarity.
Returns repair_range and settlement_duration_days per match.
"""
from typing import List, Dict, Any
from agent_core.services.vector_store import get_similar_claims
from agent_core.schemas.models import SimilarClaimMatch, SimilarClaimsOutput

# Default repair ranges by object type (for demo — in production, these come from DB)
_DEFAULT_REPAIR_RANGES = {
    "car": {"range": "$500-$3000", "days": 14},
    "laptop": {"range": "$150-$800", "days": 7},
    "package": {"range": "$20-$200", "days": 5},
}


def run_similar_claims_agent(
    user_claim: str,
    claim_object: str,
    top_k: int = 3,
) -> SimilarClaimsOutput:
    """
    TF-IDF cosine similarity search over historical claims.
    No LLM call. Returns certainty='deterministic'.
    """
    results = get_similar_claims(user_claim, top_k=top_k)

    if not results:
        return SimilarClaimsOutput(
            status="no_matches",
            summary="No similar historical claims found in the database.",
            similar_claims=[],
        )

    defaults = _DEFAULT_REPAIR_RANGES.get(claim_object.lower(), {"range": "unknown", "days": 0})

    matches: List[SimilarClaimMatch] = []
    summaries: List[str] = []

    for doc in results:
        obj_type = doc.get("claim_object", "unknown")
        obj_defaults = _DEFAULT_REPAIR_RANGES.get(obj_type.lower(), defaults)

        match = SimilarClaimMatch(
            claim_id=doc.get("claim_id", doc.get("user_id", "unknown")),
            similarity=round(float(doc.get("similarity_score", 0.0)), 3),
            claim_object=obj_type,
            issue_type=doc.get("issue_type", doc.get("claim_object", "unknown")),
            claim_status=doc.get("claim_status", "unknown"),
            repair_range=doc.get("repair_range", obj_defaults["range"]),
            settlement_duration_days=int(doc.get("settlement_duration_days", obj_defaults["days"])),
        )
        matches.append(match)
        summaries.append(
            f"- {match.claim_id}: {match.claim_object} {match.issue_type} → "
            f"{match.claim_status} (similarity: {match.similarity}, "
            f"repair: {match.repair_range}, settled in {match.settlement_duration_days}d)"
        )

    summary_text = f"Found {len(matches)} similar historical claims:\n" + "\n".join(summaries)

    return SimilarClaimsOutput(
        status="success",
        summary=summary_text,
        similar_claims=matches,
    )
