"""
Offline retrieval evaluation for the Policy Copilot. Zero API cost.

Run: `python -m agent_core.evaluation.evaluate_rag`

What it answers. "Does hybrid retrieval help?" and "does a real embedding model beat LSA?"
are empirical questions, so this measures them on `evaluation/rag/golden.jsonl` — 40
questions about the policy, each labelled with the clause(s) that answer it, 8 of them
deliberately unanswerable — instead of asserting the answer.

For every retrieval configuration it reports, over the 32 answerable questions:

* **recall@k** — the share of a question's gold clauses found in the top k, averaged;
* **MRR** — 1 / the rank of the first gold clause, averaged;
* **nDCG@5** — rank-discounted gain with binary relevance, normalised by the ideal ordering;

and, over all 40, **not-found accuracy**: whether a single score threshold separates "the
policy answers this" from "it does not". Picking that threshold on the same 40 questions
would grade the method on its own answer key, so the report also gives a **leave-one-out**
figure — each question classified by a threshold chosen on the other 39.

It also measures what each configuration costs: corpus embedding time, median query latency,
and peak memory in a fresh process.

**Caveat, stated here and in the report:** the golden set and the policy were written by the
same author. Paraphrase questions were written to avoid the policy's wording, but this is a
40-question in-distribution set, not an external benchmark.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REPO_ROOT / "evaluation" / "rag" / "golden.jsonl"
REPORT = REPO_ROOT / "evaluation" / "rag" / "report.md"
RESULTS = REPO_ROOT / "evaluation" / "rag" / "results.json"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RERANK_POOL = 10


def load_golden(path: Path = GOLDEN) -> List[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ─── Metrics ────────────────────────────────────────────────────────────────

def recall_at(ranked: Sequence[str], gold: Sequence[str], k: int) -> float:
    return len(set(ranked[:k]) & set(gold)) / len(gold)


def reciprocal_rank(ranked: Sequence[str], gold: Sequence[str]) -> float:
    return next((1.0 / i for i, doc in enumerate(ranked, start=1) if doc in gold), 0.0)


def ndcg_at(ranked: Sequence[str], gold: Sequence[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, doc in enumerate(ranked[:k], start=1) if doc in gold)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def best_threshold(scores: Sequence[float], answerable: Sequence[bool]) -> Tuple[float, int]:
    """
    The cut that classifies the most questions correctly: score >= t means "answerable".
    Ties go to the lower threshold, which wrongly refuses fewer real questions.
    """
    candidates = sorted(set(scores))
    cuts = [candidates[0] - 1e-9] + [(a + b) / 2 for a, b in zip(candidates, candidates[1:])] \
        + [candidates[-1] + 1e-9]
    best_t, best_correct = cuts[0], -1
    for t in cuts:
        correct = sum((s >= t) == a for s, a in zip(scores, answerable))
        if correct > best_correct:
            best_t, best_correct = t, correct
    return best_t, best_correct


def leave_one_out(scores: Sequence[float], answerable: Sequence[bool]) -> int:
    correct = 0
    for i in range(len(scores)):
        rest_s = [s for j, s in enumerate(scores) if j != i]
        rest_a = [a for j, a in enumerate(answerable) if j != i]
        t, _ = best_threshold(rest_s, rest_a)
        correct += (scores[i] >= t) == answerable[i]
    return correct


# ─── Configurations ─────────────────────────────────────────────────────────

@dataclass
class Outcome:
    ranked: List[str]
    score: float          # the "how well does anything match" signal used for not-found
    latency_ms: float


@dataclass
class Config:
    name: str
    describe: str
    run: Callable[[str], Outcome]
    build_ms: float = 0.0
    fallback: Optional[str] = None
    extra: Dict[str, object] = field(default_factory=dict)


def _retriever(backend: str, documents, **dense_kwargs):
    from agent_core.retrieval.hybrid import HybridRetriever
    from agent_core.retrieval.image_index import load_retrieval_config
    cfg = dict(load_retrieval_config()["hybrid"])
    cfg["dense"] = {"backend": backend, **dense_kwargs}
    started = time.perf_counter()
    retriever = HybridRetriever(cfg).index(documents)
    return retriever, (time.perf_counter() - started) * 1000


def build_configs(documents, include_embeddings: bool = True) -> List[Config]:
    configs: List[Config] = []
    lsa, lsa_ms = _retriever("lsa", documents, components=64, min_df=1)

    def via(retriever, mode: str, signal: str) -> Callable[[str], Outcome]:
        def run(question: str) -> Outcome:
            started = time.perf_counter()
            results = retriever.search(question, top_k=RERANK_POOL, mode=mode)
            ms = (time.perf_counter() - started) * 1000
            if signal == "sparse":
                top = max((r.sparse_score or 0.0 for r in results), default=0.0)
            else:
                top = max((r.dense_score or 0.0 for r in results), default=0.0)
            return Outcome([r.document.doc_id for r in results], top, ms)
        return run

    configs.append(Config("bm25", "BM25 only", via(lsa, "sparse", "sparse"), lsa_ms))
    configs.append(Config("dense-lsa", "LSA (TF-IDF + SVD) only", via(lsa, "dense", "dense"), lsa_ms))
    configs.append(Config("hybrid-lsa", "BM25 + LSA, RRF", via(lsa, "hybrid", "dense"), lsa_ms))
    if not include_embeddings:
        return configs

    bge, bge_ms = _retriever("fastembed", documents, model=EMBED_MODEL, query_prefix="")
    if bge.dense_fallback:
        print(f"fastembed unavailable, embedding configurations skipped: {bge.dense_fallback}")
        return configs
    bge_p, bge_p_ms = _retriever("fastembed", documents, model=EMBED_MODEL, query_prefix=BGE_QUERY_PREFIX)

    configs.append(Config("dense-bge", f"{EMBED_MODEL} only", via(bge, "dense", "dense"), bge_ms))
    configs.append(Config("hybrid-bge", f"BM25 + {EMBED_MODEL}, RRF", via(bge, "hybrid", "dense"), bge_ms))
    configs.append(Config("dense-bge-prefix", f"{EMBED_MODEL} only, bge query instruction",
                          via(bge_p, "dense", "dense"), bge_p_ms))
    configs.append(Config("hybrid-bge-prefix", f"BM25 + {EMBED_MODEL}, bge query instruction, RRF",
                          via(bge_p, "hybrid", "dense"), bge_p_ms))

    from agent_core.retrieval.embeddings import DEFAULT_MODEL_DIR
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    encoder = TextCrossEncoder(model_name=RERANK_MODEL, cache_dir=str(DEFAULT_MODEL_DIR))
    texts = {d.doc_id: d.text for d in documents}

    def reranked(question: str) -> Outcome:
        started = time.perf_counter()
        pool = bge.search(question, top_k=RERANK_POOL, mode="hybrid")
        ids = [r.document.doc_id for r in pool]
        scores = list(encoder.rerank(question, [texts[i] for i in ids]))
        order = sorted(zip(ids, scores), key=lambda p: -p[1])
        ms = (time.perf_counter() - started) * 1000
        return Outcome([i for i, _ in order], max(scores) if scores else float("-inf"), ms)

    configs.append(Config("hybrid-bge+rerank",
                          f"BM25 + {EMBED_MODEL}, RRF, then {RERANK_MODEL} over the top {RERANK_POOL}",
                          reranked, bge_ms))
    return configs


# ─── Evaluation ─────────────────────────────────────────────────────────────

def evaluate(config: Config, golden: List[dict]) -> Dict[str, object]:
    outcomes = {row["id"]: config.run(row["question"]) for row in golden}
    answerable = [row for row in golden if row["gold"]]

    def mean(values): return round(statistics.mean(values), 4)

    scores = [outcomes[r["id"]].score for r in golden]
    labels = [bool(r["gold"]) for r in golden]
    threshold, correct = best_threshold(scores, labels)
    refused = sum(1 for s, a in zip(scores, labels) if a and s < threshold)
    accepted = sum(1 for s, a in zip(scores, labels) if not a and s >= threshold)

    by_type: Dict[str, float] = {}
    for kind in ("exact", "paraphrase", "multi"):
        rows = [r for r in answerable if r["type"] == kind]
        by_type[kind] = mean([recall_at(outcomes[r["id"]].ranked, r["gold"], 5) for r in rows])

    misses = [
        {"id": r["id"], "question": r["question"], "gold": r["gold"],
         "top3": outcomes[r["id"]].ranked[:3]}
        for r in answerable if not set(outcomes[r["id"]].ranked[:5]) & set(r["gold"])
    ]

    return {
        "name": config.name, "describe": config.describe,
        "recall@1": mean([recall_at(outcomes[r["id"]].ranked, r["gold"], 1) for r in answerable]),
        "recall@3": mean([recall_at(outcomes[r["id"]].ranked, r["gold"], 3) for r in answerable]),
        "recall@5": mean([recall_at(outcomes[r["id"]].ranked, r["gold"], 5) for r in answerable]),
        "hit@5": mean([float(bool(set(outcomes[r["id"]].ranked[:5]) & set(r["gold"]))) for r in answerable]),
        "mrr": mean([reciprocal_rank(outcomes[r["id"]].ranked, r["gold"]) for r in answerable]),
        "ndcg@5": mean([ndcg_at(outcomes[r["id"]].ranked, r["gold"], 5) for r in answerable]),
        "recall@5_by_type": by_type,
        "not_found": {
            "threshold": round(threshold, 4),
            "in_sample_accuracy": round(correct / len(golden), 4),
            "leave_one_out_accuracy": round(leave_one_out(scores, labels) / len(golden), 4),
            "answerable_refused": refused, "unanswerable_accepted": accepted,
        },
        "median_query_ms": round(statistics.median(o.latency_ms for o in outcomes.values()), 2),
        "build_ms": round(config.build_ms, 1),
        "misses_at_5": misses,
    }


# ─── Memory, measured in a fresh process per backend ────────────────────────

_PROBE = {
    "lsa": "from agent_core.retrieval.hybrid import HybridRetriever as H; "
           "r = H({'rrf_k':60,'top_k':5,'candidates_per_arm':20,'dense':{'backend':'lsa'}}).index(docs); "
           "r.search('is rust covered')",
    "fastembed": "from agent_core.retrieval.hybrid import HybridRetriever as H; "
                 f"r = H({{'rrf_k':60,'top_k':5,'candidates_per_arm':20,'dense':{{'backend':'fastembed','model':'{EMBED_MODEL}'}}}}).index(docs); "
                 "r.search('is rust covered')",
    "fastembed+rerank": "from agent_core.retrieval.hybrid import HybridRetriever as H; "
                        "from fastembed.rerank.cross_encoder import TextCrossEncoder as X; "
                        "from agent_core.retrieval.embeddings import DEFAULT_MODEL_DIR as M; "
                        f"r = H({{'rrf_k':60,'top_k':5,'candidates_per_arm':20,'dense':{{'backend':'fastembed','model':'{EMBED_MODEL}'}}}}).index(docs); "
                        f"x = X(model_name='{RERANK_MODEL}', cache_dir=str(M)); "
                        "list(x.rerank('is rust covered', [d.text for d in docs[:10]]))",
}


# What the deployed API actually holds: the whole app imported, the embedding model loaded,
# and questions embedded — but not the corpus, whose vectors are built offline. This is the
# number that has to fit in a 512 MB instance.
_SERVING_PROBE = (
    "import resource, sys\n"
    "import platform_backend.main\n"
    "from fastembed import TextEmbedding\n"
    "from agent_core.retrieval.embeddings import DEFAULT_MODEL_DIR\n"
    f"m = TextEmbedding('{EMBED_MODEL}', cache_dir=str(DEFAULT_MODEL_DIR), threads=1)\n"
    "for q in ['is rust covered', 'how many photos do I need for a car'] * 20:\n"
    "    list(m.query_embed(q))\n"
    "rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
    "print(rss / (1024 * 1024) if sys.platform == 'darwin' else rss / 1024)\n"
)


def serving_rss_mb() -> Optional[float]:
    out = subprocess.run([sys.executable, "-c", _SERVING_PROBE], cwd=REPO_ROOT, capture_output=True, text=True)
    try:
        return round(float(out.stdout.strip().splitlines()[-1]), 1)
    except (ValueError, IndexError):
        return None


def peak_rss_mb(backend: str) -> Optional[float]:
    code = (
        "import resource, sys\n"
        "from agent_core.retrieval.policy_corpus import build_policy_clauses\n"
        "docs = build_policy_clauses()\n"
        f"{_PROBE[backend]}\n"
        "rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "print(rss / (1024 * 1024) if sys.platform == 'darwin' else rss / 1024)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
    try:
        return round(float(out.stdout.strip().splitlines()[-1]), 1)
    except (ValueError, IndexError):
        return None


# ─── Report ─────────────────────────────────────────────────────────────────

def write_report(results: List[dict], memory: Dict[str, Optional[float]], golden: List[dict]) -> None:
    from collections import Counter
    counts = Counter(r["type"] for r in golden)
    lines = [
        "# Policy Copilot — retrieval evaluation",
        "",
        "Generated by `python -m agent_core.evaluation.evaluate_rag`. Zero API calls: every",
        "model here runs locally.",
        "",
        f"**Golden set:** `evaluation/rag/golden.jsonl` — {len(golden)} questions "
        f"({counts['exact']} exact-term, {counts['paraphrase']} paraphrase, {counts['multi']} multi-clause, "
        f"{counts['unanswerable']} unanswerable) over the 35-clause synthetic policy.",
        "",
        "> **Caveat.** The policy and the questions were written by the same author. Paraphrases",
        "> avoid the policy's wording, but this is a small in-distribution set, not an external",
        "> benchmark. Differences of one or two questions (≈3 points) are within noise.",
        "",
        "**Not measured: Gemini embeddings.** `GeminiEmbeddingBackend` implements the same",
        "interface, but embedding the corpus and 40 questions would spend requests from the free",
        "daily budget the public demo's claim analysis depends on, and it refuses to run without",
        "`AURELIX_ALLOW_GEMINI_EMBEDDINGS=1`. Run this script with that set and",
        "`hybrid.dense.backend: gemini` to add the row.",
        "",
        "## Ranking quality (32 answerable questions)",
        "",
        "| configuration | recall@1 | recall@3 | recall@5 | hit@5 | MRR | nDCG@5 | median query |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        lines.append(
            f"| `{r['name']}` | {r['recall@1']:.3f} | {r['recall@3']:.3f} | {r['recall@5']:.3f} | "
            f"{r['hit@5']:.3f} | {r['mrr']:.3f} | {r['ndcg@5']:.3f} | {r['median_query_ms']:.1f} ms |"
        )
    lines += [
        "",
        "recall@k is the share of a question's gold clauses in the top k (a 3-clause question can",
        "score at most 1/3 at k=1). hit@5 is whether *any* gold clause made the top 5.",
        "",
        "### recall@5 by question type",
        "",
        "| configuration | exact | paraphrase | multi-clause |",
        "| :--- | ---: | ---: | ---: |",
    ]
    for r in results:
        t = r["recall@5_by_type"]
        lines.append(f"| `{r['name']}` | {t['exact']:.3f} | {t['paraphrase']:.3f} | {t['multi']:.3f} |")
    lines += [
        "",
        "## \"Not in the policy\" detection (all 40 questions)",
        "",
        "Each configuration's own match signal is thresholded: top cosine for dense and hybrid,",
        "top BM25 score for `bm25`, top cross-encoder score for the reranker. In-sample picks the",
        "threshold on all 40 questions; leave-one-out classifies each question with a threshold",
        "chosen on the other 39, which is the honest estimate.",
        "",
        "| configuration | threshold | in-sample | leave-one-out | real questions refused | unanswerable accepted |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        n = r["not_found"]
        lines.append(
            f"| `{r['name']}` | {n['threshold']:.4f} | {n['in_sample_accuracy']:.3f} | "
            f"{n['leave_one_out_accuracy']:.3f} | {n['answerable_refused']} | {n['unanswerable_accepted']} |"
        )
    lines += [
        "",
        "## Cost",
        "",
        "| backend | peak memory, fresh process | corpus build |",
        "| :--- | ---: | ---: |",
    ]
    build = {r["name"]: r["build_ms"] for r in results}
    for backend, mb in memory.items():
        if backend == "serving":
            continue
        key = {"lsa": "hybrid-lsa", "fastembed": "hybrid-bge", "fastembed+rerank": "hybrid-bge+rerank"}[backend]
        b = build.get(key)
        lines.append(f"| {backend} | {mb if mb is not None else 'n/a'} MB | "
                     f"{f'{b:.0f} ms' if b is not None else 'n/a'} |")
    if memory.get("serving") is not None:
        lines.append(f"| **serving: whole API + model, questions only** | **{memory['serving']} MB** | — |")
    lines += [
        "",
        "The **serving** row is what the deployed API holds: the whole app imported and the model",
        "loaded, embedding only questions — clause vectors are built offline by",
        "`tools/build_index`. Render's free instance has 512 MB.",
        "",
        "Peak memory is `ru_maxrss` of a fresh Python process that loads the policy, builds the",
        "retriever and answers one query — the retriever's own footprint, not the whole API.",
        "The corpus build for an embedding backend includes model load and embedding 35 clauses",
        "(models already downloaded to `.aurelix/models/`).",
        "",
        "## Misses at 5",
        "",
    ]
    for r in results:
        if r["misses_at_5"]:
            lines.append(f"**`{r['name']}`**")
            for m in r["misses_at_5"]:
                lines.append(f"- {m['id']} “{m['question']}” — gold {', '.join(m['gold'])}; "
                             f"top 3: {', '.join(m['top3'])}")
            lines.append("")
    REPORT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Offline retrieval evaluation (no API calls)")
    p.add_argument("--no-embeddings", action="store_true", help="LSA and BM25 only; no model download")
    p.add_argument("--no-memory", action="store_true", help="skip the fresh-process memory probes")
    args = p.parse_args()

    from agent_core.retrieval.policy_corpus import build_policy_clauses
    documents = build_policy_clauses()
    golden = load_golden()

    configs = build_configs(documents, include_embeddings=not args.no_embeddings)
    results = [evaluate(c, golden) for c in configs]
    memory = {} if args.no_memory else {
        b: peak_rss_mb(b) for b in (["lsa"] if args.no_embeddings else ["lsa", "fastembed", "fastembed+rerank"])
    }
    if not args.no_memory and not args.no_embeddings:
        memory["serving"] = serving_rss_mb()
    write_report(results, memory, golden)
    RESULTS.write_text(json.dumps({"results": results, "memory_mb": memory}, indent=1), encoding="utf-8")

    for r in results:
        print(f"{r['name']:20} recall@5 {r['recall@5']:.3f}  MRR {r['mrr']:.3f}  nDCG@5 {r['ndcg@5']:.3f}  "
              f"not-found LOO {r['not_found']['leave_one_out_accuracy']:.3f}  {r['median_query_ms']:.1f} ms")
    print(f"memory: {memory}")
    print(f"wrote {REPORT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
