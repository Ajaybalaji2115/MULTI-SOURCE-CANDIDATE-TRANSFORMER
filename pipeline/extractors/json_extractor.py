"""
pipeline/extractors/json_extractor.py

Extracts candidate fields from an ATS JSON blob.

The ATS uses its own field names that do NOT match our canonical schema.
This extractor maps them via a configurable field-map.

Handles both:
  - A list of applicant objects (most common ATS export)
  - A single applicant object
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..normalize import (
    normalize_date, normalize_email, normalize_name,
    normalize_phone, normalize_skill, normalize_country,
)
from ..schema import RawField
from .base import BaseExtractor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ATS field name → canonical field name mapping
# ---------------------------------------------------------------------------

_ATS_FIELD_MAP: Dict[str, str] = {
    # Name variants
    "applicant_name":   "full_name",
    "candidate_name":   "full_name",
    "name":             "full_name",
    "full_name":        "full_name",
    # Email variants
    "contact_email":    "emails",
    "email":            "emails",
    "email_address":    "emails",
    # Phone variants
    "contact_phone":    "phones",
    "phone":            "phones",
    "mobile":           "phones",
    # Company / title
    "org":              "_company",
    "company":          "_company",
    "current_company":  "_company",
    "employer":         "_company",
    "role":             "_title",
    "title":            "_title",
    "position":         "_title",
    "job_title":        "_title",
    # Location
    "city":             "location.city",
    "region":           "location.region",
    "country_of_origin":"location.country",
    "country":          "location.country",
    # Links
    "profile_url":      "_profile_url",
    "linkedin_url":     "links.linkedin",
    "github_url":       "links.github",
    # Other
    "summary":          "headline",
    "skill_tags":       "skills",
    "work_history":     "experience",
    "academic_history": "education",
    "years_experience": "years_experience",
}


class ATSJsonExtractor(BaseExtractor):
    SOURCE_TYPE = "ats_json"

    def extract(self, source: str) -> List[RawField]:
        label = self._source_label(source)
        skill_lookup = self._load_skill_lookup()

        try:
            with open(source, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("ATS JSON read failed for '%s': %s", source, exc)
            return []

        records = data if isinstance(data, list) else [data]
        all_fields: List[RawField] = []

        for record_idx, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            record_label = f"{label}:record_{record_idx}"
            all_fields.extend(self._extract_record(record, record_label, skill_lookup))

        logger.info("ATS JSON: extracted %d fields from %d records in '%s'",
                    len(all_fields), len(records), source)
        return all_fields

    def _extract_record(self, record: dict, label: str, skill_lookup: dict) -> List[RawField]:
        fields: List[RawField] = []
        company: Optional[str] = None
        job_title: Optional[str] = None

        for ats_key, raw_val in record.items():
            canonical = _ATS_FIELD_MAP.get(ats_key.lower().strip())
            if not canonical or raw_val is None:
                continue

            # ── Name ──────────────────────────────────────────────────────
            if canonical == "full_name":
                name = normalize_name(str(raw_val))
                if name:
                    fields.append(RawField("full_name", name, label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence))

            # ── Email ─────────────────────────────────────────────────────
            elif canonical == "emails":
                email = normalize_email(str(raw_val))
                if email:
                    fields.append(RawField("emails", email, label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence))

            # ── Phone ─────────────────────────────────────────────────────
            elif canonical == "phones":
                phone = normalize_phone(str(raw_val))
                if phone:
                    fields.append(RawField("phones", phone, label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence))

            # ── Location ──────────────────────────────────────────────────
            elif canonical == "location.city":
                fields.append(RawField("location.city", str(raw_val), label,
                                       f"ats_field:{ats_key}", raw_val,
                                       self.base_confidence))
            elif canonical == "location.region":
                fields.append(RawField("location.region", str(raw_val), label,
                                       f"ats_field:{ats_key}", raw_val,
                                       self.base_confidence))
            elif canonical == "location.country":
                country = normalize_country(str(raw_val))
                if country:
                    fields.append(RawField("location.country", country, label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence))

            # ── Company / Title (deferred to experience entry) ────────────
            elif canonical == "_company":
                company = str(raw_val)
            elif canonical == "_title":
                job_title = str(raw_val)

            # ── Profile URL — detect GitHub vs LinkedIn ───────────────────
            elif canonical == "_profile_url" and raw_val:
                url = str(raw_val)
                if "github.com" in url:
                    fields.append(RawField("links.github", url, label,
                                           f"ats_field:{ats_key}", url,
                                           self.base_confidence))
                elif "linkedin.com" in url:
                    fields.append(RawField("links.linkedin", url, label,
                                           f"ats_field:{ats_key}", url,
                                           self.base_confidence))

            # ── Headline / Summary ────────────────────────────────────────
            elif canonical == "headline":
                if isinstance(raw_val, str) and raw_val.strip():
                    fields.append(RawField("headline", raw_val.strip(), label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence * 0.9))

            # ── Skills list ───────────────────────────────────────────────
            elif canonical == "skills" and isinstance(raw_val, list):
                skill_items = []
                for s in raw_val:
                    name = normalize_skill(str(s), skill_lookup)
                    skill_items.append({
                        "name": name, "confidence": self.base_confidence,
                        "sources": [label],
                    })
                if skill_items:
                    fields.append(RawField("skills", skill_items, label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence))

            # ── Work history list ─────────────────────────────────────────
            elif canonical == "experience" and isinstance(raw_val, list):
                exp_entries = []
                for job in raw_val:
                    if not isinstance(job, dict):
                        continue
                    start = normalize_date(job.get("from") or job.get("start_date") or job.get("startDate"))
                    end   = normalize_date(job.get("to")   or job.get("end_date")   or job.get("endDate"))
                    exp_entries.append({
                        "company": job.get("employer") or job.get("company") or job.get("org"),
                        "title":   job.get("position") or job.get("title") or job.get("role"),
                        "start":   start,
                        "end":     end,
                        "summary": job.get("description") or job.get("summary"),
                    })
                if exp_entries:
                    fields.append(RawField("experience", exp_entries, label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence))

            # ── Academic history list ─────────────────────────────────────
            elif canonical == "education" and isinstance(raw_val, list):
                edu_entries = []
                for edu in raw_val:
                    if not isinstance(edu, dict):
                        continue
                    end_year = None
                    gy = edu.get("grad_year") or edu.get("end_year") or edu.get("graduation_year")
                    if gy:
                        try:
                            end_year = int(gy)
                        except (TypeError, ValueError):
                            pass
                    edu_entries.append({
                        "institution": edu.get("school") or edu.get("institution") or edu.get("university"),
                        "degree":      edu.get("qualification") or edu.get("degree"),
                        "field":       edu.get("subject") or edu.get("field") or edu.get("fieldOfStudy"),
                        "end_year":    end_year,
                    })
                if edu_entries:
                    fields.append(RawField("education", edu_entries, label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence))

            # ── Years of experience ───────────────────────────────────────
            elif canonical == "years_experience":
                try:
                    yrs = float(raw_val)
                    fields.append(RawField("years_experience", yrs, label,
                                           f"ats_field:{ats_key}", raw_val,
                                           self.base_confidence))
                except (TypeError, ValueError):
                    pass

        # Build experience entry from flat company/title fields
        if company or job_title:
            exp_entry = {"company": company, "title": job_title,
                         "start": None, "end": None, "summary": None}
            fields.append(RawField("experience", [exp_entry], label,
                                   "ats_fields:org+role", {"org": company, "role": job_title},
                                   self.base_confidence))

        return fields
