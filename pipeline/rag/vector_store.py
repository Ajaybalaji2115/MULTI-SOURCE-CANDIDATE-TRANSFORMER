"""
pipeline/rag/vector_store.py

Manages indexing and vector search for candidate profiles.
Saves and loads candidate representations and their embeddings to a file-based index (rag_index.json).
Performs local cosine similarity ranking.
"""
import json
import logging
import os
from typing import Any, Dict, List, Tuple

from .document_formatter import format_candidate_for_rag
from .models import get_embedding

logger = logging.getLogger(__name__)

# Try to import numpy for optimized vector math
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
    logger.info("Numpy is not available. Using pure Python for vector calculations.")


class VectorStore:
    """
    A simple file-based vector database that stores candidates,
    their formatted text representation, and their generated embedding vectors.
    """
    def __init__(self, index_path: str = "output/rag_index.json"):
        self.index_path = index_path
        self.entries: List[Dict[str, Any]] = []

    def load(self) -> bool:
        """Load index from file. Returns True if successful, False otherwise."""
        if not os.path.exists(self.index_path):
            logger.warning(f"Index file {self.index_path} does not exist.")
            self.entries = []
            return False
        
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                self.entries = json.load(f)
            logger.info(f"Loaded {len(self.entries)} candidates from index.")
            return True
        except Exception as e:
            logger.error(f"Failed to load RAG index from {self.index_path}: {e}")
            self.entries = []
            return False

    def save(self) -> bool:
        """Save index to file."""
        try:
            os.makedirs(os.path.dirname(self.index_path) or ".", exist_ok=True)
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(self.entries)} candidates to index at {self.index_path}.")
            return True
        except Exception as e:
            logger.error(f"Failed to save RAG index to {self.index_path}: {e}")
            return False

    def index_candidates(self, profiles: List[Dict[str, Any]], rebuild: bool = True):
        """
        Takes canonical profile dicts, converts them to text,
        generates embeddings, and stores them in the index.
        """
        if not rebuild:
            # Load existing first
            self.load()
            existing_ids = {entry["candidate_id"] for entry in self.entries}
        else:
            self.entries = []
            existing_ids = set()

        for profile in profiles:
            candidate_id = profile.get("candidate_id")
            if not candidate_id:
                # Skip if no identifier
                continue
            
            if candidate_id in existing_ids:
                # Update logic (remove old first)
                self.entries = [e for e in self.entries if e["candidate_id"] != candidate_id]

            text_rep = format_candidate_for_rag(profile)
            logger.info(f"Generating embedding for candidate: {profile.get('full_name') or candidate_id}")
            vector = get_embedding(text_rep)

            self.entries.append({
                "candidate_id": candidate_id,
                "text_representation": text_rep,
                "embedding": vector,
                "profile": profile
            })
            existing_ids.add(candidate_id)

        self.save()

    def search(self, query: str, limit: int = 3) -> List[Tuple[Dict[str, Any], float]]:
        """
        Embeds the query, computes similarity with all stored profiles,
        and returns the top matches with similarity scores.
        """
        if not self.entries:
            # Try to load
            self.load()
            if not self.entries:
                return []

        query_vector = get_embedding(query)
        scored_entries = []

        for entry in self.entries:
            sim = self._cosine_similarity(query_vector, entry["embedding"])
            scored_entries.append((entry, sim))

        # Sort by similarity descending
        scored_entries.sort(key=lambda x: x[1], reverse=True)
        return scored_entries[:limit]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec1 or not vec2:
            return 0.0
            
        if _NUMPY_AVAILABLE:
            a = np.array(vec1)
            b = np.array(vec2)
            denom = np.linalg.norm(a) * np.linalg.norm(b)
            if denom == 0:
                return 0.0
            return float(np.dot(a, b) / denom)
        
        # Pure Python fallback
        dot = sum(x * y for x, y in zip(vec1, vec2))
        norm_a = sum(x**2 for x in vec1) ** 0.5
        norm_b = sum(x**2 for x in vec2) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
