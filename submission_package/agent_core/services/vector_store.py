import math
import numpy as np
from typing import List, Dict, Any, Tuple
import os
import csv

class SimpleVectorStore:
    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self.vectors: List[np.ndarray] = []
        self.vocab: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}

    def _tokenize(self, text: str) -> List[str]:
        # Simple word tokenization and normalization
        words = text.lower().replace("|", " ").replace(":", " ").replace(".", " ").replace(",", " ").split()
        return [w for w in words if len(w) > 2]

    def fit_and_index(self, docs: List[Dict[str, Any]], text_field: str = "user_claim"):
        self.documents = docs
        self.vocab = {}
        self.vectors = []
        
        # 1. Build Vocabulary and Term Frequency
        doc_terms = []
        for doc in docs:
            tokens = self._tokenize(doc.get(text_field, ""))
            doc_terms.append(tokens)
            for t in tokens:
                if t not in self.vocab:
                    self.vocab[t] = len(self.vocab)
                    
        # 2. Compute IDF
        num_docs = len(docs)
        self.idf = {}
        for term, idx in self.vocab.items():
            doc_count = sum(1 for tokens in doc_terms if term in tokens)
            self.idf[term] = math.log((1 + num_docs) / (1 + doc_count)) + 1
            
        # 3. Create TF-IDF Vectors
        for tokens in doc_terms:
            vec = np.zeros(len(self.vocab))
            for t in tokens:
                if t in self.vocab:
                    vec[self.vocab[t]] += 1
            # Apply IDF
            for term, idx in self.vocab.items():
                vec[idx] *= self.idf[term]
            # Normalize vector
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            self.vectors.append(vec)

    def search(self, query_text: str, top_k: int = 2) -> List[Tuple[Dict[str, Any], float]]:
        if not self.vectors:
            return []
            
        tokens = self._tokenize(query_text)
        query_vec = np.zeros(len(self.vocab))
        for t in tokens:
            if t in self.vocab:
                query_vec[self.vocab[t]] += 1
        
        # Apply IDF to query
        for term, idx in self.vocab.items():
            query_vec[idx] *= self.idf[term]
            
        # Normalize query vector
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm
            
        # Calculate Cosine Similarity
        results = []
        for idx, doc_vec in enumerate(self.vectors):
            similarity = float(np.dot(query_vec, doc_vec))
            results.append((self.documents[idx], similarity))
            
        # Sort by similarity desc
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

# Global single instance of vector store
vector_store = SimpleVectorStore()

def index_historical_claims(sample_claims_path: str):
    """
    Reads sample claims CSV and indexes them into the vector database.
    """
    if not os.path.exists(sample_claims_path):
        print(f"[VectorStore] Warning: Sample claims path '{sample_claims_path}' not found. Cannot index.")
        return
        
    print(f"[VectorStore] Indexing historical claims from {sample_claims_path}...")
    claims = []
    with open(sample_claims_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            claims.append(row)
            
    vector_store.fit_and_index(claims, text_field="user_claim")
    print(f"[VectorStore] Indexed {len(claims)} historical claims.")

def get_similar_claims(query_text: str, top_k: int = 2) -> List[Dict[str, Any]]:
    results = vector_store.search(query_text, top_k=top_k)
    # Return document data with the similarity score added to metadata
    formatted = []
    for doc, score in results:
        doc_copy = doc.copy()
        doc_copy["similarity_score"] = round(score, 3)
        formatted.append(doc_copy)
    return formatted
