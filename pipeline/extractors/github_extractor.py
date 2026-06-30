"""
pipeline/extractors/github_extractor.py

Extracts candidate data from a public GitHub profile via the GitHub REST API.

API calls made:
  GET https://api.github.com/users/{username}
    → name, bio, location, company, blog (portfolio), public_repos, followers

  GET https://api.github.com/users/{username}/repos?per_page=100&sort=pushed
    → languages (aggregated by frequency), topics

Error handling:
  - 404 → profile not found, return []
  - 403 → rate limit hit, return [] with warning
  - Any network error → return [] with warning
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional
from datetime import datetime

import requests

from ..normalize import normalize_name, normalize_skill, normalize_country
from ..schema import RawField
from .base import BaseExtractor

logger = logging.getLogger(__name__)

import os

_GITHUB_API  = "https://api.github.com"
_HEADERS     = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

# Use GITHUB_TOKEN environment variable as the API key if provided
_TOKEN = os.getenv("GITHUB_TOKEN")
if _TOKEN:
    _HEADERS["Authorization"] = f"token {_TOKEN}"

_USERNAME_RE = re.compile(r"github\.com/([A-Za-z0-9\-]+)/?$")


class GitHubExtractor(BaseExtractor):
    SOURCE_TYPE = "github"

    def extract(self, source: str) -> List[RawField]:
        """
        *source* must be a GitHub profile URL or username string.
        e.g. "https://github.com/ajaybalaji" or "ajaybalaji"
        """
        username = self._parse_username(source)
        if not username:
            logger.warning("GitHub: could not parse username from '%s'", source)
            return []

        label = f"github:{username}"
        skill_lookup = self._load_skill_lookup()

        user_data = self._fetch_user(username)
        if user_data is None:
            return []

        repos_data = self._fetch_repos(username)
        return self._build_fields(user_data, repos_data, label, skill_lookup, username)

    # ── API helpers ──────────────────────────────────────────────────────────

    def _fetch_user(self, username: str) -> Optional[Dict[str, Any]]:
        url = f"{_GITHUB_API}/users/{username}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            if resp.status_code == 404:
                logger.warning("GitHub: user '%s' not found (404)", username)
                return None
            if resp.status_code == 403:
                logger.warning("GitHub: rate limit hit for '%s' (403)", username)
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("GitHub: network error fetching user '%s': %s", username, exc)
            return None

    def _fetch_repos(self, username: str) -> List[Dict[str, Any]]:
        url = f"{_GITHUB_API}/users/{username}/repos"
        params = {"per_page": 100, "sort": "pushed"}
        try:
            resp = requests.get(url, headers=_HEADERS, params=params, timeout=10)
            if resp.status_code in (403, 404):
                return []
            resp.raise_for_status()
            return resp.json() if isinstance(resp.json(), list) else []
        except requests.RequestException:
            return []

    # ── Field builders ───────────────────────────────────────────────────────

    def _build_fields(
        self,
        user: Dict[str, Any],
        repos: List[Dict[str, Any]],
        label: str,
        skill_lookup: dict,
        username: str,
    ) -> List[RawField]:
        fields: List[RawField] = []
        conf = self.base_confidence

        # Name
        if user.get("name"):
            name = normalize_name(user["name"])
            if name:
                fields.append(RawField("full_name", name, label,
                                       "api_field:name", user["name"], conf))

        # Email (public GitHub email, often null)
        if user.get("email"):
            fields.append(RawField("emails", user["email"].lower().strip(), label,
                                   "api_field:email", user["email"], conf))

        # Bio → headline
        if user.get("bio"):
            fields.append(RawField("headline", user["bio"].strip(), label,
                                   "api_field:bio", user["bio"], conf * 0.9))

        # Location (free text — best-effort country parse)
        if user.get("location"):
            loc_raw = user["location"]
            parts = [p.strip() for p in loc_raw.split(",")]
            if len(parts) >= 2:
                city    = parts[0]
                country = normalize_country(parts[-1])
                fields.append(RawField("location.city", city, label,
                                       "api_field:location", loc_raw, conf * 0.8))
                if country:
                    fields.append(RawField("location.country", country, label,
                                           "api_field:location", loc_raw, conf))
            else:
                country = normalize_country(loc_raw)
                if country:
                    fields.append(RawField("location.country", country, label,
                                           "api_field:location", loc_raw, conf))

        # Company → experience stub
        if user.get("company"):
            company = user["company"].lstrip("@").strip()
            fields.append(RawField("experience", [{
                "company": company, "title": None,
                "start": None, "end": None, "summary": None,
            }], label, "api_field:company", user["company"], conf * 0.7))

        # Blog → portfolio link
        if user.get("blog"):
            blog = user["blog"].strip()
            if blog and not blog.startswith("http"):
                blog = "https://" + blog
            fields.append(RawField("links.portfolio", blog, label,
                                   "api_field:blog", user["blog"], conf))

        # GitHub URL
        fields.append(RawField("links.github",
                               f"https://github.com/{username}", label,
                               "api_field:html_url", username, conf))

        # Years of experience — derived from account creation date (signal only)
        if user.get("created_at"):
            try:
                created = datetime.strptime(user["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                yrs = round((datetime.utcnow() - created).days / 365.25, 1)
                fields.append(RawField("years_experience", yrs, label,
                                       "derived:account_age", user["created_at"],
                                       conf * 0.4))  # low confidence — rough signal
            except (ValueError, TypeError):
                pass

        # Skills from repo languages
        skill_items = self._extract_skills_from_repos(repos, label, skill_lookup)
        if skill_items:
            fields.append(RawField("skills", skill_items, label,
                                   "api:repos_languages", None, conf))

        logger.info("GitHub: extracted %d fields for user '%s'", len(fields), username)
        return fields

    def _extract_skills_from_repos(
        self, repos: List[Dict], label: str, skill_lookup: dict
    ) -> List[dict]:
        """
        Aggregate languages across all repos and rank by frequency.
        Also pulls topics from repos.
        """
        lang_counter: Counter = Counter()
        topic_set: set = set()

        for repo in repos:
            lang = repo.get("language")
            if lang:
                lang_counter[lang] += 1
            for topic in (repo.get("topics") or []):
                topic_set.add(topic)

        skill_items = []
        total = sum(lang_counter.values()) or 1

        for lang, count in lang_counter.most_common(10):
            canonical = normalize_skill(lang, skill_lookup)
            freq_conf = min(1.0, self.base_confidence * (count / total * 3 + 0.5))
            skill_items.append({
                "name": canonical,
                "confidence": round(freq_conf, 3),
                "sources": [label],
            })

        for topic in list(topic_set)[:5]:
            canonical = normalize_skill(topic, skill_lookup)
            skill_items.append({
                "name": canonical,
                "confidence": round(self.base_confidence * 0.6, 3),
                "sources": [label],
            })

        return skill_items

    @staticmethod
    def _parse_username(source: str) -> Optional[str]:
        """Extract GitHub username from a URL or plain username string."""
        source = source.strip().rstrip("/")
        match = _USERNAME_RE.search(source)
        if match:
            return match.group(1)
        # Plain username (no slashes, no dots)
        if "/" not in source and "." not in source:
            return source
        return None
