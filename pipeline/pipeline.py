"""
pipeline/pipeline.py

Main orchestrator — ties all stages together in order:

  DETECT → EXTRACT → NORMALIZE (done inside extractors) → MERGE
  → VALIDATE → PROJECT → VALIDATE OUTPUT → OUTPUT

Usage:
    from pipeline import run_pipeline
    result = run_pipeline(
        inputs=["data/sample_recruiter.csv", "data/sample_ats.json"],
        github_url="https://github.com/ajaybalaji",
        config_path="configs/custom_config.json",
    )
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from .detect import detect_source_type
from .extractors import (
    ATSJsonExtractor, CSVExtractor, GitHubExtractor,
    LinkedInExtractor, TextExtractor,
)
from .extractors.base import BaseExtractor
from .merge import merge
from .project import load_config, project
from .schema import RawField
from .validate import validate_output, validate_profile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extractor registry — maps source type to extractor class
# ---------------------------------------------------------------------------

def _build_extractor(source_type: str, weights: Dict[str, float]) -> Optional[BaseExtractor]:
    registry = {
        "csv":        CSVExtractor,
        "ats_json":   ATSJsonExtractor,
        "github":     GitHubExtractor,
        "linkedin":   LinkedInExtractor,
        "resume":     TextExtractor,
        "text_notes": TextExtractor,
    }
    cls = registry.get(source_type)
    if cls is None:
        return None
    return cls(confidence_weights=weights)


# ---------------------------------------------------------------------------
# Main pipeline function
# ---------------------------------------------------------------------------

def run_pipeline(
    inputs: List[str],
    github_url: Optional[str] = None,
    config_path: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Run the full candidate data transformation pipeline.

    Parameters
    ----------
    inputs      : list of file paths (CSV, JSON, PDF, DOCX, TXT)
    github_url  : optional GitHub profile URL or username
    config_path : path to a projection config JSON (default: default_config.json)
    verbose     : if True, emit INFO-level logs to stdout

    Returns
    -------
    dict — the projected, validated output JSON-serialisable dict
    """
    if verbose:
        logging.basicConfig(level=logging.INFO,
                            format="%(levelname)s [%(name)s] %(message)s")

    # ── Load configuration & weights ─────────────────────────────────────────
    config  = load_config(config_path)
    weights = _load_weights()
    skill_lookup = _load_skill_lookup()

    # ── Build source list (files + optional GitHub URL) ───────────────────────
    sources: List[str] = list(inputs)
    if github_url:
        sources.append(github_url)

    # ── DETECT & EXTRACT ─────────────────────────────────────────────────────
    all_raw_fields: List[RawField] = []

    for source in sources:
        source_type = detect_source_type(source)
        logger.info("Detected '%s' → type: %s", source, source_type)

        extractor = _build_extractor(source_type, weights)
        if extractor is None:
            logger.warning("No extractor for source type '%s' ('%s') — skipped",
                           source_type, source)
            continue

        try:
            raw_fields = extractor.extract(source)
            logger.info("  Extracted %d raw fields", len(raw_fields))
            all_raw_fields.extend(raw_fields)
        except Exception as exc:
            # A well-behaved extractor should never raise, but belt-and-suspenders
            logger.error("  Extractor error for '%s': %s — skipped", source, exc)

    if not all_raw_fields:
        logger.warning("No fields extracted from any source — returning empty profile")
        return {"candidate_id": "", "error": "no_data_extracted"}

def group_fields_by_candidate(all_fields: List[RawField]) -> List[List[RawField]]:
    """
    Group RawFields into clusters where each cluster represents a unique candidate.
    Clustering is done via Union-Find (Disjoint Set) based on:
      1. Shared email addresses (case-insensitive)
      2. Shared phone numbers
      3. Shared names AND at least one social link (GitHub or LinkedIn)
    """
    from collections import defaultdict
    # Group RawFields by their exact source record (the 'source' attribute)
    record_fields = defaultdict(list)
    for rf in all_fields:
        record_fields[rf.source].append(rf)

    records = list(record_fields.keys())
    n = len(records)
    if n <= 1:
        return [all_fields]

    # Extract identifying fields for each source record
    record_info = {}
    for r in records:
        emails = set()
        phones = set()
        names = set()
        githubs = set()
        linkedins = set()
        for rf in record_fields[r]:
            if rf.canonical_name == "emails":
                emails.add(str(rf.value).lower().strip())
            elif rf.canonical_name == "phones":
                phones.add(str(rf.value).strip())
            elif rf.canonical_name == "full_name":
                names.add(str(rf.value).lower().strip())
            elif rf.canonical_name == "links.github":
                githubs.add(str(rf.value).lower().strip())
            elif rf.canonical_name == "links.linkedin":
                linkedins.add(str(rf.value).lower().strip())
        record_info[r] = {
            "emails": emails,
            "phones": phones,
            "names": names,
            "githubs": githubs,
            "linkedins": linkedins
        }

    # Union-Find helper
    parent = {r: r for r in records}
    def find(r):
        if parent[r] != r:
            parent[r] = find(parent[r])
        return parent[r]
    def union(r1, r2):
        root1 = find(r1)
        root2 = find(r2)
        if root1 != root2:
            parent[root1] = root2

    # Connect records that share identifiers
    for i in range(n):
        for j in range(i + 1, n):
            r1 = records[i]
            r2 = records[j]
            info1 = record_info[r1]
            info2 = record_info[r2]

            # Rule 1: Shared email
            if info1["emails"] & info2["emails"]:
                union(r1, r2)
                continue

            # Rule 2: Shared phone
            if info1["phones"] & info2["phones"]:
                union(r1, r2)
                continue

            # Rule 3: Shared name AND social link
            if info1["names"] & info2["names"]:
                shared_github = info1["githubs"] & info2["githubs"]
                shared_linkedin = info1["linkedins"] & info2["linkedins"]
                if shared_github or shared_linkedin:
                    union(r1, r2)
                    continue

    # Group the RawFields by their root parent
    groups = defaultdict(list)
    for r in records:
        root = find(r)
        groups[root].extend(record_fields[r])

    return list(groups.values())


# ---------------------------------------------------------------------------
# Main pipeline function
# ---------------------------------------------------------------------------

def run_pipeline(
    inputs: List[str],
    github_url: Optional[str] = None,
    config_path: Optional[str] = None,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    """
    Run the full candidate data transformation pipeline.

    Parameters
    ----------
    inputs      : list of file paths (CSV, JSON, PDF, DOCX, TXT)
    github_url  : optional GitHub profile URL or username
    config_path : path to a projection config JSON (default: default_config.json)
    verbose     : if True, emit INFO-level logs to stdout

    Returns
    -------
    list of dicts — the projected, validated output JSON-serialisable dicts (one per candidate)
    """
    if verbose:
        logging.basicConfig(level=logging.INFO,
                            format="%(levelname)s [%(name)s] %(message)s")

    # ── Load configuration & weights ─────────────────────────────────────────
    config  = load_config(config_path)
    weights = _load_weights()
    skill_lookup = _load_skill_lookup()

    # ── Build source list (files + optional GitHub URL) ───────────────────────
    sources: List[str] = list(inputs)
    if github_url:
        sources.append(github_url)

    # ── DETECT & EXTRACT ─────────────────────────────────────────────────────
    all_raw_fields: List[RawField] = []

    for source in sources:
        source_type = detect_source_type(source)
        logger.info("Detected '%s' → type: %s", source, source_type)

        extractor = _build_extractor(source_type, weights)
        if extractor is None:
            logger.warning("No extractor for source type '%s' ('%s') — skipped",
                           source_type, source)
            continue

        try:
            raw_fields = extractor.extract(source)
            logger.info("  Extracted %d raw fields", len(raw_fields))
            all_raw_fields.extend(raw_fields)
        except Exception as exc:
            # A well-behaved extractor should never raise, but belt-and-suspenders
            logger.error("  Extractor error for '%s': %s — skipped", source, exc)

    if not all_raw_fields:
        logger.warning("No fields extracted from any source — returning empty profile")
        return []

    # ── GROUP BY CANDIDATE ───────────────────────────────────────────────────
    candidate_groups = group_fields_by_candidate(all_raw_fields)
    logger.info("Grouped %d raw fields into %d unique candidate(s)",
                len(all_raw_fields), len(candidate_groups))

    results = []
    for idx, group_fields in enumerate(candidate_groups):
        # ── MERGE ────────────────────────────────────────────────────────────
        profile = merge(group_fields)

        # ── VALIDATE (canonical profile) ─────────────────────────────────────
        val_result = validate_profile(profile)
        if val_result.warnings or val_result.errors:
            for msg in val_result.warnings:
                logger.warning("Candidate #%d Validation: %s", idx + 1, msg)
            for msg in val_result.errors:
                logger.error("Candidate #%d Validation error: %s", idx + 1, msg)

        # ── PROJECT ──────────────────────────────────────────────────────────
        output = project(profile, config, skill_lookup=skill_lookup)

        # ── VALIDATE OUTPUT ───────────────────────────────────────────────────
        out_val = validate_output(output, config)
        for msg in out_val.warnings:
            logger.warning("Candidate #%d Output validation: %s", idx + 1, msg)
        for msg in out_val.errors:
            logger.error("Candidate #%d Output validation error: %s", idx + 1, msg)

        # Attach validation metadata (for transparency)
        output["_pipeline_meta"] = {
            "sources_processed": len(sources),
            "raw_fields_extracted": len(group_fields),
            "validation_warnings": val_result.warnings,
            "validation_errors":   val_result.errors,
        }
        results.append(output)

    logger.info("Pipeline complete. Processed %d candidates.", len(results))
    return results


# ---------------------------------------------------------------------------
# Helper loaders
# ---------------------------------------------------------------------------

def _load_weights() -> Dict[str, float]:
    base = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base, "configs", "confidence_weights.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}


def _load_skill_lookup() -> dict:
    base = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base, "data", "canonical_skills.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}
