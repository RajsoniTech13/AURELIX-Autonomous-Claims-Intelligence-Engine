"""
Where dense vectors live, behind one small interface.

    store.upsert(ids, vectors, metadata)
    store.search(query_vector, k, filters=None, restrict_to=None) -> [(id, cosine)]

Two backends:

* **`NumpyVectorStore`** — a matrix in memory, saved to a `.npz` file under `.aurelix/index/`.
  Exact search by one matrix–vector product. For the policy corpus (35 clauses) this is the
  right tool: an approximate index over 35 vectors would be slower to build than to scan,
  and less accurate.
* **`PgVectorStore`** — Postgres with the `pgvector` extension: an HNSW index under cosine
  distance, and metadata filtering inside the same SQL query. This is what the store becomes
  when the corpus or the number of processes outgrows one in-memory matrix: every worker
  shares one index, and the database does the filtering.

`make_vector_store()` picks pgvector when `DATABASE_URL` is Postgres and the extension is
available, and NumPy otherwise — which is what the free deploy (SQLite) uses.

**Filtering happens before ranking**, in both. Ranking first and filtering after returns
fewer than k results exactly when the filter matters most.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

import numpy as np

Hit = Tuple[str, float]


class VectorStore(Protocol):
    def upsert(self, ids: Sequence[str], vectors: np.ndarray,
               metadata: Sequence[Dict[str, Any]]) -> None: ...

    def search(self, query: np.ndarray, k: int, *, filters: Optional[Dict[str, Any]] = None,
               restrict_to: Optional[Iterable[str]] = None) -> List[Hit]: ...

    def count(self) -> int: ...


def _matches(meta: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
    return all(
        str(meta.get(key, "")).lower() == str(value).lower()
        for key, value in (filters or {}).items() if value not in (None, "")
    )


class NumpyVectorStore:
    def __init__(self, dim: Optional[int] = None):
        self.dim = dim
        self.ids: List[str] = []
        self.metadata: List[Dict[str, Any]] = []
        self.matrix = np.zeros((0, dim or 0), dtype=np.float32)

    def count(self) -> int:
        return len(self.ids)

    def upsert(self, ids: Sequence[str], vectors: np.ndarray,
               metadata: Sequence[Dict[str, Any]]) -> None:
        vectors = np.asarray(vectors, dtype=np.float32)
        if len(ids) == 0:
            return
        if self.dim is None or self.matrix.shape[0] == 0:
            self.dim = vectors.shape[1]
            if self.matrix.shape[0] == 0:
                self.matrix = np.zeros((0, self.dim), dtype=np.float32)
        if vectors.shape[1] != self.dim:
            raise ValueError(f"vector dimension {vectors.shape[1]} != store dimension {self.dim}")
        position = {doc_id: i for i, doc_id in enumerate(self.ids)}
        for doc_id, vector, meta in zip(ids, vectors, metadata):
            if doc_id in position:
                self.matrix[position[doc_id]] = vector
                self.metadata[position[doc_id]] = dict(meta)
            else:
                position[doc_id] = len(self.ids)
                self.ids.append(doc_id)
                self.metadata.append(dict(meta))
                self.matrix = np.vstack([self.matrix, vector[None, :]])

    def vector(self, doc_id: str) -> Optional[np.ndarray]:
        try:
            return self.matrix[self.ids.index(doc_id)]
        except ValueError:
            return None

    def search(self, query: np.ndarray, k: int, *, filters: Optional[Dict[str, Any]] = None,
               restrict_to: Optional[Iterable[str]] = None) -> List[Hit]:
        if not self.ids:
            return []
        allowed = set(restrict_to) if restrict_to is not None else None
        rows = [i for i, (doc_id, meta) in enumerate(zip(self.ids, self.metadata))
                if (allowed is None or doc_id in allowed) and _matches(meta, filters)]
        if not rows:
            return []
        scores = self.matrix[rows] @ np.asarray(query, dtype=np.float32)
        order = np.argsort(-scores, kind="stable")[:k]
        return [(self.ids[rows[i]], float(scores[i])) for i in order]

    # ── persistence ──

    def save(self, path: Path, identity: str) -> Path:
        """`identity` names the vector space; `load` refuses vectors from a different one."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, matrix=self.matrix, ids=np.asarray(self.ids, dtype=object),
                 metadata=np.asarray([json.dumps(m, sort_keys=True) for m in self.metadata], dtype=object),
                 identity=np.asarray(identity))
        return path

    @classmethod
    def load(cls, path: Path, identity: str) -> Optional["NumpyVectorStore"]:
        """None when the file is missing or was built in a different vector space."""
        path = Path(path)
        if not path.exists():
            return None
        data = np.load(path, allow_pickle=True)
        if str(data["identity"]) != identity:
            return None
        store = cls(dim=int(data["matrix"].shape[1]) if data["matrix"].size else None)
        store.matrix = data["matrix"].astype(np.float32)
        store.ids = [str(i) for i in data["ids"]]
        store.metadata = [json.loads(m) for m in data["metadata"]]
        return store


class PgVectorStore:
    """
    pgvector with an HNSW index under cosine distance (`vector_cosine_ops`).

    Vectors are passed as pgvector's text literal (`'[0.1,0.2,...]'::vector`), so the only
    client dependency is the SQLAlchemy Postgres driver already needed for `DATABASE_URL`.
    `<=>` is pgvector's cosine *distance*; the store reports `1 - distance`, a cosine
    similarity, so both backends return the same kind of score.
    """

    def __init__(self, engine, table: str, dim: int):
        if not table.replace("_", "").isalnum():
            raise ValueError("table name must be alphanumeric/underscore")
        self.engine, self.table, self.dim = engine, table, dim
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        from sqlalchemy import text
        with self.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(
                f"CREATE TABLE IF NOT EXISTS {self.table} ("
                f" id TEXT PRIMARY KEY, embedding vector({self.dim}) NOT NULL,"
                f" metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {self.table}_hnsw ON {self.table} "
                f"USING hnsw (embedding vector_cosine_ops)"
            ))

    @staticmethod
    def _literal(vector: np.ndarray) -> str:
        return "[" + ",".join(f"{float(x):.7f}" for x in vector) + "]"

    def count(self) -> int:
        from sqlalchemy import text
        with self.engine.connect() as conn:
            return int(conn.execute(text(f"SELECT count(*) FROM {self.table}")).scalar())

    def upsert(self, ids: Sequence[str], vectors: np.ndarray,
               metadata: Sequence[Dict[str, Any]]) -> None:
        from sqlalchemy import text
        statement = text(
            f"INSERT INTO {self.table} (id, embedding, metadata) "
            f"VALUES (:id, CAST(:embedding AS vector), CAST(:metadata AS jsonb)) "
            f"ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata"
        )
        with self.engine.begin() as conn:
            for doc_id, vector, meta in zip(ids, vectors, metadata):
                conn.execute(statement, {"id": doc_id, "embedding": self._literal(vector),
                                         "metadata": json.dumps(meta)})

    def search(self, query: np.ndarray, k: int, *, filters: Optional[Dict[str, Any]] = None,
               restrict_to: Optional[Iterable[str]] = None) -> List[Hit]:
        from sqlalchemy import text
        clauses, params = [], {"q": self._literal(query), "k": int(k)}
        if filters:
            # Pre-filter inside the query: `@>` is JSONB containment, served by the planner
            # before the ORDER BY, so k results come back even when the filter is selective.
            clauses.append("metadata @> CAST(:filters AS jsonb)")
            params["filters"] = json.dumps({key: v for key, v in filters.items() if v not in (None, "")})
        if restrict_to is not None:
            clauses.append("id = ANY(:ids)")
            params["ids"] = list(restrict_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = text(
            f"SELECT id, 1 - (embedding <=> CAST(:q AS vector)) AS score FROM {self.table} "
            f"{where} ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
        )
        with self.engine.connect() as conn:
            return [(row.id, float(row.score)) for row in conn.execute(sql, params)]


def pgvector_available(engine) -> bool:
    """True when the database is Postgres and the `vector` extension can be used."""
    if engine is None or engine.dialect.name != "postgresql":
        return False
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        return True
    except Exception:  # noqa: BLE001
        return False


def make_vector_store(table: str, dim: int, engine=None) -> VectorStore:
    """pgvector when the platform database supports it; the NumPy store otherwise."""
    if engine is None and os.getenv("DATABASE_URL", "").startswith("postgres"):
        from sqlalchemy import create_engine
        engine = create_engine(os.environ["DATABASE_URL"])
    if pgvector_available(engine):
        return PgVectorStore(engine, table, dim)
    return NumpyVectorStore(dim)
