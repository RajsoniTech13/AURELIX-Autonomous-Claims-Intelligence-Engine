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

**The dense arm is pluggable** (`hybrid.dense.backend` in `config/retrieval.yaml`):

* `lsa` — TF-IDF then a truncated SVD in numpy. Retrieves on term co-occurrence, costs
  nothing, needs no model. Not a transformer embedding, and not described as one.
* `fastembed` — a real sentence-embedding model (bge-small-en-v1.5) run locally on CPU.
* `gemini` — Gemini embeddings, quota-ledgered and refused unless explicitly authorised.

The two embedding backends live in `retrieval/embeddings.py`. If an embedding model cannot
be loaded, the retriever falls back to LSA and says so, rather than failing the request.

**Metadata filtering is applied before scoring**, not as a post-filter over the top-k.
Post-filtering silently returns fewer than k results, and does so most often exactly when
the corpus is dominated by another category — the case the filter exists for.
"""
from __future__ import annotations

import math
import os
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
    # Raw per-arm scores. The fused RRF score says how a document *ranked*, not how well it
    # *matched*, so a "not in the policy" threshold has to look at these instead.
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "doc_id": self.document.doc_id,
            "score": round(self.score, 6),
            "dense_rank": self.dense_rank,
            "sparse_rank": self.sparse_rank,
            "dense_score": None if self.dense_score is None else round(self.dense_score, 6),
            "sparse_score": None if self.sparse_score is None else round(self.sparse_score, 6),
            "metadata": dict(self.document.metadata),
        }


class DenseBackend(Protocol):
    """
    Swappable so an embedding model can replace LSA without touching the fusion.

    `encode` is for documents, `encode_query` for the question: some embedding models embed
    the two differently. `identity` names the vector space, so vectors saved by one model
    are never compared with a query embedded by another.
    """

    identity: str

    def fit(self, texts: Sequence[str]) -> None: ...
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...
    def encode_query(self, text: str) -> np.ndarray: ...


class LSABackend:
    """
    TF-IDF followed by a truncated SVD. Deterministic, offline, free.

    Vectors are L2-normalised at both ends so a dot product is a cosine.
    """

    name = "lsa"

    def __init__(self, components: int = 64, min_df: int = 1, **_: object):
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

    @property
    def identity(self) -> str:
        # LSA is fitted to its corpus, so its vectors are never reused across builds.
        return f"lsa:{self.components}:{self.min_df}"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if self.projection.size == 0:
            return np.zeros((len(texts), 1))
        vectors = self._tfidf([tokenize(t) for t in texts]) @ self.projection
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1.0, norms)

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


# Imported here, after LSABackend, because embeddings.py has no dependency on this module and
# the registry is the one place that needs both.
from agent_core.retrieval.embeddings import (  # noqa: E402
    EmbeddingUnavailable,
    FastEmbedBackend,
    GeminiEmbeddingBackend,
)
from agent_core.retrieval.vector_store import NumpyVectorStore  # noqa: E402

_BACKENDS = {"lsa": LSABackend, "fastembed": FastEmbedBackend, "gemini": GeminiEmbeddingBackend}


class HybridRetriever:
    """Dense + BM25 + RRF, with mandatory metadata filtering."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, dense: Optional[DenseBackend] = None):
        cfg = config or load_retrieval_config()["hybrid"]
        self.cfg = cfg
        dense_cfg = dict(cfg.get("dense", {}))
        backend_name = dense_cfg.pop("backend", "lsa")
        # An operational override, so the embedding model can be switched off on a live
        # instance (memory pressure, a bad model download) without a code change or deploy.
        # The test suite sets it to `lsa` so it never downloads a model.
        backend_name = os.getenv("AURELIX_DENSE_BACKEND") or backend_name
        if dense is None and backend_name not in _BACKENDS:
            raise ValueError(f"unknown dense backend {backend_name!r}; choose from {sorted(_BACKENDS)}")
        # `dense` is injectable so tests can use a fake embedder with no model download.
        self.dense: DenseBackend = dense or _BACKENDS[backend_name](**dense_cfg)
        self._lsa_cfg = {k: dense_cfg[k] for k in ("components", "min_df") if k in dense_cfg}

        self.documents: List[Document] = []
        self.store = NumpyVectorStore()
        self._bm25: Optional[BM25Okapi] = None
        self._token_sets: List[set] = []
        # Set when the configured embedding model could not be used and LSA stood in.
        self.dense_fallback: Optional[str] = None
        self.last_build: Dict[str, int] = {"embedded": 0, "reused": 0}

    # ── index ──

    def index(self, documents: Iterable[Document],
              previous: Optional[NumpyVectorStore] = None,
              embed_documents: bool = True) -> "HybridRetriever":
        """
        Build both arms once. Called at index-build time, never per query.

        `previous` is a store built earlier in the same vector space. A document whose
        `content_hash` matches the one stored there keeps its vector; only new or changed
        documents are embedded. That is what makes a rebuild after editing one clause cost
        one embedding instead of thirty-five.

        `embed_documents=False` is the serving path. Embedding the corpus is a build-time job:
        measured, it grows the process by ~139 MB of ONNX working memory for 35 clauses,
        which a 512 MB instance cannot spare. Without saved vectors the retriever falls back
        to LSA rather than embedding inside the web process; with them it loads the model
        only to embed the question, on first use.
        """
        self.documents = list(documents)
        self.store = NumpyVectorStore()
        texts = [d.text for d in self.documents]
        if not texts:
            self._bm25 = None
            return self

        tokens = [tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(tokens)
        self._token_sets = [set(t) for t in tokens]
        try:
            self._index_dense(previous, embed_documents)
        except EmbeddingUnavailable as exc:
            # Degrade, do not fail: a retriever without its embedding model still retrieves,
            # on term co-occurrence. The reason is kept so /ready and the eval can report it.
            self.dense_fallback = str(exc)
            self.dense = LSABackend(**self._lsa_cfg)
            self._index_dense(None)
        return self

    def _index_dense(self, previous: Optional[NumpyVectorStore], embed_documents: bool = True) -> None:
        self.dense.fit([d.text for d in self.documents])
        reusable: Dict[str, np.ndarray] = {}
        if previous is not None:
            for doc in self.documents:
                stored = previous.vector(doc.doc_id)
                meta = previous.metadata[previous.ids.index(doc.doc_id)] if stored is not None else {}
                if stored is not None and meta.get("content_hash") == _content_hash(doc):
                    reusable[doc.doc_id] = stored

        missing = [d for d in self.documents if d.doc_id not in reusable]
        if missing and not embed_documents and not isinstance(self.dense, LSABackend):
            raise EmbeddingUnavailable(
                f"{len(missing)} document(s) have no saved vectors and embedding at serve time "
                f"is disabled; run `python -m agent_core.tools.build_index`"
            )
        fresh = self.dense.encode([d.text for d in missing]) if missing else np.zeros((0, 0))
        vectors = dict(reusable)
        vectors.update({d.doc_id: v for d, v in zip(missing, fresh)})

        self.store.upsert(
            [d.doc_id for d in self.documents],
            np.vstack([vectors[d.doc_id] for d in self.documents]),
            [{**d.metadata, "content_hash": _content_hash(d)} for d in self.documents],
        )
        self.last_build = {"embedded": len(missing), "reused": len(reusable)}

    # ── query ──

    def search(
        self,
        query: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        mode: str = "hybrid",
    ) -> List[RetrievalResult]:
        """
        `mode` is `hybrid` (both arms, RRF-fused), `dense` or `sparse` — the single-arm modes
        exist so the evaluation can measure what fusion adds, rather than assert it.
        """
        if not self.documents:
            return []
        if mode not in ("hybrid", "dense", "sparse"):
            raise ValueError(f"unknown mode {mode!r}")

        top_k = top_k or int(self.cfg.get("top_k", 5))
        pool = int(self.cfg.get("candidates_per_arm", 20))
        rrf_k = int(self.cfg.get("rrf_k", 60))

        allowed = self._filter(filters)
        if not allowed:
            return []

        dense_ranks, dense_scores = self._rank_dense(query, allowed, pool) if mode != "sparse" else ([], {})
        sparse_ranks, sparse_scores = self._rank_sparse(query, allowed, pool) if mode != "dense" else ([], {})

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
                dense_score=dense_scores.get(idx),
                sparse_score=sparse_scores.get(idx),
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

    def _rank_dense(self, query: str, allowed: Sequence[int], pool: int) -> tuple[List[int], Dict[int, float]]:
        if self.store.count() == 0:
            return [], {}
        position = {doc.doc_id: i for i, doc in enumerate(self.documents)}
        hits = self.store.search(self.dense.encode_query(query), pool,
                                 restrict_to=[self.documents[i].doc_id for i in allowed])
        ranks = [position[doc_id] for doc_id, _ in hits]
        return ranks, {position[doc_id]: score for doc_id, score in hits}

    def _rank_sparse(self, query: str, allowed: Sequence[int], pool: int) -> tuple[List[int], Dict[int, float]]:
        if self._bm25 is None:
            return [], {}
        query_tokens = tokenize(query)
        all_scores = self._bm25.get_scores(query_tokens)
        # A document sharing no word with the query is not a lexical match, however it ranks.
        # Judged by overlap, not by score: in a small corpus a word in exactly half the
        # documents gets an IDF of zero, so a genuine match can score 0.
        terms = set(query_tokens)
        matching = [i for i in allowed if self._token_sets[i] & terms]
        if not matching:
            return [], {}
        scores = np.asarray([all_scores[i] for i in matching])
        order = np.argsort(-scores, kind="stable")[:pool]
        ranks = [matching[i] for i in order]
        return ranks, {matching[i]: float(scores[i]) for i in order}


def _content_hash(doc: Document) -> str:
    """The document's own hash if it carries one, else a hash of its text and metadata."""
    if doc.metadata.get("content_hash"):
        return str(doc.metadata["content_hash"])
    import hashlib
    import json
    payload = doc.text + json.dumps({k: v for k, v in doc.metadata.items() if k != "content_hash"},
                                    sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
