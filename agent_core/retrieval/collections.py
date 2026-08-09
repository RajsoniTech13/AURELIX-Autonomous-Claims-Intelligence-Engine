"""
The three retrieval collections, and the index lifecycle around them.

    historical_claims   past claims + what was actually observed on them
    policy_rules        evidence requirements, chunked, each with a stable rule_id
    fraud_patterns      the curated playbook, for reviewer context

**Built offline, versioned, loaded once.** `services/vector_store.py` rebuilt its entire
vocabulary and IDF table inside every `search()` call, and was rebuilt from scratch at every
process start whether or not anything had changed. Here the corpus is written to disk by
`tools/build_index.py`, carries a manifest recording what it was built from, and is read at
startup.

**Why the manifest has a fingerprint.** A stale index is worse than no index, because it
answers confidently. Each collection records a hash of its source content, so
`IndexBundle.stale_collections()` can say which parts no longer match the data they came
from instead of leaving it to be noticed.

**Retrieval never decides anything.** These collections inform a human and cite rule ids;
they do not feed the fraud score and cannot move a verdict. A similarity score is not
evidence, and a verdict that cannot be traced to a rule id is the thing Phase 1 removed.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml

from agent_core.retrieval.hybrid import Document, HybridRetriever

INDEX_VERSION = 1
DEFAULT_INDEX_DIR = Path(".aurelix/index")

HISTORICAL_CLAIMS = "historical_claims"
POLICY_RULES = "policy_rules"
FRAUD_PATTERNS = "fraud_patterns"
COLLECTIONS = (HISTORICAL_CLAIMS, POLICY_RULES, FRAUD_PATTERNS)


def _fingerprint(documents: Sequence[Document]) -> str:
    """Content hash of a collection, so staleness is detectable rather than assumed."""
    digest = hashlib.sha256()
    for doc in sorted(documents, key=lambda d: d.doc_id):
        digest.update(doc.doc_id.encode())
        digest.update(doc.text.encode())
        digest.update(json.dumps(doc.metadata, sort_keys=True).encode())
    return digest.hexdigest()[:16]


# ─── Builders ───────────────────────────────────────────────────────────────

def build_historical_claims(
    rows: Iterable[Dict[str, str]],
    observed: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Document]:
    """
    Past claims, indexed on the narrative *plus what was actually observed*.

    Indexing the claimant's words alone would retrieve claims that sound alike; adding the
    observed part and severity retrieves claims that turned out alike, which is the question
    a reviewer is really asking.
    """
    observed = observed or {}
    documents: List[Document] = []
    for row in rows:
        claim_id = row.get("claim_id") or row.get("user_id", "")
        seen = observed.get(claim_id, {})
        summary = " ".join(filter(None, [
            row.get("user_claim", ""),
            f"observed {seen['part']}" if seen.get("part") else "",
            f"{seen['issue_type']}" if seen.get("issue_type") else "",
            f"severity {seen['severity']}" if seen.get("severity") else "",
        ]))
        documents.append(Document(
            doc_id=claim_id,
            text=summary,
            metadata={
                "object_category": (row.get("claim_object") or "").lower(),
                "user_id": row.get("user_id", ""),
                "observed_part": seen.get("part", ""),
                "damage_type": seen.get("issue_type", ""),
                "severity": seen.get("severity", ""),
                "final_verdict": seen.get("claim_status", ""),
            },
        ))
    return documents


def build_policy_rules(csv_path: Path) -> List[Document]:
    """
    Chunk the evidence requirements into individually retrievable, individually citable rules.

    One document per requirement rather than one per object category, because the compliance
    check needs to cite *which* requirement failed. `EV-CAR-COUNT` is an answer; "the car
    policy" is not.

    The ids are stable by construction — derived from the object category and the field name,
    never from row order — so rewording a requirement does not change what a stored citation
    refers to.
    """
    if not csv_path.exists():
        return []

    fields = [
        ("required_image_count", "COUNT",
         "Minimum number of photographs required for a {obj} claim: {value}."),
        ("required_visibility", "VISIBILITY",
         "Parts that must be visible in the evidence for a {obj} claim: {value}."),
        ("required_viewing_angle", "ANGLE",
         "Acceptable viewing angles for {obj} evidence: {value}."),
        ("required_evidence_type", "TYPE",
         "Acceptable evidence types for a {obj} claim: {value}."),
    ]

    documents: List[Document] = []
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            obj = (row.get("claim_object") or "").strip().lower()
            if not obj:
                continue
            for column, suffix, template in fields:
                value = (row.get(column) or "").strip()
                if not value:
                    continue
                documents.append(Document(
                    doc_id=f"EV-{obj.upper()}-{suffix}",
                    text=template.format(obj=obj, value=value.replace(";", ", ")),
                    metadata={
                        "object_category": obj,
                        "requirement": column,
                        "value": value,
                        "rule_id": f"EV-{obj.upper()}-{suffix}",
                    },
                ))
    return documents


def build_fraud_patterns(yaml_path: Path) -> List[Document]:
    if not yaml_path.exists():
        return []
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    documents: List[Document] = []
    for pattern in data.get("patterns", []):
        documents.append(Document(
            doc_id=pattern["pattern_id"],
            text=" ".join([pattern.get("title", ""), pattern.get("description", "")]).strip(),
            metadata={
                "pattern_id": pattern["pattern_id"],
                "title": pattern.get("title", ""),
                "reviewer_prompt": (pattern.get("reviewer_prompt") or "").strip(),
                "related_rules": pattern.get("related_rules", []),
                # Patterns apply to several categories, so the single-value filter used by
                # the other collections does not fit. Filtering here is by membership,
                # handled at query time.
                "object_categories": pattern.get("object_categories", []),
            },
        ))
    return documents


# ─── Bundle ─────────────────────────────────────────────────────────────────

@dataclass
class CollectionMeta:
    name: str
    count: int
    fingerprint: str
    built_at: str

    def to_dict(self) -> dict:
        return {"name": self.name, "count": self.count,
                "fingerprint": self.fingerprint, "built_at": self.built_at}


@dataclass
class IndexBundle:
    """All three collections plus their manifest. Built offline, loaded at startup."""
    directory: Path = field(default_factory=lambda: DEFAULT_INDEX_DIR)
    documents: Dict[str, List[Document]] = field(default_factory=dict)
    meta: Dict[str, CollectionMeta] = field(default_factory=dict)
    _retrievers: Dict[str, HybridRetriever] = field(default_factory=dict, repr=False)

    # ── lifecycle ──

    def upsert(self, name: str, documents: Sequence[Document]) -> int:
        """
        Merge documents into a collection by doc_id.

        Upsert rather than replace so a nightly build can add yesterday's claims without
        re-reading the entire history — and so a partial build cannot silently truncate a
        collection to whatever it happened to see.
        """
        if name not in COLLECTIONS:
            raise ValueError(f"unknown collection {name!r}; expected one of {COLLECTIONS}")
        merged = {d.doc_id: d for d in self.documents.get(name, [])}
        merged.update({d.doc_id: d for d in documents})
        self.documents[name] = list(merged.values())
        self._retrievers.pop(name, None)          # force a rebuild on next query
        self.meta[name] = CollectionMeta(
            name=name, count=len(self.documents[name]),
            fingerprint=_fingerprint(self.documents[name]),
            built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        return len(self.documents[name])

    def save(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        for name, docs in self.documents.items():
            (self.directory / f"{name}.json").write_text(json.dumps(
                [{"doc_id": d.doc_id, "text": d.text, "metadata": d.metadata} for d in docs],
                indent=1,
            ), encoding="utf-8")
        manifest = {
            "index_version": INDEX_VERSION,
            "collections": {n: m.to_dict() for n, m in self.meta.items()},
        }
        path = self.directory / "manifest.json"
        path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        return path

    @classmethod
    def load(cls, directory: Path | str = DEFAULT_INDEX_DIR) -> "IndexBundle":
        directory = Path(directory)
        bundle = cls(directory=directory)
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            return bundle

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("index_version") != INDEX_VERSION:
            # Refuse rather than guess. An index written by a different builder may have a
            # different document shape, and answering confidently from it is the failure
            # mode this whole manifest exists to prevent.
            raise ValueError(
                f"index at {directory} is version {manifest.get('index_version')}, "
                f"this build expects {INDEX_VERSION}. Rebuild with "
                f"`python -m agent_core.tools.build_index`."
            )

        for name, meta in manifest.get("collections", {}).items():
            path = directory / f"{name}.json"
            if not path.exists():
                continue
            bundle.documents[name] = [
                Document(doc_id=d["doc_id"], text=d["text"], metadata=d.get("metadata", {}))
                for d in json.loads(path.read_text(encoding="utf-8"))
            ]
            bundle.meta[name] = CollectionMeta(**meta)
        return bundle

    def stale_collections(self, current: Dict[str, Sequence[Document]]) -> List[str]:
        """Which collections no longer match the source data they were built from."""
        return [
            name for name, docs in current.items()
            if name not in self.meta or self.meta[name].fingerprint != _fingerprint(docs)
        ]

    # ── query ──

    def retriever(self, name: str) -> HybridRetriever:
        """Built on first use and cached. Never per query."""
        if name not in self._retrievers:
            self._retrievers[name] = HybridRetriever().index(self.documents.get(name, []))
        return self._retrievers[name]

    def search(
        self, name: str, query: str, *,
        filters: Optional[Dict[str, Any]] = None, top_k: Optional[int] = None,
    ):
        return self.retriever(name).search(query, filters=filters, top_k=top_k)

    def fraud_patterns_for(self, object_category: str, query: str, top_k: int = 3):
        """
        Patterns apply to several object categories at once, so membership filtering
        replaces the equality filter the other collections use.
        """
        results = self.search(FRAUD_PATTERNS, query, top_k=top_k * 3)
        return [
            r for r in results
            if not r.document.metadata.get("object_categories")
            or object_category.lower() in [
                c.lower() for c in r.document.metadata["object_categories"]
            ]
        ][:top_k]

    def policy_rules_for(self, object_category: str) -> List[Document]:
        """Every requirement that applies to a category, in citable form."""
        return [
            d for d in self.documents.get(POLICY_RULES, [])
            if d.metadata.get("object_category") == object_category.lower()
        ]
