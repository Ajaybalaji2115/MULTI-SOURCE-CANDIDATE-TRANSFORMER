"""
pipeline/rag/models.py

Manages connection to the Google Gemini API for:
  1. Generating text embeddings (using models/text-embedding-004)
  2. Generating answers from context (using models/gemini-1.5-flash)

Provides graceful fallbacks if the Gemini API Key is missing or invalid.
"""
import os
import logging
import hashlib
from typing import List, Optional

logger = logging.getLogger(__name__)

# Try importing the google-generativeai SDK
try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False
    logger.warning("google-generativeai is not installed. RAG will run in local mock/fallback mode.")

def get_api_key() -> Optional[str]:
    """Retrieve Gemini API key from environment variables."""
    return os.environ.get("GEMINI_API_KEY")

def init_gemini():
    """Initialize the Google Generative AI client if possible."""
    if not _GENAI_AVAILABLE:
        return False
    
    api_key = get_api_key()
    if not api_key:
        return False
    
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        logger.error(f"Error configuring Gemini API: {e}")
        return False

def get_embedding(text: str, model: str = "models/text-embedding-004") -> List[float]:
    """
    Generate a vector embedding for the given text.
    Falls back to a deterministic pseudo-random embedding if Gemini is unavailable.
    """
    if init_gemini():
        try:
            response = genai.embed_content(
                model=model,
                content=text,
                task_type="retrieval_document"
            )
            if "embedding" in response:
                return response["embedding"]
            # Sometimes SDK returns a dictionary/list structure directly or inside an object
            elif hasattr(response, "embedding"):
                return response.embedding
            elif isinstance(response, dict) and "embedding" in response:
                return response["embedding"]
        except Exception as e:
            logger.warning(f"Gemini embedding API call failed: {e}. Falling back to mock embedding.")
    
    # Deterministic mock embedding fallback (length 768)
    return _generate_mock_embedding(text)

def generate_answer(query: str, context: str, model_name: str = "gemini-1.5-flash") -> str:
    """
    Generate an answer to the query using the provided context.
    Falls back to a keyword-based rule search answer if Gemini is unavailable.
    """
    if init_gemini():
        try:
            model = genai.GenerativeModel(model_name)
            prompt = (
                "You are an expert AI recruiting assistant for a candidate database.\n"
                "Use the following retrieved candidate context to answer the user's question.\n"
                "Be detailed, professional, and draw evidence ONLY from the provided context.\n"
                "If the context does not contain enough information to answer, state that clearly.\n\n"
                f"--- Candidate Context ---\n{context}\n\n"
                f"--- User Question ---\n{query}\n\n"
                "Answer:"
            )
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.warning(f"Gemini generation API call failed: {e}. Falling back to mock generator.")

    return _generate_mock_answer(query, context)

def _generate_mock_embedding(text: str, dimension: int = 768) -> List[float]:
    """
    Generates a deterministic vector of floats in [-1.0, 1.0] based on the input text hash,
    which allows testing search logic without API calls.
    """
    # Use MD5 hashes to construct deterministic float values
    hash_object = hashlib.md5(text.encode("utf-8"))
    hex_dig = hash_object.hexdigest()
    
    vector = []
    for i in range(dimension):
        # Generate stable mock floats
        val = int(hex_dig[i % len(hex_dig)], 16) / 15.0  # value in [0, 1]
        # Alternate signs
        if i % 2 == 0:
            val = -val
        vector.append(val)
        
        # Shift hash for diversity
        if i % len(hex_dig) == 0 and i > 0:
            hash_object = hashlib.md5((hex_dig + str(i)).encode("utf-8"))
            hex_dig = hash_object.hexdigest()
            
    # L2 normalize the mock vector
    norm = sum(x**2 for x in vector) ** 0.5
    if norm > 0:
        vector = [x / norm for x in vector]
    return vector

def _generate_mock_answer(query: str, context: str) -> str:
    """
    A simple keyword-based response generator when Gemini API is not available.
    """
    lines = [
        "WARNING: [MOCK RAG MODE - GEMINI_API_KEY NOT SET OR SDK MISSING]",
        "This response is generated locally without an LLM. To use real RAG, please set the GEMINI_API_KEY environment variable.",
        "",
        "Based on the retrieved candidates matching your query:",
    ]
    
    # Attempt to extract candidate names and summaries from context
    candidates = []
    current_candidate = None
    for line in context.splitlines():
        if line.startswith("Candidate Name:"):
            if current_candidate:
                candidates.append(current_candidate)
            current_candidate = {"name": line.split(":", 1)[1].strip(), "skills": [], "exp": []}
        elif current_candidate and line.startswith("Skills:"):
            current_candidate["skills"] = [s.strip() for s in line.split(":", 1)[1].split(",")]
        elif current_candidate and line.startswith("- "):
            current_candidate["exp"].append(line.replace("-", "").strip())
            
    if current_candidate:
        candidates.append(current_candidate)
        
    if not candidates:
        lines.append("No candidates retrieved in the context.")
        return "\n".join(lines)
        
    for cand in candidates:
        name = cand["name"]
        skills_str = ", ".join(cand["skills"][:5])
        exp_str = "; ".join(cand["exp"][:2])
        lines.append(f"- Candidate: {name}")
        if skills_str:
            lines.append(f"  Skills: {skills_str}")
        if exp_str:
            lines.append(f"  Experience highlights: {exp_str}")
            
    lines.append("")
    lines.append(f"Query was: '{query}'")
    return "\n".join(lines)
