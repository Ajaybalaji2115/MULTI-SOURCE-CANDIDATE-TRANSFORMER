"""tests/test_projection.py — Unit tests for the projection layer."""
import pytest
from pipeline.schema import CanonicalProfile
from pipeline.project import project, _resolve_path


# ── Path resolver ─────────────────────────────────────────────────────────────

class TestResolvePath:
    def test_simple_key(self):
        assert _resolve_path({"name": "Alice"}, "name") == "Alice"

    def test_nested_key(self):
        record = {"location": {"city": "Chennai", "country": "IN"}}
        assert _resolve_path(record, "location.city") == "Chennai"

    def test_array_index(self):
        assert _resolve_path({"emails": ["a@x.com", "b@x.com"]}, "emails[0]") == "a@x.com"

    def test_array_index_out_of_bounds(self):
        assert _resolve_path({"emails": []}, "emails[0]") is None

    def test_array_glob(self):
        record = {"skills": [{"name": "Python"}, {"name": "Docker"}]}
        result = _resolve_path(record, "skills[].name")
        assert result == ["Python", "Docker"]

    def test_missing_key_returns_none(self):
        assert _resolve_path({}, "full_name") is None

    def test_nested_missing_key(self):
        assert _resolve_path({"location": {}}, "location.city") is None


# ── Full projection ────────────────────────────────────────────────────────────

def make_profile(**kwargs) -> CanonicalProfile:
    defaults = {
        "candidate_id":    "abc123",
        "full_name":       "Ajay Balaji",
        "emails":          ["ajay@gmail.com"],
        "phones":          ["+919876543210"],
        "location":        {"city": "Chennai", "region": "TN", "country": "IN"},
        "links":           {"linkedin": None, "github": "https://github.com/ajay", "portfolio": None},
        "headline":        "Software Engineer",
        "years_experience": 2.0,
        "skills":          [{"name": "Python", "confidence": 0.9, "sources": ["csv:a"]},
                            {"name": "Docker", "confidence": 0.75, "sources": ["github:b"]}],
        "experience":      [{"company": "Eightfold AI", "title": "Intern",
                             "start": "2026-06", "end": "2026-12", "summary": None}],
        "education":       [{"institution": "IIT Madras", "degree": "B.Tech",
                             "field": "CS", "end_year": 2025}],
        "provenance":      [],
        "overall_confidence": 0.82,
    }
    defaults.update(kwargs)
    p = CanonicalProfile()
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


class TestProjection:
    def test_full_schema_no_fields_config(self):
        """When no fields list, full canonical record is returned."""
        profile = make_profile()
        config  = {"on_missing": "null", "include_confidence": False}
        output  = project(profile, config)
        assert "full_name" in output
        assert output["full_name"] == "Ajay Balaji"

    def test_selected_fields_only(self):
        profile = make_profile()
        config = {
            "fields": [
                {"path": "full_name", "type": "string", "required": True},
                {"path": "primary_email", "from": "emails[0]", "type": "string"},
            ],
            "on_missing": "null",
        }
        output = project(profile, config)
        assert "full_name" in output
        assert "primary_email" in output
        assert "phones" not in output       # not in config

    def test_renamed_field(self):
        profile = make_profile()
        config = {
            "fields": [{"path": "company", "from": "experience[0].company", "type": "string"}],
            "on_missing": "null",
        }
        output = project(profile, config)
        assert output["company"] == "Eightfold AI"

    def test_skill_name_glob(self):
        profile = make_profile()
        config = {
            "fields": [{"path": "skills", "from": "skills[].name", "type": "string[]"}],
            "on_missing": "null",
        }
        output = project(profile, config)
        assert isinstance(output["skills"], list)
        assert "Python" in output["skills"]

    def test_on_missing_null(self):
        profile = make_profile(headline=None)
        config = {
            "fields": [{"path": "headline", "required": False}],
            "on_missing": "null",
        }
        output = project(profile, config)
        assert "headline" in output
        assert output["headline"] is None

    def test_on_missing_omit(self):
        profile = make_profile(headline=None)
        config = {
            "fields": [{"path": "headline", "required": False}],
            "on_missing": "omit",
        }
        output = project(profile, config)
        assert "headline" not in output

    def test_on_missing_error_raises(self):
        profile = make_profile(emails=[])
        config = {
            "fields": [{"path": "email", "from": "emails[0]", "required": True}],
            "on_missing": "error",
        }
        with pytest.raises(ValueError, match="Required field"):
            project(profile, config)

    def test_include_confidence_flag(self):
        profile = make_profile()
        config  = {"fields": [], "include_confidence": True, "on_missing": "null"}
        output  = project(profile, config)
        assert "overall_confidence" in output
        assert output["overall_confidence"] == 0.82

    def test_normalize_e164_at_projection(self):
        """Projection-time E164 normalization should work on string values."""
        profile = make_profile(phones=["+919876543210"])
        config = {
            "fields": [{"path": "phone", "from": "phones[0]", "normalize": "E164"}],
            "on_missing": "null",
        }
        output = project(profile, config)
        assert output["phone"] == "+919876543210"
