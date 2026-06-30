"""tests/test_extractors.py — Unit tests for all extractors against sample files."""
import os
import json
import pytest

DATA_DIR    = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "..", "configs")


def weights():
    path = os.path.join(CONFIGS_DIR, "confidence_weights.json")
    with open(path) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


# ── CSV Extractor ────────────────────────────────────────────────────────────

class TestCSVExtractor:
    def setup_method(self):
        from pipeline.extractors.csv_extractor import CSVExtractor
        self.extractor = CSVExtractor(confidence_weights=weights())
        self.source    = os.path.join(DATA_DIR, "sample_recruiter.csv")

    def test_returns_list(self):
        fields = self.extractor.extract(self.source)
        assert isinstance(fields, list)
        assert len(fields) > 0

    def test_extracts_full_name(self):
        fields = self.extractor.extract(self.source)
        names = [f for f in fields if f.canonical_name == "full_name"]
        assert len(names) > 0

    def test_extracts_email(self):
        fields = self.extractor.extract(self.source)
        emails = [f for f in fields if f.canonical_name == "emails"]
        assert any("@" in str(e.value) for e in emails)

    def test_email_is_lowercase(self):
        fields = self.extractor.extract(self.source)
        emails = [f for f in fields if f.canonical_name == "emails"]
        for e in emails:
            assert e.value == e.value.lower()

    def test_phone_is_e164(self):
        fields = self.extractor.extract(self.source)
        phones = [f for f in fields if f.canonical_name == "phones"]
        for p in phones:
            assert p.value.startswith("+"), f"Phone not E.164: {p.value}"

    def test_missing_file_returns_empty(self):
        fields = self.extractor.extract("nonexistent_file.csv")
        assert fields == []

    def test_confidence_in_range(self):
        fields = self.extractor.extract(self.source)
        for f in fields:
            assert 0.0 <= f.confidence <= 1.0


# ── ATS JSON Extractor ───────────────────────────────────────────────────────

class TestATSJsonExtractor:
    def setup_method(self):
        from pipeline.extractors.json_extractor import ATSJsonExtractor
        self.extractor = ATSJsonExtractor(confidence_weights=weights())
        self.source    = os.path.join(DATA_DIR, "sample_ats.json")

    def test_returns_list(self):
        fields = self.extractor.extract(self.source)
        assert isinstance(fields, list)
        assert len(fields) > 0

    def test_maps_applicant_name(self):
        fields = self.extractor.extract(self.source)
        names = [f for f in fields if f.canonical_name == "full_name"]
        assert len(names) > 0
        assert any("Ajay" in str(n.value) for n in names)

    def test_maps_contact_email(self):
        fields = self.extractor.extract(self.source)
        emails = [f for f in fields if f.canonical_name == "emails"]
        assert len(emails) > 0

    def test_maps_skill_tags(self):
        fields = self.extractor.extract(self.source)
        skills = [f for f in fields if f.canonical_name == "skills"]
        assert len(skills) > 0

    def test_maps_work_history(self):
        fields = self.extractor.extract(self.source)
        exp = [f for f in fields if f.canonical_name == "experience"]
        assert len(exp) > 0
        for e in exp:
            assert isinstance(e.value, list)

    def test_maps_academic_history(self):
        fields = self.extractor.extract(self.source)
        edu = [f for f in fields if f.canonical_name == "education"]
        assert len(edu) > 0

    def test_missing_file_returns_empty(self):
        fields = self.extractor.extract("nonexistent.json")
        assert fields == []


# ── Text Extractor ───────────────────────────────────────────────────────────

class TestTextExtractor:
    def setup_method(self):
        from pipeline.extractors.text_extractor import TextExtractor
        self.extractor = TextExtractor(confidence_weights=weights())
        self.source    = os.path.join(DATA_DIR, "sample_resume.txt")

    def test_returns_list(self):
        fields = self.extractor.extract(self.source)
        assert isinstance(fields, list)
        assert len(fields) > 0

    def test_extracts_email(self):
        fields = self.extractor.extract(self.source)
        emails = [f for f in fields if f.canonical_name == "emails"]
        assert len(emails) > 0

    def test_extracts_github_link(self):
        fields = self.extractor.extract(self.source)
        github = [f for f in fields if f.canonical_name == "links.github"]
        assert len(github) > 0

    def test_extracts_skills_section(self):
        fields = self.extractor.extract(self.source)
        skills = [f for f in fields if f.canonical_name == "skills"]
        assert len(skills) > 0
        skill_items = skills[0].value
        assert isinstance(skill_items, list)
        assert len(skill_items) > 0

    def test_extracts_experience_section(self):
        fields = self.extractor.extract(self.source)
        exp = [f for f in fields if f.canonical_name == "experience"]
        assert len(exp) > 0

    def test_extracts_education_section(self):
        fields = self.extractor.extract(self.source)
        edu = [f for f in fields if f.canonical_name == "education"]
        assert len(edu) > 0

    def test_missing_file_returns_empty(self):
        fields = self.extractor.extract("nonexistent.txt")
        assert fields == []


# ── LinkedIn Extractor ───────────────────────────────────────────────────────

class TestLinkedInExtractor:
    def setup_method(self):
        from pipeline.extractors.linkedin_extractor import LinkedInExtractor
        self.extractor = LinkedInExtractor(confidence_weights=weights())
        self.source    = os.path.join(DATA_DIR, "sample_linkedin_export.json")

    def test_returns_list(self):
        fields = self.extractor.extract(self.source)
        assert isinstance(fields, list)
        assert len(fields) > 0

    def test_extracts_full_name(self):
        fields = self.extractor.extract(self.source)
        names = [f for f in fields if f.canonical_name == "full_name"]
        assert len(names) > 0
        assert "Ajay Balaji" in [n.value for n in names]

    def test_extracts_email(self):
        fields = self.extractor.extract(self.source)
        emails = [f for f in fields if f.canonical_name == "emails"]
        assert len(emails) > 0

    def test_extracts_positions(self):
        fields = self.extractor.extract(self.source)
        exp = [f for f in fields if f.canonical_name == "experience"]
        assert len(exp) > 0

    def test_extracts_education(self):
        fields = self.extractor.extract(self.source)
        edu = [f for f in fields if f.canonical_name == "education"]
        assert len(edu) > 0

    def test_missing_file_returns_empty(self):
        fields = self.extractor.extract("nonexistent.json")
        assert fields == []
