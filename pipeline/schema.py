"""
pipeline/schema.py

Defines:
  - RawField      : a single piece of evidence emitted by an extractor
  - CanonicalProfile : the internal unified candidate record
  - CANONICAL_JSON_SCHEMA : jsonschema definition for output validation
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional


# ---------------------------------------------------------------------------
# RawField — one piece of extracted evidence from a single source
# ---------------------------------------------------------------------------

@dataclass
class RawField:
    """
    A single piece of evidence emitted by any extractor.

    Attributes:
        canonical_name : The target field in the canonical schema (e.g. "full_name").
        value          : The extracted (and optionally pre-normalized) value.
        source         : Human-readable source label (e.g. "csv:sample_recruiter.csv").
        method         : How it was extracted (e.g. "csv_column", "regex", "api_field").
        raw_value      : The original, un-normalized value (for provenance).
        confidence     : Extraction confidence in [0.0, 1.0].
    """
    canonical_name: str
    value: Any
    source: str
    method: str
    raw_value: Any = None
    confidence: float = 0.5

    def __post_init__(self):
        if self.raw_value is None:
            self.raw_value = self.value
        self.confidence = max(0.0, min(1.0, self.confidence))


# ---------------------------------------------------------------------------
# CanonicalProfile — the unified internal record for one candidate
# ---------------------------------------------------------------------------

@dataclass
class CanonicalProfile:
    candidate_id: str = ""
    full_name: Optional[str] = None
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    location: dict = field(default_factory=lambda: {"city": None, "region": None, "country": None})
    links: dict = field(default_factory=lambda: {"linkedin": None, "github": None, "portfolio": None, "other": []})
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: List[dict] = field(default_factory=list)
    experience: List[dict] = field(default_factory=list)
    education: List[dict] = field(default_factory=list)
    provenance: List[dict] = field(default_factory=list)
    overall_confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "candidate_id":       self.candidate_id,
            "full_name":          self.full_name,
            "emails":             self.emails,
            "phones":             self.phones,
            "location":           self.location,
            "links":              self.links,
            "headline":           self.headline,
            "years_experience":   self.years_experience,
            "skills":             self.skills,
            "experience":         self.experience,
            "education":          self.education,
            "provenance":         self.provenance,
            "overall_confidence": self.overall_confidence,
        }


# ---------------------------------------------------------------------------
# JSON Schema for output validation
# ---------------------------------------------------------------------------

CANONICAL_JSON_SCHEMA = {
    "type": "object",
    "required": ["candidate_id", "full_name", "emails"],
    "properties": {
        "candidate_id":       {"type": "string"},
        "full_name":          {"type": ["string", "null"]},
        "emails":             {"type": "array", "items": {"type": "string"}},
        "phones":             {"type": "array", "items": {"type": "string"}},
        "location": {
            "type": "object",
            "properties": {
                "city":    {"type": ["string", "null"]},
                "region":  {"type": ["string", "null"]},
                "country": {"type": ["string", "null"]},
            },
        },
        "links": {
            "type": "object",
            "properties": {
                "linkedin":  {"type": ["string", "null"]},
                "github":    {"type": ["string", "null"]},
                "portfolio": {"type": ["string", "null"]},
                "other":     {"type": "array", "items": {"type": "string"}},
            },
        },
        "headline":           {"type": ["string", "null"]},
        "years_experience":   {"type": ["number", "null"]},
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":       {"type": "string"},
                    "confidence": {"type": "number"},
                    "sources":    {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": ["string", "null"]},
                    "title":   {"type": ["string", "null"]},
                    "start":   {"type": ["string", "null"]},
                    "end":     {"type": ["string", "null"]},
                    "summary": {"type": ["string", "null"]},
                },
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": ["string", "null"]},
                    "degree":      {"type": ["string", "null"]},
                    "field":       {"type": ["string", "null"]},
                    "end_year":    {"type": ["number", "null"]},
                },
            },
        },
        "provenance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field":      {"type": "string"},
                    "source":     {"type": "string"},
                    "method":     {"type": "string"},
                    "raw_value":  {},
                    "confidence": {"type": "number"},
                },
            },
        },
        "overall_confidence": {"type": "number"},
    },
}
