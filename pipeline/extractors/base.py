"""
pipeline/extractors/base.py

Abstract base class for all extractors.

Every extractor must implement:
    extract(source: str) -> List[RawField]

The *source* argument is either a file path or a URL depending on the
extractor type. If extraction fails for any reason, the method must log
a warning and return an empty list — it must never raise.
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, List

from ..schema import RawField

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Abstract base for all source extractors."""

    SOURCE_TYPE: str = "unknown"   # Override in subclass

    def __init__(self, confidence_weights: Dict[str, float]):
        self.confidence_weights = confidence_weights
        self.base_confidence: float = confidence_weights.get(self.SOURCE_TYPE, 0.5)

    @abstractmethod
    def extract(self, source: str) -> List[RawField]:
        """
        Parse *source* and return a list of RawField evidence objects.

        Must never raise — return [] on any failure.
        """

    def _source_label(self, source: str) -> str:
        """Return 'source_type:basename' label for provenance."""
        basename = os.path.basename(source) if os.path.exists(source) else source
        return f"{self.SOURCE_TYPE}:{basename}"

    @staticmethod
    def _load_skill_lookup() -> dict:
        """Load canonical_skills.json from the data directory."""
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        path = os.path.join(base, "data", "canonical_skills.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    @staticmethod
    def _load_confidence_weights() -> Dict[str, float]:
        """Load confidence_weights.json from the configs directory."""
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        path = os.path.join(base, "configs", "confidence_weights.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception:
            return {}
