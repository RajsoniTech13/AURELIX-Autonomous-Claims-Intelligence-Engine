"""
The policy document, split into individually citable clauses.

Why clause-level chunks. The copilot's whole value is that every sentence of an answer can be
traced to a clause a person can read. Fixed-size chunking (every 500 tokens, say) would cut
clauses in half and merge neighbours, so a citation would point at "a chunk" rather than at
`EXC-2`. The policy is written with one `### <ID> · <Title>` heading per clause, so the
natural chunk boundary is also the citation boundary.

Why a contextual header. A clause on its own — "Damage that has already been the subject of a
claim is excluded" — does not say it is an *exclusion*. Each chunk's text starts with where it
sits in the document (`AURELIX Protection Policy v1.0 › Part 3 — Exclusions › EXC-3 ...`), so
a question phrased as "what's not covered" can reach it by the section name as well as by
its wording.

Each chunk carries a content hash, so the index build re-embeds only clauses whose text
actually changed.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml

from agent_core.retrieval.hybrid import Document

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = REPO_ROOT / "knowledge" / "policies" / "aurelix_protection_policy_v1.md"
DEFAULT_RULE_MAP = REPO_ROOT / "knowledge" / "policies" / "rule_clause_map.yaml"

_CLAUSE_HEADING = re.compile(r"^### ([A-Z]+-\d+) · (.+)$")
_SECTION_HEADING = re.compile(r"^## (.+)$")
_APPLIES_TO = re.compile(r"^applies_to:\s*(.+)$")

CLAUSE_KIND = "clause"


@dataclass
class Clause:
    clause_id: str
    title: str
    section: str
    body: str
    applies_to: List[str]
    doc_id: str
    doc_title: str
    version: str
    effective_date: str
    metadata: Dict[str, str] = field(default_factory=dict)

    @property
    def header(self) -> str:
        return f"{self.doc_title} v{self.version} › {self.section} › {self.clause_id} {self.title}"

    @property
    def text(self) -> str:
        """What is indexed and embedded: the contextual header, then the clause."""
        return f"{self.header}\n{self.body}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    def to_document(self) -> Document:
        return Document(
            doc_id=self.clause_id,
            text=self.text,
            metadata={
                "kind": CLAUSE_KIND,
                "doc": self.doc_id,
                "clause_id": self.clause_id,
                "title": self.title,
                "section": self.section,
                "version": self.version,
                "effective_date": self.effective_date,
                # "all" or one category; `object_categories` keeps the full list.
                "object_category": self.applies_to[0] if len(self.applies_to) == 1 else "all",
                "object_categories": self.applies_to,
                "content_hash": self.content_hash,
            },
        )


def _front_matter(text: str) -> tuple[Dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("policy document must start with a YAML front-matter block")
    _, meta, rest = text.split("---\n", 2)
    return yaml.safe_load(meta) or {}, rest


def parse_policy(path: Path = DEFAULT_POLICY) -> List[Clause]:
    """
    Split the policy into clauses. Strict: a clause without an `applies_to` line, or a
    duplicated clause id, is an authoring error and fails the build rather than indexing
    something half-labelled.
    """
    meta, body = _front_matter(Path(path).read_text(encoding="utf-8"))
    for key in ("doc_id", "title", "version", "effective_date"):
        if not meta.get(key):
            raise ValueError(f"policy front matter is missing {key!r}")

    clauses: List[Clause] = []
    section = ""
    current: Dict[str, object] | None = None
    lines: List[str] = []

    def close() -> None:
        if current is None:
            return
        text_lines = [ln for ln in lines if not _APPLIES_TO.match(ln.strip())]
        applies = next((_APPLIES_TO.match(ln.strip()).group(1) for ln in lines
                        if _APPLIES_TO.match(ln.strip())), None)
        if applies is None:
            raise ValueError(f"clause {current['id']} has no applies_to line")
        clauses.append(Clause(
            clause_id=str(current["id"]),
            title=str(current["title"]).strip(),
            section=str(current["section"]),
            body=" ".join(" ".join(text_lines).split()),
            applies_to=[a.strip().lower() for a in applies.split(",") if a.strip()],
            doc_id=str(meta["doc_id"]), doc_title=str(meta["title"]),
            version=str(meta["version"]), effective_date=str(meta["effective_date"]),
        ))

    for raw in body.splitlines():
        if raw.startswith("> "):
            continue                                   # the synthetic-wording disclaimer
        heading = _CLAUSE_HEADING.match(raw)
        section_heading = _SECTION_HEADING.match(raw)
        if heading:
            close()
            current, lines = {"id": heading.group(1), "title": heading.group(2), "section": section}, []
        elif section_heading:
            close()
            current, lines = None, []
            section = section_heading.group(1).strip()
        elif current is not None:
            lines.append(raw)
    close()

    ids = [c.clause_id for c in clauses]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate clause ids: {sorted(duplicates)}")
    return clauses


def build_policy_clauses(path: Path = DEFAULT_POLICY) -> List[Document]:
    """The clauses as retrieval documents, for the `policy_rules` collection."""
    if not Path(path).exists():
        return []
    return [c.to_document() for c in parse_policy(path)]


def load_rule_clause_map(path: Path = DEFAULT_RULE_MAP) -> Dict[str, object]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
