"""
Dense-embedding backends for the hybrid retriever.

Two real embedding models behind the `DenseBackend` interface that LSA already implements:

* **`FastEmbedBackend`** — a local ONNX model (default `BAAI/bge-small-en-v1.5`, 384 dims,
  67 MB, MIT) run by `fastembed` on CPU. Free, offline after the first download, no quota.
* **`GeminiEmbeddingBackend`** — Gemini's embedding model through the existing client's
  quota ledger. **Refuses unless explicitly authorised**, because every call spends from a
  free daily budget the public demo depends on.

LSA stays the fallback: it needs no model download, and if `fastembed` is missing or the
model cannot be loaded, the retriever still works — on term co-occurrence instead of meaning.

Which backend is used is `hybrid.dense.backend` in `config/retrieval.yaml`. The choice was
made from measurements on the golden question set (`evaluation/rag/report.md`), not by
assumption.

Vectors are L2-normalised on the way out, so a dot product is a cosine everywhere.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np

logger = logging.getLogger("aurelix.embeddings")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = REPO_ROOT / ".aurelix" / "models"


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


class EmbeddingUnavailable(RuntimeError):
    """The embedding model could not be loaded or run. Callers fall back to LSA."""


class QuotaNotAuthorised(RuntimeError):
    """An embedding call would spend free-tier request quota that nobody authorised."""


class FastEmbedBackend:
    """
    A pretrained local model. `fit` does nothing — there is nothing to learn from the
    corpus — and the model is loaded on first use, not at construction, so importing the
    retriever never costs the ~90 MB the model takes in memory.
    """

    name = "fastembed"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", query_prefix: str = "",
                 cache_dir: Optional[str] = None, threads: Optional[int] = None, **_: object):
        self.model_name = model
        self.query_prefix = query_prefix or ""
        self.cache_dir = str(cache_dir or os.getenv("AURELIX_MODEL_DIR") or DEFAULT_MODEL_DIR)
        self.threads = threads
        self._model = None
        self._lock = threading.Lock()

    @property
    def identity(self) -> str:
        """Names the vector space. Vectors from two identities must never be compared."""
        return f"fastembed:{self.model_name}:{self.query_prefix!r}"

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from fastembed import TextEmbedding
                        self._model = TextEmbedding(
                            model_name=self.model_name, cache_dir=self.cache_dir,
                            threads=self.threads,
                        )
                    except Exception as exc:  # noqa: BLE001 - surfaced as one typed error
                        raise EmbeddingUnavailable(
                            f"could not load {self.model_name}: {type(exc).__name__}: {exc}"
                        ) from exc
        return self._model

    def fit(self, texts: Sequence[str]) -> None:
        return None

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0))
        vectors = list(self._load().passage_embed(list(texts)))
        return _normalise(np.asarray(vectors, dtype=np.float32))

    def encode_query(self, text: str) -> np.ndarray:
        vector = next(iter(self._load().query_embed(self.query_prefix + text)))
        return _normalise(np.asarray([vector], dtype=np.float32))[0]


class GeminiEmbeddingBackend:
    """
    `gemini-embedding-2` through `services/gemini_client.py`, so every call is recorded in the
    same persisted quota ledger as perception and counted the same way.

    Off unless **both** the config selects it and `AURELIX_ALLOW_GEMINI_EMBEDDINGS=1` is set.
    Two switches on purpose: a config edit alone must not be able to start spending the
    demo's daily budget. It was not run against the live API in this project.
    """

    name = "gemini"

    def __init__(self, model: str = "gemini-embedding-2", output_dimensionality: Optional[int] = None,
                 client=None, **_: object):
        self.model_name = model
        self.output_dimensionality = output_dimensionality
        self._client = client

    @property
    def identity(self) -> str:
        return f"gemini:{self.model_name}:{self.output_dimensionality}"

    @staticmethod
    def authorised() -> bool:
        return os.getenv("AURELIX_ALLOW_GEMINI_EMBEDDINGS", "").strip() in {"1", "true", "yes"}

    def _embed(self, texts: Sequence[str], task_type: str) -> np.ndarray:
        if not self.authorised():
            raise QuotaNotAuthorised(
                "Gemini embeddings spend free-tier request quota shared with the public demo. "
                "Set AURELIX_ALLOW_GEMINI_EMBEDDINGS=1 to authorise it, or use the local "
                "fastembed backend, which costs nothing."
            )
        from google.genai import types

        from agent_core.services import gemini_client
        if gemini_client.remaining_requests(self.model_name) <= 0:
            raise gemini_client.DailyQuotaExhausted(f"{self.model_name} daily budget spent",
                                                    model=self.model_name)
        client = self._client or gemini_client._get_client()
        config = types.EmbedContentConfig(task_type=task_type,
                                          output_dimensionality=self.output_dimensionality)
        gemini_client._quota_ledger.record_request(self.model_name)   # one request per batch
        response = client.models.embed_content(model=self.model_name, contents=list(texts), config=config)
        return _normalise(np.asarray([e.values for e in response.embeddings], dtype=np.float32))

    def fit(self, texts: Sequence[str]) -> None:
        return None

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts, "RETRIEVAL_DOCUMENT") if texts else np.zeros((0, 0))

    def encode_query(self, text: str) -> np.ndarray:
        return self._embed([text], "RETRIEVAL_QUERY")[0]
