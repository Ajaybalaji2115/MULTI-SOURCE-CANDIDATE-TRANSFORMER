"""
pipeline/rag package

Provides Retrieval-Augmented Generation capabilities for the candidate data profiles.
"""
from typing import Dict, Any, List

from .document_formatter import format_candidate_for_rag
from .models import get_embedding, generate_answer, get_api_key
from .vector_store import VectorStore

def query_rag(query: str, index_path: str = "output/rag_index.json", limit: int = 3) -> Dict[str, Any]:
    """
    Search candidate profiles using the query and generate an LLM response.
    
    Returns a dict with:
      - "query": original query string
      - "answer": the LLM generated answer
      - "retrieved_candidates": list of matching candidate profiles with similarity scores
    """
    store = VectorStore(index_path=index_path)
    # Search top matches
    results = store.search(query, limit=limit)
    
    if not results:
        return {
            "query": query,
            "answer": "No candidates found in the database. Please verify if candidate indexing has been run.",
            "retrieved_candidates": []
        }
        
    # Form context string
    context_blocks = []
    retrieved_info = []
    
    for idx, (entry, score) in enumerate(results):
        context_blocks.append(f"--- Candidate #{idx+1} (Similarity: {score:.4f}) ---")
        context_blocks.append(entry["text_representation"])
        context_blocks.append("")
        
        # Keep track for final return
        retrieved_info.append({
            "candidate_id": entry["candidate_id"],
            "full_name": entry["profile"].get("full_name") or "Unknown",
            "emails": entry["profile"].get("emails", []),
            "score": score,
            "text_representation": entry["text_representation"]
        })
        
    context_str = "\n".join(context_blocks)
    
    # Generate response
    answer = generate_answer(query, context_str)
    
    return {
        "query": query,
        "answer": answer,
        "retrieved_candidates": retrieved_info
    }
