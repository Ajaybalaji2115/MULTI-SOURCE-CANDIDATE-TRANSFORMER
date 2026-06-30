"""
pipeline/validate.py

Comprehensive field-level and schema-level validation.

Checks performed:
  1. Required fields present (based on config)
  2. Email format validity (RFC 5322 regex)
  3. Phone format validity (E.164 regex)
  4. Country code validity (ISO 3166-1 alpha-2)
  5. Date ordering: experience start <= end
  6. Education end_year <= current year
  7. Confidence values in [0.0, 1.0]
  8. JSON Schema validation of the full output

All checks are non-crashing. Invalid values are set to null with a
provenance note. Errors are collected in a ValidationResult object.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pycountry
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate

from .schema import CANONICAL_JSON_SCHEMA, CanonicalProfile


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_EMAIL_RE   = re.compile(r"^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+$")
_E164_RE    = re.compile(r"^\+[1-9]\d{6,14}$")
_YYYYMM_RE  = re.compile(r"^\d{4}-\d{2}$")
_ISO2_RE    = re.compile(r"^[A-Z]{2}$")

_CURRENT_YEAR = datetime.now().year


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool = True
    warnings: List[str] = field(default_factory=list)
    errors:   List[str] = field(default_factory=list)

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.valid = False

    def summary(self) -> str:
        lines = []
        if self.valid:
            lines.append("✓ Validation passed")
        else:
            lines.append("✗ Validation failed")
        for e in self.errors:
            lines.append(f"  ERROR:   {e}")
        for w in self.warnings:
            lines.append(f"  WARNING: {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual field validators
# ---------------------------------------------------------------------------

def _validate_emails(profile: CanonicalProfile, result: ValidationResult):
    cleaned = []
    for email in profile.emails:
        if email and _EMAIL_RE.match(str(email)):
            cleaned.append(email)
        else:
            result.add_warning(f"Invalid email format dropped: '{email}'")
    profile.emails = cleaned


def _validate_phones(profile: CanonicalProfile, result: ValidationResult):
    cleaned = []
    for phone in profile.phones:
        if phone and _E164_RE.match(str(phone)):
            cleaned.append(phone)
        else:
            result.add_warning(f"Phone not E.164, dropped: '{phone}'")
    profile.phones = cleaned


def _validate_country(profile: CanonicalProfile, result: ValidationResult):
    country = profile.location.get("country")
    if country is not None:
        if not (_ISO2_RE.match(str(country)) and
                pycountry.countries.get(alpha_2=str(country))):
            result.add_warning(f"Invalid ISO-3166-alpha2 country: '{country}' → set to null")
            profile.location["country"] = None


def _validate_date_ordering(profile: CanonicalProfile, result: ValidationResult):
    for i, exp in enumerate(profile.experience):
        start = exp.get("start")
        end   = exp.get("end")
        if start and end and _YYYYMM_RE.match(start) and _YYYYMM_RE.match(end):
            if start > end:
                result.add_warning(
                    f"Experience[{i}]: start '{start}' > end '{end}' — end set to null"
                )
                profile.experience[i]["end"] = None


def _validate_education_years(profile: CanonicalProfile, result: ValidationResult):
    for i, edu in enumerate(profile.education):
        yr = edu.get("end_year")
        if yr is not None:
            try:
                if int(yr) > _CURRENT_YEAR:
                    result.add_warning(
                        f"Education[{i}]: end_year {yr} is in the future (allowed, kept as-is)"
                    )
            except (TypeError, ValueError):
                result.add_warning(f"Education[{i}]: non-numeric end_year '{yr}' → null")
                profile.education[i]["end_year"] = None


def _validate_confidence_ranges(profile: CanonicalProfile, result: ValidationResult):
    if not (0.0 <= profile.overall_confidence <= 1.0):
        result.add_warning(
            f"overall_confidence {profile.overall_confidence} out of range → clamped"
        )
        profile.overall_confidence = max(0.0, min(1.0, profile.overall_confidence))

    for s in profile.skills:
        c = s.get("confidence", 0)
        if not (0.0 <= c <= 1.0):
            s["confidence"] = max(0.0, min(1.0, c))


def _validate_required_fields(profile: CanonicalProfile, result: ValidationResult):
    if not profile.candidate_id:
        result.add_error("candidate_id is empty — ID generation failed")
    if not profile.full_name and not profile.emails:
        result.add_warning("Neither full_name nor emails present — profile may be unusable")


def _validate_json_schema(data: dict, result: ValidationResult):
    try:
        jsonschema_validate(instance=data, schema=CANONICAL_JSON_SCHEMA)
    except JsonSchemaValidationError as e:
        result.add_error(f"JSON schema validation failed: {e.message}")


# ---------------------------------------------------------------------------
# Main validate function
# ---------------------------------------------------------------------------

def validate_profile(profile: CanonicalProfile) -> ValidationResult:
    """
    Run all field-level validations on *profile* (mutates profile in place
    for fixable issues).

    Returns a ValidationResult with any warnings or errors.
    """
    result = ValidationResult()

    _validate_required_fields(profile, result)
    _validate_emails(profile, result)
    _validate_phones(profile, result)
    _validate_country(profile, result)
    _validate_date_ordering(profile, result)
    _validate_education_years(profile, result)
    _validate_confidence_ranges(profile, result)
    _validate_json_schema(profile.to_dict(), result)

    return result


def validate_output(output: dict, config: dict) -> ValidationResult:
    """
    Validate a projected output dict against the config's required fields.
    """
    result = ValidationResult()
    on_missing = config.get("on_missing", "null")

    for field_def in config.get("fields", []):
        path     = field_def.get("path")
        required = field_def.get("required", False)
        if required and path:
            val = output.get(path)
            if val is None:
                msg = f"Required output field '{path}' is null or missing"
                if on_missing == "error":
                    result.add_error(msg)
                else:
                    result.add_warning(msg)

    return result
