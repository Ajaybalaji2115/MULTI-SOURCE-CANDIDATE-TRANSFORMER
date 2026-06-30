"""
pipeline/extractors/linkedin_extractor.py

Extracts candidate fields from an official LinkedIn data export JSON file.

This extractor works with the JSON format that LinkedIn provides when a user
downloads their own data via Settings → Data Privacy → Get a copy of your data.
It does NOT scrape LinkedIn (which violates their ToS).

For testing, a mock JSON with the same structure is used (sample_linkedin_export.json).

Expected top-level keys:
    firstName, lastName, emailAddress, phoneNumbers, headline, summary,
    locationName, geoCountryName, positions, educations, skills, websites
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


class LinkedInExtractor(BaseExtractor):
    SOURCE_TYPE = "linkedin"

    def extract(self, source: str) -> List[RawField]:
        label = self._source_label(source)
        skill_lookup = self._load_skill_lookup()

        try:
            with open(source, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("LinkedIn JSON read failed for '%s': %s", source, exc)
            return []

        if not isinstance(data, dict):
            logger.warning("LinkedIn JSON: expected dict, got %s", type(data).__name__)
            return []

        return self._build_fields(data, label, skill_lookup)

    def _build_fields(self, data: dict, label: str, skill_lookup: dict) -> List[RawField]:
        fields: List[RawField] = []
        conf = self.base_confidence

        # ── Full Name ────────────────────────────────────────────────────────
        first = data.get("firstName", "")
        last  = data.get("lastName",  "")
        full  = f"{first} {last}".strip()
        if full:
            name = normalize_name(full)
            if name:
                fields.append(RawField("full_name", name, label,
                                       "li_field:firstName+lastName", full, conf))

        # ── Email ────────────────────────────────────────────────────────────
        email_raw = data.get("emailAddress")
        if email_raw:
            email = normalize_email(str(email_raw))
            if email:
                fields.append(RawField("emails", email, label,
                                       "li_field:emailAddress", email_raw, conf))

        # ── Phone ────────────────────────────────────────────────────────────
        for ph_obj in (data.get("phoneNumbers") or []):
            if isinstance(ph_obj, dict):
                number = ph_obj.get("number")
            else:
                number = str(ph_obj)
            phone = normalize_phone(number)
            if phone:
                fields.append(RawField("phones", phone, label,
                                       "li_field:phoneNumbers", number, conf))

        # ── Headline ─────────────────────────────────────────────────────────
        headline = data.get("headline") or data.get("summary")
        if headline and isinstance(headline, str):
            fields.append(RawField("headline", headline.strip(), label,
                                   "li_field:headline", headline, conf * 0.9))

        # ── Location ─────────────────────────────────────────────────────────
        loc_name = data.get("locationName")
        if loc_name:
            parts = [p.strip() for p in str(loc_name).split(",")]
            if parts:
                fields.append(RawField("location.city", parts[0], label,
                                       "li_field:locationName", loc_name, conf * 0.8))
                if len(parts) > 1:
                    fields.append(RawField("location.region", parts[1], label,
                                           "li_field:locationName", loc_name, conf * 0.8))

        country_raw = data.get("geoCountryName")
        if country_raw:
            country = normalize_country(str(country_raw))
            if country:
                fields.append(RawField("location.country", country, label,
                                       "li_field:geoCountryName", country_raw, conf))

        # ── Positions → experience ───────────────────────────────────────────
        positions = data.get("positions") or []
        if positions:
            exp_entries = []
            for pos in positions:
                if not isinstance(pos, dict):
                    continue
                start = normalize_date(pos.get("startDate") or pos.get("start_date"))
                end   = normalize_date(pos.get("endDate")   or pos.get("end_date"))
                exp_entries.append({
                    "company": pos.get("companyName") or pos.get("company"),
                    "title":   pos.get("title"),
                    "start":   start,
                    "end":     end,
                    "summary": pos.get("description"),
                })
            if exp_entries:
                fields.append(RawField("experience", exp_entries, label,
                                       "li_field:positions", positions, conf))

        # ── Educations ───────────────────────────────────────────────────────
        educations = data.get("educations") or []
        if educations:
            edu_entries = []
            for edu in educations:
                if not isinstance(edu, dict):
                    continue
                end_year = None
                end_date = edu.get("endDate") or edu.get("end_date")
                if isinstance(end_date, dict):
                    end_year = end_date.get("year")
                elif isinstance(end_date, (int, str)):
                    try:
                        end_year = int(str(end_date)[:4])
                    except ValueError:
                        pass
                edu_entries.append({
                    "institution": edu.get("schoolName") or edu.get("school"),
                    "degree":      edu.get("degreeName") or edu.get("degree"),
                    "field":       edu.get("fieldOfStudy") or edu.get("field"),
                    "end_year":    end_year,
                })
            if edu_entries:
                fields.append(RawField("education", edu_entries, label,
                                       "li_field:educations", educations, conf))

        # ── Skills ───────────────────────────────────────────────────────────
        skills_raw = data.get("skills") or []
        skill_items = []
        for s in skills_raw:
            name_raw = s.get("name") if isinstance(s, dict) else str(s)
            canonical = normalize_skill(name_raw, skill_lookup)
            skill_items.append({
                "name": canonical,
                "confidence": conf,
                "sources": [label],
            })
        if skill_items:
            fields.append(RawField("skills", skill_items, label,
                                   "li_field:skills", skills_raw, conf))

        # ── Websites → links ─────────────────────────────────────────────────
        for site in (data.get("websites") or []):
            url = site.get("url") if isinstance(site, dict) else str(site)
            kind = (site.get("type") or "").upper() if isinstance(site, dict) else ""
            if not url:
                continue
            if "github.com" in url:
                fields.append(RawField("links.github", url, label,
                                       "li_field:websites", url, conf))
            elif kind == "PORTFOLIO" or "portfolio" in url.lower():
                fields.append(RawField("links.portfolio", url, label,
                                       "li_field:websites", url, conf))
            else:
                fields.append(RawField("links.other", url, label,
                                       "li_field:websites", url, conf))

        logger.info("LinkedIn: extracted %d fields from '%s'", len(fields), label)
        return fields
