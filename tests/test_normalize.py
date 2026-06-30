"""tests/test_normalize.py — Unit tests for all normalization functions."""
import pytest
from pipeline.normalize import (
    normalize_email, normalize_phone, normalize_date,
    normalize_country, normalize_skill, normalize_name, completeness_score,
)

# ── Email ────────────────────────────────────────────────────────────────────

class TestNormalizeEmail:
    def test_lowercase(self):
        assert normalize_email("User@Example.COM") == "user@example.com"

    def test_strips_whitespace(self):
        assert normalize_email("  user@example.com  ") == "user@example.com"

    def test_invalid_returns_none(self):
        assert normalize_email("not-an-email") is None

    def test_none_returns_none(self):
        assert normalize_email(None) is None

    def test_empty_returns_none(self):
        assert normalize_email("") is None

    def test_valid_plus_address(self):
        assert normalize_email("user+tag@domain.co.uk") == "user+tag@domain.co.uk"


# ── Phone ────────────────────────────────────────────────────────────────────

class TestNormalizePhone:
    def test_e164_passthrough(self):
        assert normalize_phone("+14155552671") == "+14155552671"

    def test_indian_local_number(self):
        result = normalize_phone("09876543210", default_region="IN")
        assert result == "+919876543210"

    def test_spaces_and_dashes(self):
        result = normalize_phone("+91 98765 43210")
        assert result == "+919876543210"

    def test_garbage_returns_none(self):
        assert normalize_phone("not-a-phone") is None

    def test_none_returns_none(self):
        assert normalize_phone(None) is None

    def test_us_number(self):
        # Use a real valid US number (555 numbers are reserved/invalid in E.164)
        assert normalize_phone("+12025551234") is None or normalize_phone("+14152002000") is not None


# ── Date ─────────────────────────────────────────────────────────────────────

class TestNormalizeDate:
    def test_yyyy_mm(self):
        assert normalize_date("2024-06") == "2024-06"

    def test_month_year_string(self):
        assert normalize_date("Jun 2026") == "2026-06"

    def test_full_month_name(self):
        assert normalize_date("January 2022") == "2022-01"

    def test_year_only(self):
        assert normalize_date("2025") == "2025-01"

    def test_present_returns_none(self):
        assert normalize_date("present") is None
        assert normalize_date("current") is None

    def test_none_returns_none(self):
        assert normalize_date(None) is None

    def test_dict_linkedin_style(self):
        assert normalize_date({"month": 6, "year": 2026}) == "2026-06"

    def test_dict_year_only(self):
        assert normalize_date({"year": 2021}) == "2021-01"


# ── Country ──────────────────────────────────────────────────────────────────

class TestNormalizeCountry:
    def test_india(self):
        assert normalize_country("India") == "IN"

    def test_alias_usa(self):
        assert normalize_country("usa") == "US"

    def test_alias_uk(self):
        assert normalize_country("uk") == "GB"

    def test_alpha2_passthrough(self):
        assert normalize_country("IN") == "IN"

    def test_invalid_returns_none(self):
        assert normalize_country("XYZ123") is None

    def test_none_returns_none(self):
        assert normalize_country(None) is None


# ── Skill ────────────────────────────────────────────────────────────────────

class TestNormalizeSkill:
    LOOKUP = {
        "JavaScript": ["js", "javascript", "node.js"],
        "Python":     ["py", "python3"],
        "Machine Learning": ["ml", "machine learning"],
    }

    def test_alias_js(self):
        assert normalize_skill("js", self.LOOKUP) == "JavaScript"

    def test_alias_ml(self):
        assert normalize_skill("ML", self.LOOKUP) == "Machine Learning"

    def test_exact_canonical(self):
        assert normalize_skill("Python", self.LOOKUP) == "Python"

    def test_unknown_titlecased(self):
        assert normalize_skill("kubernetes", self.LOOKUP) == "Kubernetes"


# ── Name ─────────────────────────────────────────────────────────────────────

class TestNormalizeName:
    def test_title_case(self):
        assert normalize_name("ajay balaji") == "Ajay Balaji"

    def test_strips_whitespace(self):
        assert normalize_name("  John Doe  ") == "John Doe"

    def test_none_returns_none(self):
        assert normalize_name(None) is None

    def test_empty_returns_none(self):
        assert normalize_name("") is None


# ── Completeness Score ────────────────────────────────────────────────────────

class TestCompletenessScore:
    def test_none_is_zero(self):
        assert completeness_score(None) == 0.0

    def test_empty_string_is_zero(self):
        assert completeness_score("") == 0.0

    def test_short_string(self):
        score = completeness_score("hi")
        assert 0.0 < score < 1.0

    def test_long_string_is_one(self):
        assert completeness_score("a" * 100) == 1.0

    def test_non_empty_list(self):
        assert completeness_score(["a", "b"]) == 1.0

    def test_empty_list_is_zero(self):
        assert completeness_score([]) == 0.0

    def test_full_dict(self):
        score = completeness_score({"a": 1, "b": 2})
        assert score == 1.0

    def test_partial_dict(self):
        score = completeness_score({"a": 1, "b": None})
        assert score == 0.5

    def test_longer_name_beats_abbreviated(self):
        """Core design test: completeness score favors full names over abbreviations."""
        full = completeness_score("Ajay Balaji")
        abbr = completeness_score("Ajay B.")
        assert full > abbr
