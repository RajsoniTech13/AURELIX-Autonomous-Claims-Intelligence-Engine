"""
Vector stores, hybrid fusion, and incremental indexing. Hermetic: a fake embedder stands in
for the model, so nothing is downloaded.

* **Vector stores** behave identically: upsert, cosine search, filtering *before* ranking,
  and a NumPy store that refuses vectors saved from a different model.
* **Incremental indexing** re-embeds only changed documents.
* **A server never embeds the corpus** — it reuses saved vectors or falls back to LSA, because
  embedding inside a 512 MB web process was measured at ~139 MB extra.
"""
from __future__ import annotations

import hashlib
import os
from typing import List

import numpy as np
import pytest

from agent_core.retrieval.collections import POLICY_RULES, IndexBundle
from agent_core.retrieval.embeddings import EmbeddingUnavailable
from agent_core.retrieval.hybrid import Document, HybridRetriever, LSABackend, tokenize
from agent_core.retrieval.policy_corpus import build_policy_clauses
from agent_core.retrieval.vector_store import NumpyVectorStore, PgVectorStore

CFG = {"rrf_k": 60, "top_k": 5, "candidates_per_arm": 20, "dense": {"backend": "lsa"}}


class FakeEmbedder:
    """Hashed bag of words: deterministic, instant, and similar texts get similar vectors."""

    name = "fastembed"            # so the copilot's threshold lookup treats it as a model
    identity = "fake:128"

    def __init__(self):
        self.encoded: List[str] = []

    def fit(self, texts):
        return None

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(128, dtype=np.float32)
        for token in tokenize(text):
            v[int(hashlib.md5(token.encode()).hexdigest(), 16) % 128] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode(self, texts):
        self.encoded.extend(texts)
        return np.vstack([self._vec(t) for t in texts]) if texts else np.zeros((0, 128))

    def encode_query(self, text):
        return self._vec(text)


# ─── Vector stores ──────────────────────────────────────────────────────────

def test_numpy_store_ranks_by_cosine_and_filters_before_ranking():
    store = NumpyVectorStore()
    store.upsert(["a", "b", "c"], np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32),
                 [{"kind": "clause"}, {"kind": "requirement"}, {"kind": "clause"}])
    assert [i for i, _ in store.search(np.array([1, 0]), 3)] == ["a", "b", "c"]
    # Filtered first: the nearest match overall ("b") is not eligible, so k results still come back.
    assert [i for i, _ in store.search(np.array([0.8, 0.6]), 2, filters={"kind": "clause"})] == ["a", "c"]
    assert [i for i, _ in store.search(np.array([1, 0]), 3, restrict_to=["c"])] == ["c"]


def test_numpy_store_upsert_replaces_rather_than_duplicates():
    store = NumpyVectorStore()
    store.upsert(["a"], np.array([[1.0, 0.0]]), [{}])
    store.upsert(["a"], np.array([[0.0, 1.0]]), [{"v": 2}])
    assert store.count() == 1
    assert store.vector("a").tolist() == [0.0, 1.0]


def test_numpy_store_rejects_a_mismatched_dimension():
    store = NumpyVectorStore()
    store.upsert(["a"], np.array([[1.0, 0.0]]), [{}])
    with pytest.raises(ValueError, match="dimension"):
        store.upsert(["b"], np.array([[1.0, 0.0, 0.0]]), [{}])


def test_numpy_store_round_trips_and_refuses_another_vector_space(tmp_path):
    store = NumpyVectorStore()
    store.upsert(["a", "b"], np.array([[1.0, 0.0], [0.0, 1.0]]), [{"x": 1}, {"x": 2}])
    path = store.save(tmp_path / "v.npz", identity="model-A")
    loaded = NumpyVectorStore.load(path, identity="model-A")
    assert loaded.ids == ["a", "b"] and loaded.metadata == [{"x": 1}, {"x": 2}]
    assert np.allclose(loaded.matrix, store.matrix)
    # Vectors from a different model are not comparable with this model's queries.
    assert NumpyVectorStore.load(path, identity="model-B") is None
    assert NumpyVectorStore.load(tmp_path / "missing.npz", identity="model-A") is None


@pytest.mark.skipif(not os.getenv("AURELIX_TEST_PG_URL"),
                    reason="needs a Postgres with pgvector: set AURELIX_TEST_PG_URL to run")
def test_pgvector_store_matches_the_numpy_store():
    from sqlalchemy import create_engine
    engine = create_engine(os.environ["AURELIX_TEST_PG_URL"])
    store = PgVectorStore(engine, "aurelix_test_vectors", dim=2)
    with engine.begin() as conn:
        from sqlalchemy import text
        conn.execute(text("DELETE FROM aurelix_test_vectors"))
    store.upsert(["a", "b", "c"], np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32),
                 [{"kind": "clause"}, {"kind": "requirement"}, {"kind": "clause"}])
    assert [i for i, _ in store.search(np.array([1, 0]), 3)] == ["a", "b", "c"]
    assert [i for i, _ in store.search(np.array([0.8, 0.6]), 2, filters={"kind": "clause"})] == ["a", "c"]


def test_pgvector_store_validates_its_table_name():
    with pytest.raises(ValueError):
        PgVectorStore(engine=None, table="x; DROP TABLE claims", dim=2)


# ─── Retrieval: fusion, incremental indexing, serving mode ──────────────────

def test_hybrid_fuses_both_arms_and_reports_raw_scores():
    fake = FakeEmbedder()
    retriever = HybridRetriever(CFG, dense=fake).index(build_policy_clauses())
    top = retriever.search("wear and tear rust", top_k=3)
    assert top[0].document.doc_id == "EXC-2"
    assert top[0].dense_rank is not None and top[0].sparse_rank is not None
    assert top[0].dense_score is not None and top[0].sparse_score > 0
    assert [r.document.doc_id for r in retriever.search("rust", mode="sparse", top_k=1)] == ["EXC-2"]


def test_a_document_sharing_no_word_with_the_query_is_not_a_bm25_match():
    retriever = HybridRetriever(CFG).index([Document("a", "front bumper dent"), Document("b", "laptop hinge")])
    assert [r.document.doc_id for r in retriever.search("bumper", mode="sparse")] == ["a"]


def test_an_unchanged_rebuild_embeds_nothing_and_an_edit_embeds_one():
    docs = build_policy_clauses()
    first = HybridRetriever(CFG, dense=FakeEmbedder()).index(docs)
    assert first.last_build == {"embedded": len(docs), "reused": 0}

    again = HybridRetriever(CFG, dense=FakeEmbedder()).index(docs, previous=first.store)
    assert again.last_build == {"embedded": 0, "reused": len(docs)}

    edited = [Document(d.doc_id, d.text + " Edited.", {**d.metadata, "content_hash": "changed"})
              if d.doc_id == "EXC-2" else d for d in docs]
    fake = FakeEmbedder()
    third = HybridRetriever(CFG, dense=fake).index(edited, previous=first.store)
    assert third.last_build == {"embedded": 1, "reused": len(docs) - 1}
    assert len(fake.encoded) == 1


def test_a_server_never_embeds_the_corpus_it_falls_back_to_lsa():
    fake = FakeEmbedder()
    retriever = HybridRetriever(CFG, dense=fake).index(build_policy_clauses(), embed_documents=False)
    assert fake.encoded == []
    assert isinstance(retriever.dense, LSABackend)
    assert "embedding at serve time is disabled" in retriever.dense_fallback
    assert retriever.search("rust", top_k=1)            # still retrieves


def test_an_unloadable_model_degrades_to_lsa_rather_than_failing():
    class Broken(FakeEmbedder):
        def encode(self, texts):
            raise EmbeddingUnavailable("no model on disk")

    retriever = HybridRetriever(CFG, dense=Broken()).index(build_policy_clauses())
    assert isinstance(retriever.dense, LSABackend) and "no model on disk" in retriever.dense_fallback
    assert retriever.search("rust", top_k=1)


def test_the_bundle_saves_vectors_and_a_server_reuses_them(tmp_path, monkeypatch):
    """Build offline with a model; load as a server; the server embeds nothing."""
    monkeypatch.setattr("agent_core.retrieval.collections.HybridRetriever",
                        lambda *a, **k: HybridRetriever(CFG, dense=FakeEmbedder()))
    build = IndexBundle(directory=tmp_path)
    build.upsert(POLICY_RULES, build_policy_clauses())
    build.retriever(POLICY_RULES)
    build.save()
    assert (tmp_path / f"{POLICY_RULES}.vectors.npz").exists()

    served = IndexBundle.load(tmp_path, embed_documents=False)
    retriever = served.retriever(POLICY_RULES)
    assert retriever.dense_fallback is None
    assert retriever.last_build == {"embedded": 0, "reused": 35}
