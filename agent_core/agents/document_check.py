"""
Document cross-check — DETERMINISTIC, no LLM call.

Perception transcribes what a document says. This decides what that means, by
comparing the paperwork against the photographs and the claimant's statement.
The split is the same one the whole system rests on: the model observes, Python
judges, and every judgement names a rule.

**Why this is the check that matters.** Photographs answer "is there damage".
Paperwork answers "is this the damage being paid for". The gap between those two
is where most real claim leakage sits, and it is checkable without any model
help once the fields are extracted:

* an estimate that itemises a part the photograph does not show damaged,
* a receipt for a different object entirely,
* an amount that does not survive contact with the observed severity.

Each is a comparison between two values already in hand. None of them needs a
second model call, which is why the capability fits a 20-request daily budget.

**Deliberately not implemented here.** Authenticity — whether a PDF was edited,
whether a garage exists, whether a VAT number is real. That needs a registry
lookup or forensic analysis, and guessing at it from a rendered page would be
exactly the kind of confident fabrication this architecture exists to prevent.
An illegible or unreadable document is reported as such and routed to a human.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_core.agents.alignment import AlignmentResult, normalise_object, normalise_part
from agent_core.rules_engine import load_rules
from agent_core.schemas.perception import ClaimPerception, severity_rank

# Document types that assert a repair cost. Only these make an amount-versus-severity
# comparison meaningful; a police report with a number on it is not a quote.
_COSTING_TYPES = {"invoice", "repair_estimate"}


@dataclass
class DocumentAssessment:
    """One document, judged against the rest of the evidence."""
    document_id: str
    document_type: str
    legible: bool
    object_match: str = "unknown"        # match | mismatch | unknown
    part_support: str = "unknown"        # supports | contradicts | unrelated | unknown
    matched_parts: List[str] = field(default_factory=list)
    amount: Optional[float] = None
    currency: str = "unknown"
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "document_type": self.document_type,
            "legible": self.legible,
            "object_match": self.object_match,
            "part_support": self.part_support,
            "matched_parts": list(self.matched_parts),
            "amount": self.amount,
            "currency": self.currency,
            "notes": list(self.notes),
        }


@dataclass
class DocumentCheckResult:
    """What the paperwork, taken together, says about this claim."""
    assessments: List[DocumentAssessment] = field(default_factory=list)
    signals: List[str] = field(default_factory=list)     # fraud signal names
    notes: List[str] = field(default_factory=list)       # reviewer-facing sentences

    @property
    def count(self) -> int:
        return len(self.assessments)

    @property
    def object_mismatch(self) -> bool:
        return any(a.object_match == "mismatch" for a in self.assessments)

    @property
    def part_contradiction(self) -> bool:
        return any(a.part_support == "contradicts" for a in self.assessments)

    @property
    def illegible(self) -> bool:
        return bool(self.assessments) and all(not a.legible for a in self.assessments)

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "assessments": [a.to_dict() for a in self.assessments],
            "signals": list(self.signals),
            "notes": list(self.notes),
            "object_mismatch": self.object_mismatch,
            "part_contradiction": self.part_contradiction,
            "illegible": self.illegible,
        }

    def describe(self) -> str:
        return " ".join(self.notes)


_TOKEN = re.compile(r"[a-z]+")


def _parts_in(line_items: List[str], object_category: str) -> List[str]:
    """
    Canonical part names mentioned anywhere in a document's line items.

    Runs through the same object-scoped ontology the alignment engine uses, so a
    package invoice reading "side panel" resolves to `package_side` rather than a
    car's quarter panel — the collision that once contradicted a valid claim.
    """
    found: List[str] = []
    for item in line_items or []:
        text = (item or "").lower()
        # Try the whole line first, then progressively shorter word windows, so
        # "replace front bumper cover" reaches `front_bumper` rather than `lid`.
        words = _TOKEN.findall(text)
        candidates = [text] + [
            " ".join(words[i:j])
            for i in range(len(words))
            for j in range(len(words), i, -1)
            if 0 < j - i <= 3
        ]
        for candidate in candidates:
            part = normalise_part(candidate, object_category)
            if part not in ("unknown", "none", "") and part not in found and part != candidate:
                found.append(part)
                break
    return found


def run_document_check(
    perception: Optional[ClaimPerception],
    alignment: Optional[AlignmentResult],
    claim_object: str = "",
) -> DocumentCheckResult:
    """
    Compare every supplied document against the photographs and the claim.

    Pure function of stored perception, exactly like the rest of judgement — so a
    rule change re-scores historical claims without spending a request.
    """
    result = DocumentCheckResult()
    if perception is None or not perception.documents:
        return result

    cfg = load_rules().get("documents", {})
    ceilings: Dict[str, float] = cfg.get("amount_ceiling_by_severity", {}) or {}

    claimed_object = normalise_object(
        (perception.claim_understanding.object_category if perception else "") or claim_object
    )
    observed_parts = set(alignment.observed_parts) if alignment else set()
    observed_severity = alignment.observed_severity if alignment else "unknown"

    for doc in perception.documents:
        a = DocumentAssessment(
            document_id=doc.document_id,
            document_type=doc.document_type,
            legible=doc.legible,
            amount=doc.total_amount,
            currency=doc.currency,
        )

        if not doc.legible or doc.document_type == "unreadable":
            a.notes.append(f"{doc.document_id} could not be read.")
            result.assessments.append(a)
            continue

        # ── Does the paperwork concern the same object as the claim? ──
        doc_object = normalise_object(doc.object_described)
        if doc_object in ("unknown", "other", ""):
            a.object_match = "unknown"
        elif doc_object == claimed_object:
            a.object_match = "match"
        else:
            a.object_match = "mismatch"
            a.notes.append(
                f"{doc.document_id} is a {doc.document_type.replace('_', ' ')} for a "
                f"{doc_object}, but the claim is about a {claimed_object}."
            )

        # ── Do the itemised parts line up with what the photographs show? ──
        doc_parts = _parts_in(doc.line_items, claimed_object)
        a.matched_parts = doc_parts
        if not doc_parts:
            a.part_support = "unknown"
        elif observed_parts and set(doc_parts) & observed_parts:
            a.part_support = "supports"
            overlap = sorted(set(doc_parts) & observed_parts)
            a.notes.append(
                f"{doc.document_id} itemises {', '.join(overlap)}, which matches the "
                f"observed damage."
            )
        elif observed_parts:
            a.part_support = "contradicts"
            a.notes.append(
                f"{doc.document_id} itemises {', '.join(doc_parts)}, but the damage observed "
                f"in the photographs is on {', '.join(sorted(observed_parts))}."
            )
        else:
            a.part_support = "unrelated"

        # ── Is the amount plausible for the severity actually observed? ──
        #
        # A ceiling, not a price model. It only asks "is this an order of
        # magnitude away from what this severity could cost", and only for
        # documents that actually quote work.
        if (
            doc.document_type in _COSTING_TYPES
            and doc.total_amount is not None
            and observed_severity in ceilings
            and severity_rank(observed_severity) is not None
        ):
            ceiling = float(ceilings[observed_severity])
            if doc.total_amount > ceiling:
                a.notes.append(
                    f"{doc.document_id} quotes {doc.total_amount:.0f} {doc.currency} against "
                    f"damage assessed as {observed_severity}."
                )
                if "document_amount_implausible" not in result.signals:
                    result.signals.append("document_amount_implausible")

        result.assessments.append(a)

    # ── Aggregate signals ──
    if result.object_mismatch and "document_object_mismatch" not in result.signals:
        result.signals.append("document_object_mismatch")
    if result.part_contradiction and "document_part_contradiction" not in result.signals:
        result.signals.append("document_part_contradiction")

    for a in result.assessments:
        result.notes.extend(a.notes)

    if result.illegible:
        result.notes.append("No supplied document could be read.")

    return result
