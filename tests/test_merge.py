"""tests/test_merge.py — Unit tests for the merge engine."""
import pytest
from pipeline.merge import merge, generate_candidate_id, _resolve_scalar
from pipeline.schema import RawField


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_rf(name, value, source_type="csv", confidence=0.9, raw=None):
    return RawField(
        canonical_name=name,
        value=value,
        source=f"{source_type}:test.csv",
        method="test",
        raw_value=raw or value,
        confidence=confidence,
    )


# ── Completeness-first resolution ────────────────────────────────────────────

class TestScalarResolution:
    def test_prefers_more_complete_name(self):
        """Structured abbreviated name should LOSE to a more complete unstructured name."""
        csv_field    = make_rf("full_name", "Ajay B.",   source_type="csv",    confidence=0.9)
        resume_field = make_rf("full_name", "Ajay Balaji", source_type="resume", confidence=0.65)
        winner = _resolve_scalar([csv_field, resume_field])
        assert winner.value == "Ajay Balaji"

    def test_prefers_higher_confidence_when_completeness_equal(self):
        f1 = make_rf("full_name", "John Doe", source_type="resume", confidence=0.6)
        f2 = make_rf("full_name", "John Doe", source_type="csv",    confidence=0.9)
        winner = _resolve_scalar([f1, f2])
        assert winner.confidence == 0.9

    def test_single_candidate_wins(self):
        f = make_rf("full_name", "Alice Smith")
        winner = _resolve_scalar([f])
        assert winner.value == "Alice Smith"


# ── Array field merging ───────────────────────────────────────────────────────

class TestArrayMerge:
    def test_emails_deduped(self):
        fields = [
            make_rf("emails", "user@example.com", "csv"),
            make_rf("emails", "USER@EXAMPLE.COM", "ats_json"),
            make_rf("emails", "other@example.com", "resume"),
        ]
        profile = merge(fields)
        # Both distinct emails present, duplicate removed
        assert len(profile.emails) == 2
        assert "user@example.com" in profile.emails or "user@example.com" in [e.lower() for e in profile.emails]

    def test_phones_union(self):
        fields = [
            make_rf("phones", "+919876543210", "csv"),
            make_rf("phones", "+15551234567",  "ats_json"),
        ]
        profile = merge(fields)
        assert len(profile.phones) == 2


# ── Skills deduplication ──────────────────────────────────────────────────────

class TestSkillsMerge:
    def test_duplicate_skills_merged(self):
        skills_a = [{"name": "Python", "confidence": 0.9, "sources": ["csv:a"]}]
        skills_b = [{"name": "Python", "confidence": 0.7, "sources": ["github:b"]}]
        fields = [
            make_rf("skills", skills_a, "csv"),
            make_rf("skills", skills_b, "github"),
        ]
        profile = merge(fields)
        python_skills = [s for s in profile.skills if s["name"] == "Python"]
        assert len(python_skills) == 1
        assert "csv:a" in python_skills[0]["sources"] or "github:b" in python_skills[0]["sources"]

    def test_multiple_skills_union(self):
        skills_a = [
            {"name": "Python",     "confidence": 0.9, "sources": ["csv:a"]},
            {"name": "JavaScript", "confidence": 0.8, "sources": ["csv:a"]},
        ]
        skills_b = [
            {"name": "Docker",     "confidence": 0.7, "sources": ["github:b"]},
        ]
        fields = [
            make_rf("skills", skills_a, "csv"),
            make_rf("skills", skills_b, "github"),
        ]
        profile = merge(fields)
        names = [s["name"] for s in profile.skills]
        assert "Python" in names
        assert "JavaScript" in names
        assert "Docker" in names


# ── Experience deduplication ──────────────────────────────────────────────────

class TestExperienceMerge:
    def test_duplicate_experience_deduped(self):
        exp = [{"company": "Google", "title": "Engineer", "start": "2020-01", "end": None, "summary": None}]
        fields = [
            make_rf("experience", exp, "csv"),
            make_rf("experience", exp, "resume"),
        ]
        profile = merge(fields)
        google_jobs = [e for e in profile.experience if e["company"] == "Google"]
        assert len(google_jobs) == 1


# ── Candidate ID generation ───────────────────────────────────────────────────

class TestCandidateId:
    def test_email_based_id_deterministic(self):
        prov = []
        id1 = generate_candidate_id(["user@example.com"], "Alice", [], {}, prov)
        id2 = generate_candidate_id(["user@example.com"], "Alice", [], {}, prov)
        assert id1 == id2
        assert len(id1) == 64  # SHA256 hex

    def test_name_phone_fallback(self):
        prov = []
        id1 = generate_candidate_id([], "Alice Smith", ["+14155552671"], {}, prov)
        assert len(id1) == 64

    def test_uuid_fallback_flagged(self):
        prov = []
        id1 = generate_candidate_id([], None, [], {}, prov)
        # UUID4 fallback — should be flagged in provenance
        flagged = any(p.get("method") == "uuid4_fallback" for p in prov)
        assert flagged

    def test_different_emails_different_ids(self):
        prov = []
        id1 = generate_candidate_id(["alice@x.com"], "Alice", [], {}, prov)
        id2 = generate_candidate_id(["bob@x.com"],   "Bob",   [], {}, prov)
        assert id1 != id2


# ── Overall confidence ────────────────────────────────────────────────────────

class TestOverallConfidence:
    def test_confidence_in_range(self):
        fields = [
            make_rf("full_name", "Alice Smith", "csv", confidence=0.9),
            make_rf("emails",    "alice@x.com", "csv", confidence=0.9),
        ]
        profile = merge(fields)
        assert 0.0 <= profile.overall_confidence <= 1.0

    def test_single_source_confidence(self):
        fields = [make_rf("full_name", "Alice Smith", "csv", confidence=0.9)]
        profile = merge(fields)
        assert profile.overall_confidence > 0.0


# ── Provenance tracking ───────────────────────────────────────────────────────

class TestProvenance:
    def test_all_sources_recorded(self):
        fields = [
            make_rf("full_name", "Ajay B.",    "csv",    confidence=0.9),
            make_rf("full_name", "Ajay Balaji","resume", confidence=0.65),
        ]
        profile = merge(fields)
        sources_in_provenance = [p["source"] for p in profile.provenance]
        assert any("csv" in s for s in sources_in_provenance)
        assert any("resume" in s for s in sources_in_provenance)
