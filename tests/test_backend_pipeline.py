"""
Guardrails on the Phase 4.2 migration.

The web platform spent three phases running a pipeline nobody was measuring: ten nodes,
four LLM calls per claim, and a verdict the model produced itself. It was migrated in 4.2.
These tests exist so it cannot drift back — not by an accidental import, not by a helpful
fallback, and not by a well-meaning "just use the old path when the new one fails".

Three independent guarantees, because any one of them alone is escapable:

1. **Static reachability.** The old modules are not reachable from the FastAPI app by any
   import edge, including imports written inside functions.
2. **Call count.** One claim costs exactly one Gemini request, and a claim with no usable
   image costs none. A silent reintroduction of the four-call flow shows up as 4.
3. **Stage identity.** The stages the pipeline actually runs are the ones it declares.

Hermetic: the one test that would call Gemini spies on the client instead.
"""
from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path
from typing import Iterator, Set

import pytest
from PIL import Image

import agent_core
from agent_core.schemas.perception import BatchPerceptionOutput
from agent_core.service import LLM_STAGES, PIPELINE_STAGES, analyse_claim_events

REPO_ROOT = Path(__file__).resolve().parents[1]

# The superseded four-call flow. Named individually rather than by prefix so that adding a
# new agent module does not silently join the forbidden list.
SUPERSEDED_MODULES = {
    "agent_core.orchestrator.graph",
    "agent_core.agents.claim_ingestion",
    "agent_core.agents.vision_analysis",
    "agent_core.agents.fraud_review",
    "agent_core.agents.decision",
    "agent_core.output_mapper",
}


# ─── 1. Static reachability ─────────────────────────────────────────────────

def _module_file(name: str) -> Path | None:
    """Resolve a first-party dotted module name to a file, without importing it."""
    parts = name.split(".")
    candidates = (REPO_ROOT.joinpath(*parts).with_suffix(".py"),
                  REPO_ROOT.joinpath(*parts, "__init__.py"))
    return next((p for p in candidates if p.is_file()), None)


def _imports_of(path: Path) -> Iterator[str]:
    """
    Every module name imported by a file, including imports nested inside functions.

    Function-level imports matter here specifically: the pre-migration backend reached the
    old router through `from agent_core.orchestrator.graph import route_after_validation`
    written in the middle of a generator, where no top-of-file scan would have found it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


FIRST_PARTY_ROOTS = ("agent_core", "platform_backend")


def _reachable_first_party_modules(root_module: str) -> Set[str]:
    """
    Transitive closure of first-party imports starting from `root_module`.

    A first-party name is recorded even when no file backs it. That matters: the
    superseded modules are deleted, so resolving names by file alone would quietly ignore
    an import of `agent_core.orchestrator.graph` and report the graph as unreachable when
    the code plainly references it.
    """
    seen: Set[str] = set()
    stack = [root_module]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        if name.split(".")[0] in FIRST_PARTY_ROOTS:
            seen.add(name)
        path = _module_file(name)
        if path is None:            # third-party, stdlib, or deleted; nothing to descend into
            continue
        stack.extend(_imports_of(path))
    return seen


def test_fastapi_app_cannot_reach_the_superseded_flow():
    reachable = _reachable_first_party_modules("platform_backend.main")
    leaked = reachable & SUPERSEDED_MODULES
    assert not leaked, (
        f"platform_backend.main can reach the superseded four-call pipeline via {sorted(leaked)}. "
        f"The web platform must use agent_core.service only."
    )


def test_the_batched_pipeline_is_actually_reachable():
    """The inverse assertion. Otherwise the test above passes on a backend that imports nothing."""
    reachable = _reachable_first_party_modules("platform_backend.main")
    assert "agent_core.service" in reachable
    assert "agent_core.agents.perception" in reachable


def test_cli_cannot_reach_the_superseded_flow():
    reachable = _reachable_first_party_modules("agent_core.main")
    assert not (reachable & SUPERSEDED_MODULES)


def test_superseded_modules_do_not_exist_on_disk():
    """
    Belt and braces: unreachable is good, absent is better.

    An unreachable module is one careless import away from being reachable again.
    """
    present = [m for m in SUPERSEDED_MODULES if _module_file(m) is not None]
    assert not present, f"superseded modules still on disk: {present}"


def test_agent_core_does_not_export_the_old_entry_point():
    assert "process_claim" not in agent_core.__all__
    assert not hasattr(agent_core, "process_claim")
    assert "analyse_claim" in agent_core.__all__


def test_importing_the_app_does_not_pull_in_the_superseded_flow():
    """
    Runtime confirmation in a clean interpreter, since the static scan and the real import
    machinery could in principle disagree.
    """
    code = (
        "import platform_backend.main, sys, json;"
        f"print(json.dumps(sorted(set(sys.modules) & {SUPERSEDED_MODULES!r})))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("[]"), (
        f"superseded modules imported at runtime: {result.stdout.strip()}"
    )


# ─── 2. Call count ──────────────────────────────────────────────────────────

class GeminiSpy:
    """Counts calls to the multimodal client and returns a canned perception."""

    def __init__(self, claim_id: str = "C1"):
        self.calls = 0
        self.claim_id = claim_id

    def __call__(self, *, contents, response_model, **kwargs):
        self.calls += 1
        return BatchPerceptionOutput.model_validate({"results": [{
            "claim_id": self.claim_id,
            "observed_object": "car",
            "image_quality": {"overall": "good", "score": 90, "issues": ["none"]},
            "claim_understanding": {
                "object_category": "car", "claimed_part": "front_bumper",
                "claimed_issue": "dent", "claimed_severity": "medium",
            },
            "damage_analysis": {"damage_detected": True, "damaged_parts": [{
                "part": "front_bumper", "issue_type": "dent", "severity": "medium",
                "image_id": "img_1", "visual_confidence": 90,
            }]},
            "claimed_part_visible": True,
            "supporting_image_ids": ["img_1"],
            "evidence": [], "uncertainties": [],
            "instruction_like_text_present": False,
        }]})


@pytest.fixture
def spy(monkeypatch) -> GeminiSpy:
    s = GeminiSpy()
    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", s)
    return s


def _photo(tmp_path: Path, name: str = "claim.jpg") -> Path:
    """A large, sharp, correctly exposed image, so preflight cannot be the thing that fails."""
    import numpy as np
    rng = np.random.default_rng(0)
    arr = rng.integers(40, 215, (620, 900, 3), dtype=np.uint8)
    path = tmp_path / name
    Image.fromarray(arr, "RGB").save(path, "JPEG", quality=90)
    return path


def _drain(events) -> object:
    analysis = None
    for event in events:
        if event["stage"] == "done":
            analysis = event["analysis"]
    return analysis


def test_one_claim_costs_exactly_one_request(spy, tmp_path):
    """
    The headline guarantee of Phase 2/4. Four is the number this must never be again:
    at four calls per claim the 44-case benchmark needs 176 requests against a free
    budget of 20, which is not slow, it is arithmetically impossible.
    """
    _photo(tmp_path)
    analysis = _drain(analyse_claim_events(
        user_id="C1", user_claim="The front bumper is dented.", claim_object="car",
        image_paths="claim.jpg", image_base_dir=str(tmp_path), claim_id="C1",
    ))
    assert spy.calls == 1
    assert analysis.llm_requests == 1
    assert analysis.verdict.claim_status == "supported"


def test_a_claim_with_no_usable_image_costs_nothing(spy):
    """
    Preflight short-circuit. A claim with nothing to look at cannot produce a grounded
    finding, so a request would buy exactly nothing — this is the largest quota saver
    in the system and it must not quietly stop working.
    """
    analysis = _drain(analyse_claim_events(
        user_id="C1", user_claim="The front bumper is dented.", claim_object="car",
        image_paths="does/not/exist.jpg", claim_id="C1",
    ))
    assert spy.calls == 0
    assert analysis.llm_requests == 0
    assert analysis.verdict.claim_status == "not_enough_information"
    assert "R001_no_usable_image" in analysis.verdict.rule_ids


def test_the_backend_service_makes_the_same_single_call(spy, tmp_path, monkeypatch):
    """Exercised through platform_backend, not agent_core, so the route's own path is covered."""
    from platform_backend.services import claim_service

    photo = _photo(tmp_path)
    captured = {}

    def fake_save(db, db_claim, audit_logs):
        captured["claim"] = db_claim
        captured["logs"] = audit_logs
        return db_claim

    monkeypatch.setattr(claim_service, "_save_claim_and_audit", fake_save)
    claim_service.execute_claim_sync(
        db=None, user_id="C1", image_paths=photo.name,
        user_claim="The front bumper is dented.", claim_object="car",
        u_history=None, e_rules=None, image_base_dir=str(tmp_path),
    )

    assert spy.calls == 1
    assert captured["claim"].claim_status == "supported"
    assert [l["agent_name"] for l in captured["logs"]] == list(PIPELINE_STAGES)


def test_perception_failure_never_becomes_a_verdict(monkeypatch, tmp_path):
    """A model that cannot be reached must produce an error state, never a decision."""
    from agent_core.services.gemini_client import LLMUnavailableError

    def boom(**kwargs):
        raise LLMUnavailableError("no model available")

    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", boom)
    _photo(tmp_path)
    analysis = _drain(analyse_claim_events(
        user_id="C1", user_claim="The front bumper is destroyed.", claim_object="car",
        image_paths="claim.jpg", image_base_dir=str(tmp_path), claim_id="C1",
    ))
    assert analysis.verdict.claim_status == "not_enough_information"
    assert "R002_perception_unavailable" in analysis.verdict.rule_ids
    assert analysis.error is not None


# ─── 3. Stage identity ──────────────────────────────────────────────────────

def test_declared_stages_are_the_stages_that_run(spy, tmp_path):
    _photo(tmp_path)
    stages = [
        e["stage"] for e in analyse_claim_events(
            user_id="C1", user_claim="The front bumper is dented.", claim_object="car",
            image_paths="claim.jpg", image_base_dir=str(tmp_path), claim_id="C1",
        )
        if e["stage"] != "done" and e["status"] == "complete"
    ]
    assert stages == list(PIPELINE_STAGES)


def test_exactly_one_declared_stage_touches_the_network():
    assert LLM_STAGES == {"perception"}
    assert LLM_STAGES < set(PIPELINE_STAGES)


def test_skipped_perception_is_reported_as_skipped_not_complete(spy):
    """
    The UI must not show a completed model call that never happened. A silently
    'complete' perception stage is how a zero-evidence claim comes to look analysed.
    """
    events = list(analyse_claim_events(
        user_id="C1", user_claim="The bumper is dented.", claim_object="car",
        image_paths="does/not/exist.jpg", claim_id="C1",
    ))
    perception_events = [e for e in events if e["stage"] == "perception"]
    assert [e["status"] for e in perception_events] == ["skipped"]


def test_frontend_stage_list_matches_the_backend():
    """
    The UI keeps its own copy of the stage names, so it can silently stop lighting up.
    Kept honest by reading the actual source rather than trusting a comment.
    """
    src = (REPO_ROOT / "frontend/components/dashboard/SubmitClaimTab.tsx").read_text(encoding="utf-8")
    block = src.split("INITIAL_STAGES: PipelineStages = {", 1)[1].split("}", 1)[0]
    declared = [line.split(":")[0].strip() for line in block.strip().splitlines() if ":" in line]
    assert declared == list(PIPELINE_STAGES)
