"""
tests/test_rag.py - Unit tests for RAG pipeline components
"""
import os
import json
import tempfile
import pytest

from pipeline.rag.document_formatter import format_candidate_for_rag
from pipeline.rag.models import _generate_mock_embedding, _generate_mock_answer, get_embedding, generate_answer
from pipeline.rag.vector_store import VectorStore
from pipeline.rag import query_rag


@pytest.fixture
def sample_profiles():
    return [
        {
            "candidate_id": "cand_01",
            "full_name": "Alice Smith",
            "emails": ["alice@example.com"],
            "phones": ["+14155550001"],
            "location": {"city": "San Francisco", "region": "CA", "country": "US"},
            "headline": "Senior Software Engineer",
            "years_experience": 8,
            "skills": [
                {"name": "Python", "confidence": 0.95, "sources": ["resume"]},
                {"name": "Go", "confidence": 0.80, "sources": ["github"]}
            ],
            "experience": [
                {
                    "company": "Google",
                    "title": "Staff Engineer",
                    "start": "2020-01",
                    "end": "present",
                    "summary": "Led team of 5 backend developers.\nArchitected cloud service."
                }
            ],
            "education": [
                {
                    "institution": "Stanford University",
                    "degree": "MS",
                    "field": "Computer Science",
                    "end_year": 2018
                }
            ],
            "overall_confidence": 0.90
        },
        {
            "candidate_id": "cand_02",
            "full_name": "Bob Jones",
            "emails": ["bob@example.com"],
            "phones": ["+919876543210"],
            "location": {"city": "Bengaluru", "region": "Karnataka", "country": "IN"},
            "headline": "Machine Learning Engineer",
            "years_experience": 4,
            "skills": [
                {"name": "Python", "confidence": 0.90, "sources": ["resume"]},
                {"name": "PyTorch", "confidence": 0.95, "sources": ["resume"]}
            ],
            "experience": [
                {
                    "company": "Flipkart",
                    "title": "ML Engineer",
                    "start": "2022-06",
                    "end": "present",
                    "summary": "Built recommendation pipelines."
                }
            ],
            "education": [
                {
                    "institution": "IIT Madras",
                    "degree": "B.Tech",
                    "field": "Electrical Engineering",
                    "end_year": 2022
                }
            ],
            "overall_confidence": 0.85
        }
    ]


def test_document_formatter(sample_profiles):
    alice = sample_profiles[0]
    formatted = format_candidate_for_rag(alice)
    
    assert "Candidate Name: Alice Smith" in formatted
    assert "Candidate ID: cand_01" in formatted
    assert "Headline: Senior Software Engineer" in formatted
    assert "Profile Confidence Score: 0.90" in formatted
    assert "Years of Experience: 8" in formatted
    assert "Emails: alice@example.com" in formatted
    assert "Phones: +14155550001" in formatted
    assert "Location: San Francisco, CA, US" in formatted
    assert "Skills: Python (conf: 0.95), Go (conf: 0.80)" in formatted
    assert "Work Experience:" in formatted
    assert "- Staff Engineer at Google (2020-01 to present)" in formatted
    assert "  Led team of 5 backend developers." in formatted
    assert "Education:" in formatted
    assert "- MS in Computer Science from Stanford University (Graduated: 2018)" in formatted


def test_mock_embedding():
    vector = _generate_mock_embedding("hello world", dimension=128)
    assert len(vector) == 128
    # L2 Norm should be approximately 1.0 (float precision)
    norm = sum(x**2 for x in vector) ** 0.5
    assert pytest.approx(norm, 1e-5) == 1.0
    
    # Check determinism
    vector2 = _generate_mock_embedding("hello world", dimension=128)
    assert vector == vector2


def test_mock_answer():
    context = "Candidate Name: Alice Smith\nSkills: Python, Go\n- Staff Engineer at Google\n"
    query = "Find python developers"
    answer = _generate_mock_answer(query, context)
    
    assert "MOCK RAG MODE" in answer
    assert "Alice Smith" in answer
    assert "Python" in answer
    assert "Staff Engineer at Google" in answer


def test_vector_store(sample_profiles):
    # Use temporary file to avoid cluttering workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "test_index.json")
        store = VectorStore(index_path=index_path)
        
        # Test index creation
        store.index_candidates(sample_profiles, rebuild=True)
        assert len(store.entries) == 2
        assert os.path.exists(index_path)
        
        # Test load
        store2 = VectorStore(index_path=index_path)
        loaded = store2.load()
        assert loaded is True
        assert len(store2.entries) == 2
        assert store2.entries[0]["candidate_id"] == "cand_01"
        assert len(store2.entries[0]["embedding"]) == 768
        
        # Test search ranking: "Google Staff Engineer" should rank Alice first
        results = store2.search("Google Staff Engineer", limit=1)
        assert len(results) == 1
        matched_cand, score = results[0]
        assert matched_cand["candidate_id"] == "cand_01"


def test_query_rag(sample_profiles):
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "test_index.json")
        store = VectorStore(index_path=index_path)
        store.index_candidates(sample_profiles, rebuild=True)
        
        res = query_rag("Find ML engineer", index_path=index_path, limit=1)
        assert res["query"] == "Find ML engineer"
        assert len(res["retrieved_candidates"]) == 1
        assert res["retrieved_candidates"][0]["candidate_id"] == "cand_02"
        assert "MOCK RAG MODE" in res["answer"]
