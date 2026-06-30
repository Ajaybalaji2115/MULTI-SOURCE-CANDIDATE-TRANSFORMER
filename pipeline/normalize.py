"""
pipeline/normalize.py

All normalization functions used across the pipeline.

Functions:
    normalize_email(v)            → lowercase, stripped string or None
    normalize_phone(v, region)    → E.164 string or None
    normalize_date(v)             → "YYYY-MM" string or None
    normalize_country(v)          → ISO 3166-1 alpha-2 string or None
    normalize_skill(v, lookup)    → canonical skill name string or original
    normalize_name(v)             → title-cased stripped string or None
    completeness_score(v)         → float 0-1 measuring value richness
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional

import phonenumbers
import pycountry
from dateutil import parser as dateutil_parser


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+$")


def normalize_email(value: Any) -> Optional[str]:
    """Return lowercase email if valid, else None."""
    if not value:
        return None
    v = str(value).strip().lower()
    if _EMAIL_RE.match(v):
        return v
    return None


# ---------------------------------------------------------------------------
# Phone → E.164
# ---------------------------------------------------------------------------

def normalize_phone(value: Any, default_region: str = "IN") -> Optional[str]:
    """
    Parse *value* into E.164 format (e.g., +14155552671).

    Tries the given *default_region* as a hint for local numbers.
    Returns None if parsing fails.
    """
    if not value:
        return None
    raw = str(value).strip()
    # Remove common separators that confuse the parser
    cleaned = re.sub(r"[\s\-\(\)\.]{1,}", "", raw)
    for attempt in (raw, cleaned):
        try:
            parsed = phonenumbers.parse(attempt, default_region)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
        except phonenumbers.NumberParseException:
            continue
    return None


# ---------------------------------------------------------------------------
# Date → YYYY-MM
# ---------------------------------------------------------------------------

_YEAR_ONLY_RE = re.compile(r"^\d{4}$")


def normalize_date(value: Any) -> Optional[str]:
    """
    Parse a date string in any common format and return "YYYY-MM".
    Returns None if the value cannot be parsed.
    Handles:
        "Jun 2026", "2026-06", "06/2026", "June 2026", "2026", dict {month, year}
    """
    if value is None:
        return None

    # LinkedIn-style dict: {"month": 6, "year": 2026}
    if isinstance(value, dict):
        year = value.get("year")
        month = value.get("month", 1)
        if year:
            return f"{int(year):04d}-{int(month):02d}"
        return None

    raw = str(value).strip()

    # Year only → treat as January of that year
    if _YEAR_ONLY_RE.match(raw):
        return f"{raw}-01"

    # "present" / "current" → None (open-ended)
    if raw.lower() in ("present", "current", "now", "ongoing", "till date", ""):
        return None

    try:
        dt = dateutil_parser.parse(raw, default=dateutil_parser.parse("2000-01-01"))
        return dt.strftime("%Y-%m")
    except (ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Country → ISO 3166-1 alpha-2
# ---------------------------------------------------------------------------

# Common aliases not covered by pycountry
_COUNTRY_ALIASES: Dict[str, str] = {
    "usa":          "US",
    "united states":"US",
    "u.s.a":       "US",
    "uk":           "GB",
    "united kingdom": "GB",
    "india":        "IN",
    "uae":          "AE",
    "russia":       "RU",
}


def normalize_country(value: Any) -> Optional[str]:
    """Return ISO 3166-1 alpha-2 country code, or None."""
    if not value:
        return None
    raw = str(value).strip()
    lower = raw.lower()

    # Direct alias check
    if lower in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[lower]

    # Already a 2-letter code?
    if len(raw) == 2 and raw.upper().isalpha():
        try:
            pycountry.countries.get(alpha_2=raw.upper())
            return raw.upper()
        except Exception:
            pass

    # Try pycountry by name or alpha-2
    try:
        result = pycountry.countries.search_fuzzy(raw)
        if result:
            return result[0].alpha_2
    except LookupError:
        pass

    return None


# ---------------------------------------------------------------------------
# Skill → canonical name
# ---------------------------------------------------------------------------

def normalize_skill(value: Any, lookup: Dict[str, list]) -> str:
    """
    Map *value* to a canonical skill name using a reverse lookup table.

    *lookup* maps canonical_name → [alias1, alias2, ...].
    Returns the canonical name if found, else the original value title-cased.
    """
    if not value:
        return str(value)
    raw = str(value).strip()
    lower = raw.lower()

    for canonical, aliases in lookup.items():
        if lower == canonical.lower() or lower in [a.lower() for a in aliases]:
            return canonical

    return raw.title()


# ---------------------------------------------------------------------------
# Name
# ---------------------------------------------------------------------------

def normalize_name(value: Any) -> Optional[str]:
    """Strip, unicode-normalize, and title-case a person name."""
    if not value:
        return None
    normalized = unicodedata.normalize("NFC", str(value).strip())
    return normalized.title()


# ---------------------------------------------------------------------------
# Completeness Score
# ---------------------------------------------------------------------------

def completeness_score(value: Any) -> float:
    """
    Return a float in [0, 1] representing how 'complete' a value is.

    Rules:
    - None / empty string / empty list → 0.0
    - String: length capped at 100 chars → score ∝ length
    - List: non-empty → 1.0
    - Dict: proportion of non-None values
    - Number: 1.0 if non-zero, 0.5 if zero
    """
    if value is None:
        return 0.0
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0.0
        return min(1.0, len(stripped) / 100.0)
    if isinstance(value, list):
        return 1.0 if len(value) > 0 else 0.0
    if isinstance(value, dict):
        non_none = sum(1 for v in value.values() if v is not None)
        total = len(value)
        return non_none / total if total > 0 else 0.0
    if isinstance(value, (int, float)):
        return 1.0 if value != 0 else 0.5
    return 1.0
