"""
pipeline/merge.py

Merges all RawField evidence from every extractor into a single
CanonicalProfile using a completeness-first conflict resolution policy.

Conflict resolution (scalar fields):
  1. Score each candidate value by completeness (length/richness)
  2. Break ties by confidence
  3. Break further ties by source_type priority (structured > unstructured)
  All competing values are stored in provenance.

Array fields (emails, phones, skills, experience, education):
  Union + deduplicate, sorted by confidence descending.

Candidate ID generation (fallback chain):
  SHA256(email) → SHA256(name+phone) → SHA256(name+url) → UUID4 (flagged)
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
import warnings
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .normalize import completeness_score
from .schema import CanonicalProfile, RawField


# ---------------------------------------------------------------------------
# Source-type priority (used only as final tiebreaker)
# ---------------------------------------------------------------------------

_SOURCE_PRIORITY: Dict[str, int] = {
    "csv":        5,
    "ats_json":   4,
    "github":     3,
    "linkedin":   3,
    "resume":     2,
    "text_notes": 1,
}

_SCALAR_FIELDS = {
    "full_name", "headline", "years_experience",
    "location.city", "location.region", "location.country",
    "links.linkedin", "links.github", "links.portfolio",
}

_ARRAY_FIELDS = {"emails", "phones"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_priority(source_label: str) -> int:
    """Extract the source-type prefix from 'csv:filename.csv' → priority int."""
    source_type = source_label.split(":")[0] if ":" in source_label else source_label
    return _SOURCE_PRIORITY.get(source_type, 0)


def _load_confidence_weights() -> Dict[str, float]:
    """Load configurable confidence weights from configs/confidence_weights.json."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    weights_path = os.path.join(base_dir, "configs", "confidence_weights.json")
    try:
        with open(weights_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        # Fallback defaults
        return {
            "csv": 0.90, "ats_json": 0.85, "github": 0.75,
            "linkedin": 0.70, "resume": 0.65, "text_notes": 0.60,
            "agreement_bonus": 0.05, "max_confidence": 1.0,
        }


# ---------------------------------------------------------------------------
# Candidate ID generation
# ---------------------------------------------------------------------------

def generate_candidate_id(
    emails: List[str],
    name: Optional[str],
    phones: List[str],
    links: Dict[str, Any],
    provenance: List[dict],
) -> str:
    """
    Deterministic ID generation with fallback chain:
      1. SHA256(primary_email)
      2. SHA256(normalize(name) + E164(phone))
      3. SHA256(normalize(name) + github_or_linkedin_url)
      4. UUID4 (flagged in provenance)
    """
    def sha256(s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    # Step 1 — email
    if emails:
        return sha256(emails[0].lower())

    # Step 2 — name + phone
    if name and phones:
        return sha256(name.lower().strip() + phones[0])

    # Step 3 — name + URL
    url = links.get("github") or links.get("linkedin")
    if name and url:
        return sha256(name.lower().strip() + url.lower().strip())

    # Step 4 — UUID fallback (flagged)
    fallback_id = str(uuid.uuid4())
    provenance.append({
        "field":      "candidate_id",
        "source":     "system",
        "method":     "uuid4_fallback",
        "raw_value":  None,
        "confidence": 0.1,
    })
    warnings.warn("candidate_id fell back to UUID4 — no reliable identifier found.")
    return fallback_id


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def _dedup_strings(items: List[dict]) -> List[dict]:
    """Deduplicate list of {value, confidence, source} by normalized value."""
    seen: Dict[str, dict] = {}
    for item in items:
        key = str(item["value"]).lower().strip()
        if key not in seen or item["confidence"] > seen[key]["confidence"]:
            seen[key] = item
    return sorted(seen.values(), key=lambda x: x["confidence"], reverse=True)


def _dedup_skills(skills: List[dict]) -> List[dict]:
    seen: Dict[str, dict] = {}
    for s in skills:
        key = s["name"].lower().strip()
        if key not in seen:
            seen[key] = s
        else:
            # Merge sources and boost confidence
            existing = seen[key]
            existing["sources"] = list(set(existing["sources"] + s["sources"]))
            existing["confidence"] = min(
                1.0,
                max(existing["confidence"], s["confidence"]) + 0.05 * (len(existing["sources"]) - 1),
            )
    return sorted(seen.values(), key=lambda x: x["confidence"], reverse=True)


def _dedup_experience(entries: List[dict]) -> List[dict]:
    """Deduplicate experience by (company, title, start) triple."""
    seen: Dict[tuple, dict] = {}
    for e in entries:
        key = (
            (e.get("company") or "").lower().strip(),
            (e.get("title") or "").lower().strip(),
            e.get("start") or "",
        )
        if key not in seen:
            seen[key] = e
    return list(seen.values())


def _dedup_education(entries: List[dict]) -> List[dict]:
    """Deduplicate education by (institution, degree) pair."""
    seen: Dict[tuple, dict] = {}
    for e in entries:
        key = (
            (e.get("institution") or "").lower().strip(),
            (e.get("degree") or "").lower().strip(),
        )
        if key not in seen:
            seen[key] = e
    return list(seen.values())


# ---------------------------------------------------------------------------
# Scalar field resolution
# ---------------------------------------------------------------------------

def _resolve_scalar(candidates: List[RawField]) -> RawField:
    """
    Completeness-first conflict resolution for a single scalar field.
    Returns the winning RawField.
    """
    def sort_key(rf: RawField):
        comp   = completeness_score(rf.value)
        conf   = rf.confidence
        prio   = _source_priority(rf.source)
        return (comp, conf, prio)

    return max(candidates, key=sort_key)


# ---------------------------------------------------------------------------
# Main merge function
# ---------------------------------------------------------------------------

def merge(raw_fields: List[RawField]) -> CanonicalProfile:
    """
    Merge a list of RawField evidence into one CanonicalProfile.

    Steps:
      1. Group fields by canonical_name.
      2. Resolve scalar conflicts (completeness-first).
      3. Union array fields (emails, phones).
      4. Aggregate skills, experience, education.
      5. Compute overall_confidence.
      6. Generate candidate_id.
      7. Build provenance list.
    """
    weights = _load_confidence_weights()
    agreement_bonus = weights.get("agreement_bonus", 0.05)
    max_conf = weights.get("max_confidence", 1.0)

    # Group all evidence by field name
    grouped: Dict[str, List[RawField]] = defaultdict(list)
    for rf in raw_fields:
        grouped[rf.canonical_name].append(rf)

    profile = CanonicalProfile()
    field_confidences: List[float] = []
    provenance: List[dict] = []

    # ── Helper to record provenance ──────────────────────────────────────────
    def record_provenance(rf: RawField):
        provenance.append({
            "field":      rf.canonical_name,
            "source":     rf.source,
            "method":     rf.method,
            "raw_value":  rf.raw_value,
            "confidence": rf.confidence,
        })

    # ── Scalar fields ────────────────────────────────────────────────────────
    for fname in _SCALAR_FIELDS:
        candidates = grouped.get(fname, [])
        if not candidates:
            continue

        winner = _resolve_scalar(candidates)

        # Agreement bonus if multiple sources agree (same normalized value)
        agreement_count = sum(
            1 for rf in candidates
            if str(rf.value).lower().strip() == str(winner.value).lower().strip()
            and rf is not winner
        )
        final_conf = min(max_conf, winner.confidence + agreement_count * agreement_bonus)

        # Record all candidates in provenance
        for rf in candidates:
            record_provenance(rf)

        field_confidences.append(final_conf)

        # Set on profile
        if fname == "full_name":
            profile.full_name = winner.value
        elif fname == "headline":
            profile.headline = winner.value
        elif fname == "years_experience":
            try:
                profile.years_experience = float(winner.value)
            except (TypeError, ValueError):
                profile.years_experience = None
        elif fname.startswith("location."):
            key = fname.split(".")[1]
            profile.location[key] = winner.value
        elif fname.startswith("links."):
            key = fname.split(".")[1]
            profile.links[key] = winner.value

    # ── Array fields: emails & phones ────────────────────────────────────────
    for fname in _ARRAY_FIELDS:
        candidates = grouped.get(fname, [])
        if not candidates:
            continue
        items = [{"value": rf.value, "confidence": rf.confidence, "source": rf.source}
                 for rf in candidates]
        deduped = _dedup_strings(items)
        values = [d["value"] for d in deduped]

        if fname == "emails":
            profile.emails = values
        elif fname == "phones":
            profile.phones = values

        avg_conf = sum(d["confidence"] for d in deduped) / len(deduped)
        field_confidences.append(avg_conf)
        for rf in candidates:
            record_provenance(rf)

    # ── Skills (union + dedup) ────────────────────────────────────────────────
    skill_raws = grouped.get("skills", [])
    if skill_raws:
        all_skills: List[dict] = []
        for rf in skill_raws:
            record_provenance(rf)
            if isinstance(rf.value, list):
                for s in rf.value:
                    if isinstance(s, dict):
                        all_skills.append(s)
                    else:
                        all_skills.append({
                            "name": str(s),
                            "confidence": rf.confidence,
                            "sources": [rf.source],
                        })
        profile.skills = _dedup_skills(all_skills)
        if profile.skills:
            field_confidences.append(
                sum(s["confidence"] for s in profile.skills) / len(profile.skills)
            )

    # ── Experience (union + dedup) ────────────────────────────────────────────
    exp_raws = grouped.get("experience", [])
    if exp_raws:
        all_exp: List[dict] = []
        for rf in exp_raws:
            record_provenance(rf)
            if isinstance(rf.value, list):
                all_exp.extend(rf.value)
        profile.experience = _dedup_experience(all_exp)

    # ── Education (union + dedup) ─────────────────────────────────────────────
    edu_raws = grouped.get("education", [])
    if edu_raws:
        all_edu: List[dict] = []
        for rf in edu_raws:
            record_provenance(rf)
            if isinstance(rf.value, list):
                all_edu.extend(rf.value)
        profile.education = _dedup_education(all_edu)

    # ── Other links (union + dedup) ──────────────────────────────────────────
    other_raws = grouped.get("links.other", [])
    if other_raws:
        other_links = []
        for rf in other_raws:
            record_provenance(rf)
            if isinstance(rf.value, list):
                other_links.extend(rf.value)
            else:
                other_links.append(rf.value)
        seen_other = set()
        deduped_other = []
        for link in other_links:
            l_clean = str(link).strip().lower()
            if l_clean and l_clean not in seen_other:
                seen_other.add(l_clean)
                deduped_other.append(link)
        profile.links["other"] = deduped_other

    # ── Overall confidence ────────────────────────────────────────────────────
    if field_confidences:
        profile.overall_confidence = round(
            sum(field_confidences) / len(field_confidences), 4
        )

    # ── Candidate ID ──────────────────────────────────────────────────────────
    profile.provenance = provenance
    profile.candidate_id = generate_candidate_id(
        emails=profile.emails,
        name=profile.full_name,
        phones=profile.phones,
        links=profile.links,
        provenance=provenance,
    )

    return profile
