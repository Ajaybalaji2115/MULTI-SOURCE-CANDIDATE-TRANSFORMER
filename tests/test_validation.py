"""tests/test_validation.py — Unit tests for the validation layer."""
import pytest
from pipeline.schema import CanonicalProfile
from pipeline.validate import validate_profile, validate_output, ValidationResult


def make_profile(**overrides) -> CanonicalProfile:
    p = CanonicalProfile()
    p.candidate_id    = "abc123"
    p.full_name       = "Ajay Balaji"
    p.emails          = ["ajay@gmail.com"]
    p.phones          = ["+919876543210"]
    p.location        = {"city": "Chennai", "region": "TN", "country": "IN"}
    p.links           = {"linkedin": None, "github": None, "portfolio": None}
    p.headline        = "Software Engineer"
    p.years_experience= 2.0
    p.skills          = []
    p.experience      = [{"company": "Eightfold", "title": "Intern",
                          "start": "2026-01", "end": "2026-12", "summary": None}]
    p.education       = [{"institution": "IIT Madras", "degree": "B.Tech",
                          "field": "CS", "end_year": 2025}]
    p.provenance      = []
    p.overall_confidence = 0.85
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


# ── Email validation ──────────────────────────────────────────────────────────

class TestEmailValidation:
    def test_valid_email_kept(self):
        p = make_profile(emails=["valid@example.com"])
        validate_profile(p)
        assert "valid@example.com" in p.emails

    def test_invalid_email_dropped_with_warning(self):
        p = make_profile(emails=["not-an-email", "good@example.com"])
        result = validate_profile(p)
        assert "good@example.com" in p.emails
        assert "not-an-email" not in p.emails
        assert any("not-an-email" in w for w in result.warnings)


# ── Phone validation ──────────────────────────────────────────────────────────

class TestPhoneValidation:
    def test_e164_phone_kept(self):
        p = make_profile(phones=["+919876543210"])
        validate_profile(p)
        assert "+919876543210" in p.phones

    def test_non_e164_dropped_with_warning(self):
        p = make_profile(phones=["not-a-phone", "+919876543210"])
        result = validate_profile(p)
        assert "+919876543210" in p.phones
        assert "not-a-phone" not in p.phones
        assert any("not-a-phone" in w for w in result.warnings)


# ── Country validation ────────────────────────────────────────────────────────

class TestCountryValidation:
    def test_valid_iso2_kept(self):
        p = make_profile(location={"city": "Chennai", "region": None, "country": "IN"})
        validate_profile(p)
        assert p.location["country"] == "IN"

    def test_invalid_country_nulled(self):
        p = make_profile(location={"city": "X", "region": None, "country": "XX"})
        result = validate_profile(p)
        assert p.location["country"] is None
        assert any("XX" in w for w in result.warnings)


# ── Date ordering ─────────────────────────────────────────────────────────────

class TestDateOrdering:
    def test_valid_order_unchanged(self):
        exp = [{"company": "A", "title": "Dev", "start": "2020-01", "end": "2022-06", "summary": None}]
        p = make_profile(experience=exp)
        validate_profile(p)
        assert p.experience[0]["end"] == "2022-06"

    def test_start_after_end_nulls_end(self):
        exp = [{"company": "A", "title": "Dev", "start": "2023-01", "end": "2020-06", "summary": None}]
        p = make_profile(experience=exp)
        result = validate_profile(p)
        assert p.experience[0]["end"] is None
        assert any("start" in w and "end" in w for w in result.warnings)


# ── Education year ────────────────────────────────────────────────────────────

class TestEducationYear:
    def test_non_numeric_year_nulled(self):
        edu = [{"institution": "MIT", "degree": "BS", "field": "CS", "end_year": "abc"}]
        p = make_profile(education=edu)
        result = validate_profile(p)
        assert p.education[0]["end_year"] is None


# ── Confidence range ──────────────────────────────────────────────────────────

class TestConfidenceRange:
    def test_over_one_clamped(self):
        p = make_profile(overall_confidence=1.5)
        result = validate_profile(p)
        assert p.overall_confidence == 1.0
        assert any("clamped" in w for w in result.warnings)

    def test_under_zero_clamped(self):
        p = make_profile(overall_confidence=-0.1)
        result = validate_profile(p)
        assert p.overall_confidence == 0.0


# ── Required fields ───────────────────────────────────────────────────────────

class TestRequiredFields:
    def test_empty_candidate_id_is_error(self):
        p = make_profile(candidate_id="")
        result = validate_profile(p)
        assert not result.valid
        assert any("candidate_id" in e for e in result.errors)


# ── Output validation ─────────────────────────────────────────────────────────

class TestOutputValidation:
    def test_required_field_present_passes(self):
        output = {"full_name": "Alice", "primary_email": "a@x.com"}
        config = {
            "fields": [{"path": "full_name", "required": True},
                       {"path": "primary_email", "required": True}],
            "on_missing": "null",
        }
        result = validate_output(output, config)
        assert result.valid

    def test_required_field_null_gives_warning(self):
        output = {"full_name": None}
        config = {
            "fields": [{"path": "full_name", "required": True}],
            "on_missing": "null",
        }
        result = validate_output(output, config)
        assert any("full_name" in w for w in result.warnings)

    def test_required_field_null_with_error_mode_fails(self):
        output = {"full_name": None}
        config = {
            "fields": [{"path": "full_name", "required": True}],
            "on_missing": "error",
        }
        result = validate_output(output, config)
        assert not result.valid
        assert any("full_name" in e for e in result.errors)
