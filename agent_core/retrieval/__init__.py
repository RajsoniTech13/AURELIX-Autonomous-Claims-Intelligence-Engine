"""
Retrieval layer: hybrid text search, and the image index behind `R030_duplicate_image_reuse`.
"""
from agent_core.retrieval.hashing import ImageFingerprint, dhash, fingerprint, hamming, phash
from agent_core.retrieval.hybrid import Document, HybridRetriever, RetrievalResult
from agent_core.retrieval.image_index import (
    DuplicateMatch,
    ImageIndex,
    IndexedImage,
    content_hash,
    indexable,
    load_retrieval_config,
)

__all__ = [
    "ImageFingerprint", "fingerprint", "phash", "dhash", "hamming",
    "Document", "HybridRetriever", "RetrievalResult",
    "ImageIndex", "IndexedImage", "DuplicateMatch", "content_hash", "indexable",
    "load_retrieval_config",
]
