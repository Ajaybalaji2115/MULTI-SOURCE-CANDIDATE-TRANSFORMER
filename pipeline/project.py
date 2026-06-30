"""
pipeline/project.py

Config-driven projection layer.

Transforms the internal CanonicalProfile into any output shape described
by a runtime config JSON. The core pipeline is never modified to change
output format — only the config changes.

Config schema:
{
  "fields": [
    {
      "path":      <output field name>,
      "from":      <dot/bracket path into canonical record, optional>,
      "type":      "string" | "string[]" | "number" | "object" | "object[]",
      "normalize": "E164" | "canonical" | "iso3166" (optional),
      "required":  true | false (optional, default false)
    }
  ],
  "include_confidence": true | false,
  "on_missing":  "null" | "omit" | "error"
}
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .normalize import normalize_phone, normalize_skill, normalize_country
from .schema import CanonicalProfile


# ---------------------------------------------------------------------------
# Path resolver
# ---------------------------------------------------------------------------

_ARRAY_INDEX_RE = re.compile(r"^(\w+)\[(\d+)\]$")   # emails[0]
_ARRAY_GLOB_RE  = re.compile(r"^(\w+)\[\]$")         # skills[]


def _resolve_path(record: dict, path: str) -> Any:
    """
    Resolve a dot-path (possibly with array indexing) from a dict.

    Supported path forms:
      "full_name"           → record["full_name"]
      "location.city"       → record["location"]["city"]
      "emails[0]"           → record["emails"][0]
      "experience[0].company" → record["experience"][0]["company"]
      "skills[].name"       → [s["name"] for s in record["skills"]]
    """
    parts = path.split(".")
    current: Any = record

    i = 0
    while i < len(parts):
        part = parts[i]
        if current is None:
            return None

        # Array glob: "skills[]" followed by a sub-key next part
        glob_match = _ARRAY_GLOB_RE.match(part)
        if glob_match:
            arr_key = glob_match.group(1)
            arr = current.get(arr_key, []) if isinstance(current, dict) else []
            if not isinstance(arr, list):
                return None
            # Collect remaining path after the glob
            remaining = ".".join(parts[i + 1:])
            if remaining:
                return [_resolve_path(item, remaining)
                        for item in arr if isinstance(item, dict)]
            return arr

        # Indexed access: "emails[0]"
        idx_match = _ARRAY_INDEX_RE.match(part)
        if idx_match:
            key, idx = idx_match.groups()
            arr = current.get(key, []) if isinstance(current, dict) else []
            if not isinstance(arr, list) or int(idx) >= len(arr):
                return None
            current = arr[int(idx)]
            i += 1
            continue

        # Simple key
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        i += 1

    return current


# ---------------------------------------------------------------------------
# Per-field extra normalization at projection time
# ---------------------------------------------------------------------------

def _apply_normalize(value: Any, normalize_flag: Optional[str], skill_lookup: dict) -> Any:
    if not normalize_flag or value is None:
        return value
    flag = normalize_flag.upper()
    if flag == "E164":
        if isinstance(value, list):
            return [normalize_phone(v) for v in value]
        return normalize_phone(value)
    if flag == "CANONICAL":
        if isinstance(value, list):
            return [normalize_skill(v, skill_lookup) for v in value]
        return normalize_skill(value, skill_lookup)
    if flag == "ISO3166":
        if isinstance(value, list):
            return [normalize_country(v) for v in value]
        return normalize_country(value)
    return value


# ---------------------------------------------------------------------------
# Main projection function
# ---------------------------------------------------------------------------

def project(
    profile: CanonicalProfile,
    config: dict,
    skill_lookup: Optional[dict] = None,
) -> dict:
    """
    Apply *config* to *profile* and return the projected output dict.

    Parameters
    ----------
    profile      : CanonicalProfile — the merged canonical record
    config       : dict — the parsed config JSON
    skill_lookup : dict — canonical skills alias table (for 'canonical' normalize)

    Returns
    -------
    dict — the projected output, ready for JSON serialisation
    """
    if skill_lookup is None:
        skill_lookup = {}

    record    = profile.to_dict()
    fields    = config.get("fields", [])
    on_missing = config.get("on_missing", "null")
    include_conf = config.get("include_confidence", False)
    include_prov = config.get("include_provenance", True)

    # If no fields specified, return the full canonical record
    if not fields:
        output = dict(record)
        if include_conf:
            output["overall_confidence"] = profile.overall_confidence
        if not include_prov and "provenance" in output:
            del output["provenance"]
        return output

    output: Dict[str, Any] = {}

    for field_def in fields:
        out_key    = field_def.get("path")
        source_key = field_def.get("from", out_key)   # default: same as path
        required   = field_def.get("required", False)
        norm_flag  = field_def.get("normalize")

        if not out_key:
            continue

        # Resolve value from canonical record
        value = _resolve_path(record, source_key)

        # Apply extra normalization
        value = _apply_normalize(value, norm_flag, skill_lookup)

        # Handle missing / null
        if value is None or (isinstance(value, list) and len(value) == 0):
            if required and on_missing == "error":
                raise ValueError(
                    f"Required field '{out_key}' (from '{source_key}') is missing or null."
                )
            if on_missing == "omit":
                continue
            # on_missing == "null" (default): include as null
            output[out_key] = None
        else:
            output[out_key] = value

    if include_conf:
        output["overall_confidence"] = profile.overall_confidence
    if not include_prov and "provenance" in output:
        del output["provenance"]

    return output


# ---------------------------------------------------------------------------
# Config loader helper
# ---------------------------------------------------------------------------

def load_config(config_path: Optional[str]) -> dict:
    """Load a config JSON file, or return the default (full schema) config."""
    if not config_path:
        import os
        base = os.path.dirname(os.path.dirname(__file__))
        config_path = os.path.join(base, "configs", "default_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        raise RuntimeError(f"Failed to load config '{config_path}': {e}")
