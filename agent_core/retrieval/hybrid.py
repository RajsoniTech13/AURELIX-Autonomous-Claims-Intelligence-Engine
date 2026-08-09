"""
Hybrid retrieval: dense + sparse, fused by Reciprocal Rank Fusion, filtered on metadata.

Replaces `services/vector_store.py`, a hand-rolled TF-IDF store that rebuilt its entire
vocabulary and IDF table on every call and had no metadata filtering at all — so scoring a
car claim happily returned laptop claims, and the index was rebuilt per process start
regardless of whether anything had changed.

**Why RRF rather than a weighted score blend.** The two arms produce scores on
incomparable scales: cosine similarity is bounded in [-1, 1], BM25 is unbounded and corpus
dependent. Blending them requires a normalisation and a weight, both of which have to be
re-fitted whenever the corpus changes, and neither of which anybody ever re-fits. RRF needs
only the ranks, so it has one constant and no calibration debt.

**Why LSA for the dense arm.** It retrieves on term co-occurrence rather than exact overlap,
which is what "dense" is for here, and it costs nothing: a truncated SVD in numpy, no
network, no quota. It is **not** a transformer embedding and this module does not pretend
otherwise — `GeminiEmbeddingBackend` implements the same interface for when spending request
budget on embeddings is authorised.

**Metadata filtering is applied before scoring**, not as a post-filter over the top-k.
Post-filtering silently returns fewer than k results, and does so most often exactly when
the corpus is dominated by another category — the case the filter exists for.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

import numpy as np
from rank_bm25 import BM25Okapi

from agent_core.retrieval.image_index import load_retrieval_config

_TOKEN = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> List[str]:
    """Lowercase word tokens of length >= 2. Shared by both arms so they see one corpus."""
    return [t for t in _TOKEN.findall((text or "").lower()) if len(t) > 1]


@dataclass
class Document:
    doc_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    document: Document
    score: float
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "doc_id": self.document.doc_id,
            "score": round(self.score, 6),
            "dense_rank": self.dense_rank,
            "sparse_rank": self.sparse_rank,
            "metadata": dict(self.document.metadata),
        }


class DenseBackend(Protocol):
    """Swappable so an embedding model can replace LSA without touching the fusion."""

    def fit(self, texts: Sequence[str]) -> None: ...
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class LSABackend:
    """
    TF-IDF followed by a truncated SVD. Deterministic, offline, free.

    Vectors are L2-normalised at both ends so a dot product is a cosine.
    """

    def __init__(self, components: int = 64, min_df: int = 1):
        self.components = components
        self.min_df = min_df
        self.vocab: Dict[str, int] = {}
        self.idf: np.ndarray = np.zeros(0)
        self.projection: np.ndarray = np.zeros((0, 0))

    def fit(self, texts: Sequence[str]) -> None:
        docs = [tokenize(t) for t in texts]
        df: Dict[str, int] = {}
        for tokens in docs:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1

        self.vocab = {t: i for i, t in enumerate(sorted(t for t, c in df.items() if c >= self.min_df))}
        if not self.vocab or not docs:
            self.idf = np.zeros(0)
            self.projection = np.zeros((0, 0))
            return

        n = len(docs)
        self.idf = np.array([
            math.log((1 + n) / (1 + df[t])) + 1.0 for t in self.vocab
        ], dtype=np.float64)

        matrix = self._tfidf(docs)
        # Truncated SVD. `components` is capped by the data — asking for 64 dimensions from
        # a 20-document corpus would otherwise produce pure noise columns.
        k = int(min(self.components, min(matrix.shape) - 1)) if min(matrix.shape) > 1 else 1
        _, _, vt = np.linalg.svd(matrix, full_matrices=False)
        self.projection = vt[:k].T

    def _tfidf(self, docs: Sequence[Sequence[str]]) -> np.ndarray:
        matrix = np.zeros((len(docs), len(self.vocab)), dtype=np.float64)
        for row, tokens in enumerate(docs):
            for term in tokens:
                idx = self.vocab.get(term)
                if idx is not None:
                    matrix[row, idx] += 1.0
        matrix *= self.idf
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1.0, norms)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if self.projection.size == 0:
            return np.zeros((len(texts), 1))
        vectors = self._tfidf([tokenize(t) for t in texts]) @ self.projection
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1.0, norms)


class GeminiEmbeddingBackend:
    """
    Placeholder for `gemini-embedding-001` behind the same interface.

    Deliberately not implemented. Embedding generation spends request budget, and the brief
    is explicit that quota is not to be spent on it without approval. The interface exists
    so switching backends is a config change (`hybrid.dense.backend`) rather than a rewrite —
    and so that "we chose not to spend quota" stays visible in the code instead of becoming
    an undocumented absence.
    """

    def fit(self, texts: Sequence[str]) -> None:
        raise NotImplementedError(
            "Gemini embeddings are not enabled: generating them spends request quota. "
            "Set hybrid.dense.backend: lsa, or authorise the request budget first."
        )

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        raise NotImplementedError(self.fit.__doc__)


_BACKENDS = {"lsa": LSABackend, "gemini": GeminiEmbeddingBackend}


class HybridRetriever:
    """Dense + BM25 + RRF, with mandatory metadata filtering."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or load_retrieval_config()["hybrid"]
        self.cfg = cfg
        dense_cfg = cfg.get("dense", {})
        backend_name = dense_cfg.get("backend", "lsa")
        if backend_name not in _BACKENDS:
            raise ValueError(f"unknown dense backend {backend_name!r}; choose from {sorted(_BACKENDS)}")
        self.dense: DenseBackend = _BACKENDS[backend_name](
            components=dense_cfg.get("components", 64), min_df=dense_cfg.get("min_df", 1),
        ) if backend_name == "lsa" else _BACKENDS[backend_name]()

        self.documents: List[Document] = []
        self._vectors: np.ndarray = np.zeros((0, 0))
        self._bm25: Optional[BM25Okapi] = None

    # ── index ──

    def index(self, documents: Iterable[Document]) -> "HybridRetriever":
        """
        Build both arms once. Called at index-build time, never per query.

        The store this replaces re-derived its vocabulary and IDF table inside `search`,
        which made every retrieval O(corpus).
        """
        self.documents = list(documents)
        texts = [d.text for d in self.documents]
        if not texts:
            self._vectors = np.zeros((0, 0))
            self._bm25 = None
            return self

        self.dense.fit(texts)
        self._vectors = self.dense.encode(texts)
        self._bm25 = BM25Okapi([tokenize(t) for t in texts])
        return self

    # ── query ──

    def search(
        self,
        query: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
    ) -> List[RetrievalResult]:
        if not self.documents:
            return []

        top_k = top_k or int(self.cfg.get("top_k", 5))
        pool = int(self.cfg.get("candidates_per_arm", 20))
        rrf_k = int(self.cfg.get("rrf_k", 60))

        allowed = self._filter(filters)
        if not allowed:
            return []

        dense_ranks = self._rank_dense(query, allowed, pool)
        sparse_ranks = self._rank_sparse(query, allowed, pool)

        fused: Dict[int, float] = {}
        for ranks in (dense_ranks, sparse_ranks):
            for rank, idx in enumerate(ranks, start=1):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + rank)

        ordered = sorted(fused.items(), key=lambda kv: (-kv[1], self.documents[kv[0]].doc_id))
        results = []
        for idx, score in ordered[:top_k]:
            results.append(RetrievalResult(
                document=self.documents[idx], score=score,
                dense_rank=dense_ranks.index(idx) + 1 if idx in dense_ranks else None,
                sparse_rank=sparse_ranks.index(idx) + 1 if idx in sparse_ranks else None,
            ))
        return results

    def _filter(self, filters: Optional[Dict[str, Any]]) -> List[int]:
        """
        Pre-filter to the indices a query is allowed to see.

        Mandatory by design: retrieving laptop claims to score a car claim is not a
        ranking imperfection, it is a wrong answer that looks like a right one.
        """
        if not filters:
            return list(range(len(self.documents)))
        keep = []
        for i, doc in enumerate(self.documents):
            if all(
                str(doc.metadata.get(key, "")).lower() == str(value).lower()
                for key, value in filters.items() if value not in (None, "")
            ):
                keep.append(i)
        return keep

    def _rank_dense(self, query: str, allowed: Sequence[int], pool: int) -> List[int]:
        if self._vectors.size == 0:
            return []
        scores = self._vectors[list(allowed)] @ self.dense.encode([query])[0]
        order = np.argsort(-scores)[:pool]
        return [allowed[i] for i in order]

    def _rank_sparse(self, query: str, allowed: Sequence[int], pool: int) -> List[int]:
        if self._bm25 is None:
            return []
        all_scores = self._bm25.get_scores(tokenize(query))
        scores = np.asarray([all_scores[i] for i in allowed])
        order = np.argsort(-scores)[:pool]
        return [allowed[i] for i in order]
