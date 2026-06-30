"""
pipeline/extractors/csv_extractor.py

Extracts candidate fields from a Recruiter CSV export.

Expected columns (case-insensitive):
    full_name / name, email, phone, current_company, title,
    location, linkedin_url, years_experience

All missing values become null in provenance — never invented.
"""
from __future__ import annotations

import csv
import logging
from typing import Dict, List, Optional

from ..normalize import (
    normalize_email, normalize_name, normalize_phone,
    normalize_country, normalize_skill,
)
from ..schema import RawField
from .base import BaseExtractor

logger = logging.getLogger(__name__)


# Mapping of possible CSV column names → our canonical field names
_COLUMN_MAP = {
    "full_name":          "full_name",
    "name":               "full_name",
    "candidate_name":     "full_name",
    "email":              "emails",
    "email_address":      "emails",
    "contact_email":      "emails",
    "phone":              "phones",
    "phone_number":       "phones",
    "contact_phone":      "phones",
    "mobile":             "phones",
    "current_company":    "experience",
    "company":            "experience",
    "employer":           "experience",
    "title":              "experience",
    "job_title":          "experience",
    "position":           "experience",
    "location":           "location",
    "city":               "location.city",
    "country":            "location.country",
    "linkedin_url":       "links.linkedin",
    "linkedin":           "links.linkedin",
    "github_url":         "links.github",
    "github":             "links.github",
    "years_experience":   "years_experience",
    "experience_years":   "years_experience",
}


class CSVExtractor(BaseExtractor):
    SOURCE_TYPE = "csv"

    def extract(self, source: str) -> List[RawField]:
        label = self._source_label(source)
        fields: List[RawField] = []

        try:
            with open(source, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
        except Exception as exc:
            logger.warning("CSV read failed for '%s': %s", source, exc)
            return []

        for row_idx, row in enumerate(rows):
            row_fields = self._extract_row(row, label, row_idx)
            fields.extend(row_fields)

        logger.info("CSV: extracted %d fields from %d rows in '%s'",
                    len(fields), len(rows), source)
        return fields

    def _extract_row(self, row: Dict[str, str], label: str, row_idx: int) -> List[RawField]:
        """Extract all recognisable fields from a single CSV row."""
        label = f"{label}:row_{row_idx}"
        fields: List[RawField] = []

        # Normalise column names to lowercase/stripped
        normalised = {k.strip().lower(): v.strip() for k, v in row.items() if v and v.strip()}

        # Collect raw company and title separately so we can build an experience entry
        company: Optional[str] = None
        job_title: Optional[str] = None

        for col, raw_val in normalised.items():
            canonical = _COLUMN_MAP.get(col)
            if not canonical:
                continue

            if canonical == "full_name":
                name = normalize_name(raw_val)
                if name:
                    fields.append(RawField(
                        canonical_name="full_name",
                        value=name,
                        source=label,
                        method="csv_column:full_name",
                        raw_value=raw_val,
                        confidence=self.base_confidence,
                    ))

            elif canonical == "emails":
                email = normalize_email(raw_val)
                if email:
                    fields.append(RawField(
                        canonical_name="emails",
                        value=email,
                        source=label,
                        method="csv_column:email",
                        raw_value=raw_val,
                        confidence=self.base_confidence,
                    ))

            elif canonical == "phones":
                phone = normalize_phone(raw_val)
                if phone:
                    fields.append(RawField(
                        canonical_name="phones",
                        value=phone,
                        source=label,
                        method="csv_column:phone",
                        raw_value=raw_val,
                        confidence=self.base_confidence,
                    ))

            elif canonical == "experience":  # company or title column
                if col in ("current_company", "company", "employer"):
                    company = raw_val
                elif col in ("title", "job_title", "position"):
                    job_title = raw_val

            elif canonical == "location":
                # Parse "Chennai India" style free-text location
                parts = raw_val.split()
                if parts:
                    # Last token → try as country
                    country = normalize_country(parts[-1])
                    city = " ".join(parts[:-1]) if len(parts) > 1 else None
                    if city:
                        fields.append(RawField(
                            canonical_name="location.city",
                            value=city,
                            source=label,
                            method="csv_column:location",
                            raw_value=raw_val,
                            confidence=self.base_confidence * 0.8,
                        ))
                    if country:
                        fields.append(RawField(
                            canonical_name="location.country",
                            value=country,
                            source=label,
                            method="csv_column:location",
                            raw_value=raw_val,
                            confidence=self.base_confidence,
                        ))

            elif canonical == "location.city":
                fields.append(RawField(
                    canonical_name="location.city",
                    value=raw_val,
                    source=label,
                    method=f"csv_column:{col}",
                    raw_value=raw_val,
                    confidence=self.base_confidence,
                ))

            elif canonical == "location.country":
                country = normalize_country(raw_val)
                if country:
                    fields.append(RawField(
                        canonical_name="location.country",
                        value=country,
                        source=label,
                        method=f"csv_column:{col}",
                        raw_value=raw_val,
                        confidence=self.base_confidence,
                    ))

            elif canonical == "links.linkedin":
                fields.append(RawField(
                    canonical_name="links.linkedin",
                    value=raw_val,
                    source=label,
                    method="csv_column:linkedin_url",
                    raw_value=raw_val,
                    confidence=self.base_confidence,
                ))

            elif canonical == "links.github":
                fields.append(RawField(
                    canonical_name="links.github",
                    value=raw_val,
                    source=label,
                    method="csv_column:github_url",
                    raw_value=raw_val,
                    confidence=self.base_confidence,
                ))

            elif canonical == "years_experience":
                try:
                    yrs = float(raw_val)
                    fields.append(RawField(
                        canonical_name="years_experience",
                        value=yrs,
                        source=label,
                        method="csv_column:years_experience",
                        raw_value=raw_val,
                        confidence=self.base_confidence,
                    ))
                except ValueError:
                    logger.debug("Non-numeric years_experience '%s' ignored", raw_val)

        # Build experience entry from company + title
        if company or job_title:
            exp_entry = {
                "company": company,
                "title":   job_title,
                "start":   None,
                "end":     None,
                "summary": None,
            }
            fields.append(RawField(
                canonical_name="experience",
                value=[exp_entry],
                source=label,
                method="csv_columns:company+title",
                raw_value={"company": company, "title": job_title},
                confidence=self.base_confidence,
            ))

        return fields
