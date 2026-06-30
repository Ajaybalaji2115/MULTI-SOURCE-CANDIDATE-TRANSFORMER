"""
pipeline/detect.py

Identifies the source type of an input so it can be routed to the
correct extractor. Detection is based on file extension, MIME-type
heuristics, and URL patterns.

Source type strings (canonical):
    "csv"       — Recruiter CSV export
    "ats_json"  — ATS JSON blob (list of applicant objects)
    "github"    — GitHub profile URL
    "linkedin"  — LinkedIn data-export JSON
    "resume"    — Resume PDF or DOCX
    "text_notes"— Free-text notes / plain-text resume (.txt)
    "unknown"   — Cannot be determined
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def detect_source_type(source: str) -> str:
    """
    Detect the source type of *source*.

    Parameters
    ----------
    source : str
        Either a file path (absolute or relative) or a URL string.

    Returns
    -------
    str
        One of the canonical source type strings listed above.
    """
    src = source.strip()

    # ── URL patterns ────────────────────────────────────────────────────────
    if src.startswith("http://") or src.startswith("https://"):
        if "github.com/" in src:
            return "github"
        if "linkedin.com/" in src:
            # LinkedIn scraping is out of scope; treat URL as a link only
            return "unknown"
        return "unknown"

    # ── File-based detection ─────────────────────────────────────────────────
    path = Path(src)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return "csv"

    if suffix == ".pdf":
        return "resume"

    if suffix in (".doc", ".docx"):
        return "resume"

    if suffix == ".txt":
        return "text_notes"

    if suffix == ".json":
        return _inspect_json(src)

    return "unknown"


def _inspect_json(filepath: str) -> str:
    """
    Peek inside a JSON file to decide whether it is an ATS blob or a
    LinkedIn export.

    Heuristics:
    - LinkedIn export:  top-level object with "firstName" / "lastName" keys
                        OR "positions" / "educations" / "emailAddress" keys.
    - ATS JSON:         a list of objects, or a top-level object without
                        LinkedIn-style keys.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return "unknown"

    linkedin_keys = {"firstName", "lastName", "emailAddress", "positions",
                     "educations", "headline", "locationName"}

    if isinstance(data, dict):
        if linkedin_keys & set(data.keys()):
            return "linkedin"
        return "ats_json"

    if isinstance(data, list):
        # List of applicant dicts → ATS JSON
        return "ats_json"

    return "unknown"
