"""
Retrieval: perceptual hashing, the duplicate-image index, and hybrid text search.

The duplicate index decides whether somebody is accused of fraud, so the tests are weighted
towards the things that would produce a *wrong accusation*: matching a claim against itself,
matching two genuinely different photographs, or trusting the fingerprint of an image too
featureless to have a stable one.

Hermetic: real fixture photographs and in-memory transformations. No model, no network.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageEnhance

from agent_core.retrieval.hashing import dhash, fingerprint, hamming, phash
from agent_core.retrieval.hybrid import Document, GeminiEmbeddingBackend, HybridRetriever
from agent_core.retrieval.image_index import (
    ImageIndex,
    content_hash,
    indexable,
    load_retrieval_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CAR = REPO_ROOT / "tests/fixtures/images/car_damage.jpg"
CAT = REPO_ROOT / "tests/fixtures/images/cat.jpg"


@pytest.fixture
def car() -> Image.Image:
    return Image.open(CAR).convert("RGB")


@pytest.fixture
def cat() -> Image.Image:
    return Image.open(CAT).convert("RGB")


@pytest.fixture
def index(tmp_path) -> ImageIndex:
    return ImageIndex(tmp_path / "idx.db")


def reencode(img: Image.Image, quality: int = 55) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


# ─── Hashing ────────────────────────────────────────────────────────────────

def test_a_hash_is_64_bits(car):
    assert 0 <= phash(car) < 2 ** 64
    assert 0 <= dhash(car) < 2 ** 64


def test_an_image_matches_itself_exactly(car):
    assert hamming(phash(car), phash(car)) == 0
    assert hamming(dhash(car), dhash(car)) == 0


@pytest.mark.parametrize("transform,label", [
    (lambda i: reencode(i), "re-encoded"),
    (lambda i: i.resize((i.width // 2, i.height // 2), Image.LANCZOS), "resized down"),
    (lambda i: i.resize((i.width * 2, i.height * 2), Image.LANCZOS), "resized up"),
    (lambda i: ImageEnhance.Brightness(i).enhance(1.2), "brightened"),
    (lambda i: i.convert("L").convert("RGB"), "greyscaled"),
])
def test_hashes_survive_ordinary_re_upload_damage(car, transform, label):
    """These are what a photograph goes through on its way through a messaging app."""
    original, altered = fingerprint(car), fingerprint(transform(car))
    assert hamming(original.phash, altered.phash) <= 12, label
    assert hamming(original.dhash, altered.dhash) <= 10, label


def test_different_photographs_are_far_apart(car, cat):
    a, b = fingerprint(car), fingerprint(cat)
    assert hamming(a.phash, b.phash) > 12
    assert hamming(a.dhash, b.dhash) > 10


def test_content_hash_ignores_the_container_but_not_the_pixels(car):
    """
    Re-saving an unmodified image must stay in the exact tier: a different encoder or a
    stripped EXIF block changes the file while the photograph is the same one.
    """
    buf = io.BytesIO()
    car.save(buf, "PNG")
    buf.seek(0)
    assert content_hash(Image.open(buf)) == content_hash(car)
    assert content_hash(ImageEnhance.Brightness(car).enhance(1.05)) != content_hash(car)


# ─── The duplicate index ────────────────────────────────────────────────────

def test_an_empty_index_accuses_nobody(index, car):
    assert index.find_duplicates([car], claim_id="C1", user_id="u1") == []


def test_the_same_photograph_under_a_different_claim_is_caught(index, car):
    index.add_claim_images("C1", "u1", [car])
    matches = index.find_duplicates([car], claim_id="C2", user_id="u2")
    assert len(matches) == 1
    assert matches[0].kind == "exact"
    assert matches[0].prior_claim_id == "C1"
    assert matches[0].prior_user_id == "u1"
    assert "C1" in matches[0].describe()


def test_a_re_encoded_photograph_is_still_caught(index, car):
    """Exactly the case a cryptographic hash misses and this feature exists for."""
    index.add_claim_images("C1", "u1", [car])
    matches = index.find_duplicates([reencode(car, 40)], claim_id="C2", user_id="u2")
    assert len(matches) == 1
    assert matches[0].prior_claim_id == "C1"


def test_a_claim_does_not_match_itself(index, car):
    """
    A claimant may legitimately attach the same photograph twice, and reprocessing a claim
    must not turn it into a fraud case against itself.
    """
    index.add_claim_images("C1", "u1", [car])
    assert index.find_duplicates([car], claim_id="C1", user_id="u1") == []


def test_the_same_claimant_under_a_new_claim_is_still_reuse(index, car):
    """Resubmitting last year's damage as a new incident is the textbook case."""
    index.add_claim_images("C1", "u1", [car])
    matches = index.find_duplicates([car], claim_id="C2", user_id="u1")
    assert len(matches) == 1
    assert matches[0].prior_claim_id == "C1"


def test_a_different_photograph_is_not_a_duplicate(index, car, cat):
    index.add_claim_images("C1", "u1", [car])
    assert index.find_duplicates([cat], claim_id="C2", user_id="u2") == []


def test_exact_matches_outrank_near_matches(index, car):
    index.add_claim_images("C_near", "u1", [reencode(car, 40)])
    index.add_claim_images("C_exact", "u2", [car])
    matches = index.find_duplicates([car], claim_id="C3", user_id="u3")
    assert len(matches) == 1
    assert matches[0].kind == "exact"
    assert matches[0].prior_claim_id == "C_exact"


def test_reprocessing_a_claim_refreshes_rather_than_duplicates(index, car, cat):
    index.add_claim_images("C1", "u1", [car])
    index.add_claim_images("C1", "u1", [cat])
    assert index.count() == 1


def test_near_matching_can_be_switched_off(index, car, monkeypatch, tmp_path):
    cfg = tmp_path / "retrieval.yaml"
    cfg.write_text(
        "version: 1\n"
        "duplicate_detection:\n"
        "  enabled: true\n"
        "  near_duplicate: {enabled: false, max_phash_distance: 12, max_dhash_distance: 10}\n"
        "  ignore_same_claim: true\n"
        "  require_quality: [good, fair, poor]\n"
        "hybrid: {rrf_k: 60, top_k: 5, candidates_per_arm: 20,\n"
        "         dense: {backend: lsa, components: 64, min_df: 1}, metadata_filters: []}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AURELIX_RETRIEVAL_CONFIG", str(cfg))
    load_retrieval_config.cache_clear()
    try:
        index.add_claim_images("C1", "u1", [car])
        assert index.find_duplicates([reencode(car, 40)], claim_id="C2") == []   # near: off
        assert len(index.find_duplicates([car], claim_id="C2")) == 1             # exact: always
    finally:
        load_retrieval_config.cache_clear()


def test_unusable_images_are_not_indexable():
    """
    The composition with Phase 4.1. A near-featureless image has DCT coefficients bunched
    around the median, so its pHash moves 22 bits under a mere re-encode — measured. The
    quality gate already identifies that class, so it gates the index too.
    """
    assert indexable("good") and indexable("fair")
    assert not indexable("unusable")


# ─── Hybrid text retrieval ──────────────────────────────────────────────────

CORPUS = [
    Document("H1", "front bumper dented in a car park collision", {"object_category": "car"}),
    Document("H2", "rear bumper scratched when reversing", {"object_category": "car"}),
    Document("H3", "windscreen cracked by a stone on the motorway", {"object_category": "car"}),
    Document("H4", "laptop screen cracked after being dropped", {"object_category": "laptop"}),
    Document("H5", "laptop keyboard damaged by a spilled drink", {"object_category": "laptop"}),
    Document("H6", "parcel arrived with the seal torn open", {"object_category": "package"}),
]


@pytest.fixture
def retriever() -> HybridRetriever:
    return HybridRetriever().index(CORPUS)


def test_retrieval_finds_the_obvious_match(retriever):
    results = retriever.search("dent on the front bumper", filters={"object_category": "car"})
    assert results
    assert results[0].document.doc_id == "H1"


def test_metadata_filtering_is_absolute(retriever):
    """
    Retrieving a laptop claim to score a car claim is not a ranking imperfection, it is a
    wrong answer wearing the costume of a right one.
    """
    results = retriever.search("cracked screen", filters={"object_category": "car"})
    assert results
    assert all(r.document.metadata["object_category"] == "car" for r in results)
    assert "H4" not in {r.document.doc_id for r in results}


def test_filtering_happens_before_scoring_not_after(retriever):
    """A post-filter silently returns fewer than k, worst exactly when the filter matters."""
    results = retriever.search("damage", filters={"object_category": "laptop"}, top_k=2)
    assert len(results) == 2
    assert {r.document.doc_id for r in results} == {"H4", "H5"}


def test_both_arms_contribute(retriever):
    results = retriever.search("laptop screen cracked", filters={"object_category": "laptop"})
    top = results[0]
    assert top.document.doc_id == "H4"
    assert top.dense_rank is not None and top.sparse_rank is not None


def test_fusion_beats_either_arm_on_a_vocabulary_mismatch(retriever):
    """
    'windscreen' never appears as 'windshield' in the corpus, so a purely lexical arm has
    nothing to match on. The dense arm is what keeps the right document in the running.
    """
    results = retriever.search("windshield broken by a stone", filters={"object_category": "car"})
    assert "H3" in {r.document.doc_id for r in results}


def test_an_empty_corpus_returns_nothing_rather_than_raising():
    assert HybridRetriever().index([]).search("anything") == []


def test_a_filter_matching_nothing_returns_nothing(retriever):
    assert retriever.search("bumper", filters={"object_category": "spaceship"}) == []


def test_top_k_is_respected(retriever):
    assert len(retriever.search("damage", top_k=3)) == 3


def test_results_are_deterministic(retriever):
    a = [r.document.doc_id for r in retriever.search("bumper damage")]
    b = [r.document.doc_id for r in retriever.search("bumper damage")]
    assert a == b


def test_recall_at_5_on_a_labelled_probe_set(retriever):
    """A measurement, not an assertion of taste. Probes are paraphrases, not substrings."""
    probes = [
        ("my car's front bumper got dented in a car park", "car", "H1"),
        ("reversed into a post and scraped the back bumper", "car", "H2"),
        ("a stone chipped and cracked my windshield", "car", "H3"),
        ("dropped my laptop and the display is broken", "laptop", "H4"),
        ("spilled coffee on the laptop keys", "laptop", "H5"),
        ("the package seal was ripped when it arrived", "package", "H6"),
    ]
    hits = sum(
        expected in {r.document.doc_id
                     for r in retriever.search(q, filters={"object_category": cat}, top_k=5)}
        for q, cat, expected in probes
    )
    assert hits == len(probes), f"recall@5 = {hits}/{len(probes)}"


def test_the_gemini_backend_refuses_rather_than_silently_spending_quota():
    """
    It must fail loudly. A dense backend that quietly starts making paid API calls is a
    billing incident, and this project has one hard constraint.
    """
    with pytest.raises(NotImplementedError, match="quota"):
        GeminiEmbeddingBackend().fit(["anything"])


def test_an_unknown_backend_is_rejected_at_construction():
    with pytest.raises(ValueError, match="unknown dense backend"):
        HybridRetriever({"dense": {"backend": "wishful-thinking"}})


# ─── R030 end to end ────────────────────────────────────────────────────────
#
# `R030_duplicate_image_reuse` has sat in config/decision_rules.yaml since Phase 2 with
# nothing able to set its condition. These are the tests that say it is alive.

def _run(tmp_path, index, *, claim_id, user_id, image, monkeypatch):
    """Analyse one claim against a given index, with perception stubbed out."""
    from tests.test_backend_pipeline import GeminiSpy
    from agent_core.service import analyse_claim_events

    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal",
                        GeminiSpy(claim_id=claim_id))
    path = tmp_path / f"{claim_id}.jpg"
    image.save(path, "JPEG", quality=92)

    analysis = None
    for event in analyse_claim_events(
        user_id=user_id, user_claim="The front bumper is dented.", claim_object="car",
        image_paths=path.name, image_base_dir=str(tmp_path),
        claim_id=claim_id, image_index=index,
    ):
        if event["stage"] == "done":
            analysis = event["analysis"]
    return analysis


def test_r030_fires_when_a_photograph_is_reused(tmp_path, index, car, monkeypatch):
    first = _run(tmp_path, index, claim_id="CLM-100", user_id="u1", image=car,
                 monkeypatch=monkeypatch)
    assert first.duplicate_matches == []
    assert "R030_duplicate_image_reuse" not in first.verdict.rule_ids

    second = _run(tmp_path, index, claim_id="CLM-200", user_id="u2",
                  image=reencode(car, 70), monkeypatch=monkeypatch)

    assert second.duplicate_matches, "the reused photograph was not detected"
    assert "R030_duplicate_image_reuse" in second.verdict.rule_ids
    assert second.verdict.claim_status == "contradicted"
    assert "possible_manipulation" in second.verdict.risk_flags
    assert second.verdict.manual_review_required


def test_the_verdict_names_the_prior_claim(tmp_path, index, car, monkeypatch):
    """
    'An image was submitted before' is not actionable. A reviewer needs to know which
    claim, and the claimant is owed the same answer.
    """
    _run(tmp_path, index, claim_id="CLM-100", user_id="u1", image=car, monkeypatch=monkeypatch)
    second = _run(tmp_path, index, claim_id="CLM-200", user_id="u2", image=car,
                  monkeypatch=monkeypatch)
    assert "CLM-100" in second.verdict.justification
    assert "u1" in second.verdict.justification


def test_a_distinct_photograph_does_not_trigger_r030(tmp_path, index, car, cat, monkeypatch):
    _run(tmp_path, index, claim_id="CLM-100", user_id="u1", image=car, monkeypatch=monkeypatch)
    second = _run(tmp_path, index, claim_id="CLM-200", user_id="u2", image=cat,
                  monkeypatch=monkeypatch)
    assert second.duplicate_matches == []
    assert "R030_duplicate_image_reuse" not in second.verdict.rule_ids


def test_the_duplicate_check_happens_before_the_model_call(tmp_path, index, car, monkeypatch):
    """
    Ordering is load-bearing twice over: querying must see the index as it was *before*
    this claim, and a claim already provably a resubmission should not also be paid for.
    """
    from agent_core.service import PIPELINE_STAGES
    assert PIPELINE_STAGES.index("duplicate_check") < PIPELINE_STAGES.index("perception")
