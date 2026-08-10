"""
Alignment engine — deterministic, no LLM.

Compares what the claimant asserted against what was observed. This is the comparison the
whole system exists to make, and it is computed in Python on purpose: both operands come
from the model's own report, so asking the model to also do the subtraction adds a failure
mode without adding information. Here it is reproducible, unit-testable, and free.

The part ontology solves a specific false-negative: a claimant writing "bonnet dented" and a
model reporting "hood dent" is a match, not a mismatch. Without normalisation that reads as
`part_mismatch` and produces a wrong `contradicted` verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

from agent_core.schemas.perception import ClaimPerception, severity_rank

PartMatch = Literal["exact", "adjacent", "mismatch", "not_visible", "unknown"]
ObjectMatch = Literal["match", "mismatch", "unknown"]


# ─── Part ontology ──────────────────────────────────────────────────────────
# Synonyms collapse to a canonical name. Adjacency captures parts close enough that
# damage to one plausibly involves the other -- a front-bumper impact marking the
# grille is not a contradiction.

_SYNONYMS = {
    # car
    "bonnet": "hood", "hood": "hood",
    "boot": "trunk", "trunk": "trunk", "tailgate": "trunk",
    "windscreen": "windshield", "windshield": "windshield", "front_glass": "windshield",
    "wing": "fender", "fender": "fender", "wing_mirror": "side_mirror",
    "side_mirror": "side_mirror", "mirror": "side_mirror", "door_mirror": "side_mirror",
    "front_bumper": "front_bumper", "front bumper": "front_bumper", "fbumper": "front_bumper",
    "rear_bumper": "rear_bumper", "rear bumper": "rear_bumper", "back_bumper": "rear_bumper",
    "bumper": "bumper",
    "headlight": "headlight", "head_lamp": "headlight", "headlamp": "headlight",
    "taillight": "taillight", "tail_lamp": "taillight", "rear_light": "taillight",
    "door": "door", "door_panel": "door", "driver_door": "door", "passenger_door": "door",
    "grille": "grille", "grill": "grille",
    "wheel": "wheel", "tyre": "wheel", "tire": "wheel", "rim": "wheel",
    "roof": "roof",
    # Models describe the flank of a car as "side panel" / "body panel" as often as
    # "quarter panel"; without these two claims came back as part_mismatch against a
    # perfectly reasonable observation.
    "quarter_panel": "quarter_panel", "side_panel": "quarter_panel",
    "body_panel": "quarter_panel", "rear_panel": "quarter_panel",
    # laptop
    "screen": "screen", "display": "screen", "lcd": "screen", "monitor": "screen",
    "keyboard": "keyboard", "keys": "keyboard",
    "hinge": "hinge", "trackpad": "trackpad", "touchpad": "trackpad",
    "lid": "lid", "cover": "lid", "body": "body", "chassis": "body", "casing": "body",
    "corner": "corner", "port": "port",
    # package
    "package_corner": "package_corner", "box_corner": "package_corner",
    "seal": "seal", "tape": "seal",
    "box": "box", "carton": "box", "package": "box",
    # NB: no bare "side" -> package_side mapping. It used to swallow a car's
    # "side mirror" and report a mirror claim as damage to a package side.
    "package_side": "package_side", "box_side": "package_side",
    "contents": "contents", "label": "label", "shipping_label": "label",
    # sentinels
    "none": "none", "unknown": "unknown", "": "unknown",
}

_ADJACENT = {
    "front_bumper": {"grille", "headlight", "hood", "fender", "bumper"},
    "rear_bumper": {"taillight", "trunk", "quarter_panel", "bumper"},
    "hood": {"front_bumper", "grille", "headlight", "windshield", "fender"},
    "grille": {"front_bumper", "headlight", "hood"},
    "headlight": {"front_bumper", "grille", "hood", "fender"},
    "taillight": {"rear_bumper", "trunk", "quarter_panel"},
    "trunk": {"rear_bumper", "taillight", "quarter_panel"},
    "door": {"side_mirror", "fender", "quarter_panel"},
    "side_mirror": {"door", "windshield", "quarter_panel"},
    "quarter_panel": {"door", "fender", "rear_bumper", "trunk", "side_mirror"},
    "fender": {"front_bumper", "door", "hood", "headlight", "wheel"},
    "windshield": {"hood", "roof", "side_mirror"},
    "screen": {"lid", "hinge"},
    "hinge": {"screen", "lid", "body"},
    "lid": {"screen", "hinge", "body"},
    "keyboard": {"trackpad", "body"},
    "trackpad": {"keyboard", "body"},
    "body": {"keyboard", "trackpad", "corner", "lid", "port"},
    "corner": {"body", "lid"},
    # A torn seal and a crushed corner are different failure modes with different causes,
    # so they are NOT adjacent: treating them as such let a corner-damage observation
    # support a seal-tampering claim.
    "package_corner": {"box", "package_side"},
    "seal": {"box", "label"},
    "box": {"package_corner", "package_side", "seal", "label"},
    "package_side": {"box", "package_corner"},
    "label": {"seal", "box"},
    "contents": {"box"},
}


# Tokens that name a different component depending on what the object is.
#
# `_SYNONYMS` is one flat table, so it can only hold one meaning per token — and the
# meaning it held was the car one. A package claimant writing "side" and a model observing
# "side_panel" both resolved to `quarter_panel`, a car part, which read as a part mismatch
# and contradicted a perfectly valid package claim (SYN-014).
#
# These overlay the global table when the claim's object category is known. Only tokens
# that genuinely resolve to the wrong object class are listed; anything already correct
# globally is left alone.
_OBJECT_SCOPED_SYNONYMS: dict[str, dict[str, str]] = {
    "package": {
        "side": "package_side", "side_panel": "package_side",
        "body_panel": "package_side", "rear_panel": "package_side",
        "panel": "package_side", "wall": "package_side",
        "corner": "package_corner", "edge": "package_corner",
        "lid": "box", "cover": "box", "top": "box", "flap": "box", "body": "box",
    },
    "car": {
        # A car's "side" or "body" is its flank. Exact keys win before this, so
        # "side_mirror" is still a mirror.
        "side": "quarter_panel", "panel": "quarter_panel", "body": "quarter_panel",
    },
    "laptop": {
        # The global table is already laptop-first for body / corner / lid / cover /
        # screen. Only the panel family leaks, and it leaks to a car part.
        "side_panel": "body", "body_panel": "body", "rear_panel": "body",
        # Bare "panel" is left unmapped on purpose: on a laptop it is as likely to mean
        # the display panel as the base panel, and guessing between them is worse than
        # declining to.
    },
}


def normalise_part(part: str, object_category: str = "") -> str:
    """
    Map a free-text part name onto the canonical ontology.

    `object_category` disambiguates tokens that name different components on different
    objects — see `_OBJECT_SCOPED_SYNONYMS`. It is optional so existing callers and tests
    keep the previous global-only behaviour.
    """
    key = (part or "").strip().lower().replace("-", "_").replace(" ", "_")

    table = _SYNONYMS
    scoped = _OBJECT_SCOPED_SYNONYMS.get(normalise_object(object_category)) if object_category else None
    if scoped:
        table = {**_SYNONYMS, **scoped}

    if key in table:
        return table[key]
    # "front_bumper_area", "left_headlight" -> longest matching canonical token
    best = None
    for syn, canon in table.items():
        if syn and len(syn) > 2 and syn in key:
            if best is None or len(syn) > len(best[0]):
                best = (syn, canon)
    return best[1] if best else key or "unknown"


def parts_adjacent(a: str, b: str) -> bool:
    return b in _ADJACENT.get(a, set()) or a in _ADJACENT.get(b, set())


_OBJECT_SYNONYMS = {
    "car": "car", "vehicle": "car", "automobile": "car", "sedan": "car", "suv": "car", "truck": "car",
    "laptop": "laptop", "notebook": "laptop", "computer": "laptop", "macbook": "laptop",
    "package": "package", "parcel": "package", "box": "package", "carton": "package",
}


def normalise_object(obj: str) -> str:
    """
    Map a free-text object category onto car | laptop | package.

    Exact key, then whole word, then longest substring — in that order.

    Scanning for *any* substring in insertion order resolved **"carton" to "car"**, because
    "car" is a prefix of it. A carton claim was therefore judged against a vehicle, which
    makes `object_match` a mismatch and fires `R010_wrong_object` — the most dispositive
    rule in the engine — contradicting a valid package claim outright. "cardboard box" had
    the same failure. Word matching is what removes that class of collision.
    """
    key = (obj or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in _OBJECT_SYNONYMS:
        return _OBJECT_SYNONYMS[key]

    for token in key.split("_"):
        if token in _OBJECT_SYNONYMS:
            return _OBJECT_SYNONYMS[token]

    best = None
    for syn, canon in _OBJECT_SYNONYMS.items():
        if syn in key and (best is None or len(syn) > len(best[0])):
            best = (syn, canon)
    return best[1] if best else key or "unknown"


# ─── Result ─────────────────────────────────────────────────────────────────

@dataclass
class AlignmentResult:
    part_match: PartMatch
    object_match: ObjectMatch
    severity_delta: Optional[int]        # claimed rank - observed rank; None if unmeasurable
    claimed_part: str
    observed_parts: List[str] = field(default_factory=list)
    claimed_severity: str = "unknown"
    observed_severity: str = "unknown"
    matched_part: Optional[str] = None
    damage_detected: bool = False
    claimed_part_visible: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def severity_inflated(self) -> bool:
        """Claimed materially worse than observed."""
        return self.severity_delta is not None and self.severity_delta >= 2

    @property
    def severity_overstated(self) -> bool:
        """Claimed one notch worse — worth flagging, not worth contradicting."""
        return self.severity_delta is not None and self.severity_delta == 1

    @property
    def severity_understated(self) -> bool:
        return self.severity_delta is not None and self.severity_delta <= -1

    def to_dict(self) -> dict:
        return {
            "part_match": self.part_match,
            "object_match": self.object_match,
            "severity_delta": self.severity_delta,
            "claimed_part": self.claimed_part,
            "observed_parts": self.observed_parts,
            "claimed_severity": self.claimed_severity,
            "observed_severity": self.observed_severity,
            "matched_part": self.matched_part,
            "damage_detected": self.damage_detected,
            "claimed_part_visible": self.claimed_part_visible,
            "notes": self.notes,
        }


def compute_alignment(perception: ClaimPerception, declared_object: str = "") -> AlignmentResult:
    """Compare claimed against observed. Pure function of the perception record."""
    notes: List[str] = []

    # The object is resolved first because it scopes how part names are read: "side_panel"
    # is a car's quarter panel and a package's side wall. Both sides of the comparison use
    # the *claimed* object as their frame of reference — when the images show something
    # else entirely, R010_wrong_object fires before any part rule is reached, so the part
    # comparison is moot in that case.
    claimed_object = normalise_object(
        perception.claim_understanding.object_category or declared_object
    )

    claimed_part = normalise_part(perception.claim_understanding.claimed_part, claimed_object)
    observed = [
        (normalise_part(d.part, claimed_object), d)
        for d in perception.damage_analysis.damaged_parts
    ]
    observed_parts = [p for p, _ in observed]

    # ── object match ──
    seen_object = normalise_object(perception.observed_object)
    if seen_object in ("unknown", "none", ""):
        object_match: ObjectMatch = "unknown"
    elif seen_object == claimed_object:
        object_match = "match"
    else:
        object_match = "mismatch"
        notes.append(f"claim is about a {claimed_object} but the images show a {seen_object}")

    # ── part match ──
    matched = None
    if claimed_part in ("unknown", "none"):
        part_match: PartMatch = "unknown"
        notes.append("the claimant never identified a specific part")
    elif not perception.claimed_part_visible and (
        adj0 := next((p for p in observed_parts if parts_adjacent(claimed_part, p)), None)
    ):
        # "Not visible" but damage was found on an adjacent part, so the region WAS imaged.
        # This is an adjacency, not an absence: a laptop lid reported as not visible while
        # the screen it backs is clearly damaged should not become not_enough_information.
        part_match = "adjacent"
        matched = adj0
        notes.append(
            f"the claimed part ({claimed_part}) was not itself identified, but damage was "
            f"observed on the adjacent {adj0}"
        )
    elif not perception.claimed_part_visible:
        # The load-bearing branch: not seeing a part is not the same as seeing it undamaged.
        part_match = "not_visible"
        notes.append(f"the claimed part ({claimed_part}) is not visible in any submitted image")
    elif claimed_part in observed_parts:
        part_match = "exact"
        matched = claimed_part
    elif (adj := next((p for p in observed_parts if parts_adjacent(claimed_part, p)), None)):
        part_match = "adjacent"
        matched = adj
        notes.append(f"damage found on {matched}, adjacent to the claimed {claimed_part}")
    elif observed_parts:
        part_match = "mismatch"
        notes.append(f"claimed {claimed_part} but damage was observed on {', '.join(observed_parts)}")
    else:
        # Part visible, no damage found on it anywhere.
        part_match = "mismatch"
        notes.append(f"the claimed part ({claimed_part}) is visible but no damage was observed on it")

    # ── severity delta ──
    claimed_sev = perception.claim_understanding.claimed_severity
    observed_sev = "unknown"
    if matched:
        for p, d in observed:
            if p == matched:
                observed_sev = d.severity
                break
    elif part_match == "exact" and observed:
        observed_sev = observed[0][1].severity
    elif part_match == "mismatch" and not observed_parts and perception.claimed_part_visible:
        # Visible and undamaged is a real reading of "none", not an absence of one.
        observed_sev = "none"

    c_rank, o_rank = severity_rank(claimed_sev), severity_rank(observed_sev)
    severity_delta = (c_rank - o_rank) if (c_rank is not None and o_rank is not None) else None
    if severity_delta is None:
        notes.append("severity could not be compared (one side is unknown)")

    return AlignmentResult(
        part_match=part_match,
        object_match=object_match,
        severity_delta=severity_delta,
        claimed_part=claimed_part,
        observed_parts=observed_parts,
        claimed_severity=claimed_sev,
        observed_severity=observed_sev,
        matched_part=matched,
        damage_detected=perception.damage_analysis.damage_detected,
        claimed_part_visible=perception.claimed_part_visible,
        notes=notes,
    )
