"""
pipeline/extractors/text_extractor.py

Section-based extractor for:
  - Plain-text resumes (.txt)
  - DOCX resumes (.docx)
  - PDF resumes (.pdf)
  - Recruiter notes (.txt)

Pipeline:
  1. Text extraction layer    (raw text from PDF/DOCX/TXT)
  2. Section detection        (split into EDUCATION, EXPERIENCE, SKILLS, etc.)
  3. Per-section regex rules  (extract structured data from each section)
  4. Contact block parsing    (top of document: email, phone, links, name)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..normalize import (
    normalize_date, normalize_email, normalize_name,
    normalize_phone, normalize_skill, normalize_country,
)
from ..schema import RawField
from .base import BaseExtractor

logger = logging.getLogger(__name__)

# ── Optional heavy dependencies (soft imports) ────────────────────────────────
try:
    import pdfplumber as _pdfplumber
    _PDF_AVAILABLE = True
except ImportError:  # pragma: no cover
    _pdfplumber = None  # type: ignore[assignment]
    _PDF_AVAILABLE = False

try:
    from docx import Document as _DocxDocument
    _DOCX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DocxDocument = None  # type: ignore[assignment,misc]
    _DOCX_AVAILABLE = False

# ── Section header patterns ──────────────────────────────────────────────────
_SECTION_HEADERS = {
    "summary":     re.compile(r"^\s*(summary|objective|profile|about)\s*$", re.I),
    "skills":      re.compile(r"^\s*(skills?|technical skills?|core competencies|expertise)\s*$", re.I),
    "experience":  re.compile(r"^\s*(experience|work experience|employment|professional experience|work history)\s*$", re.I),
    "education":   re.compile(r"^\s*(education|academic|qualifications?|degrees?)\s*$", re.I),
    "projects":    re.compile(r"^\s*(projects?|personal projects?|side projects?)\s*$", re.I),
    "certifications": re.compile(r"^\s*(certifications?|certificates?|licenses?)\s*$", re.I),
}

# ── Contact block regex ──────────────────────────────────────────────────────
_EMAIL_RE    = re.compile(r"[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+")
_PHONE_RE    = re.compile(r"(?:\+?\d[\d\s\-\(\)\.]{7,15}\d)")
_GITHUB_RE   = re.compile(r"https?://(?:www\.)?github\.com/[\w\-]+")
_LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[\w\-]+")
_URL_RE      = re.compile(r"https?://[\w\-\.]+\.[\w\-]{2,}(?:/[\w\-\./\?=&%]*)?")

# ── Date range pattern for experience ────────────────────────────────────────
_DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{4}"
    r"|\d{4}[-/]\d{2}|\d{4})"
    r"\s*[-–—to]+\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{4}"
    r"|\d{4}[-/]\d{2}|\d{4}|present|current|now|ongoing)",
    re.I,
)

# ── Degree keywords ──────────────────────────────────────────────────────────
_DEGREE_RE = re.compile(
    r"\b(B\.?Tech|B\.?E\.?|B\.?Sc?\.?|B\.?A\.?|M\.?Tech|M\.?E\.?|M\.?Sc?\.?|M\.?A\.?|"
    r"MBA|PhD|Ph\.D|Bachelor|Master|Doctor|Associate|Diploma)\b",
    re.I,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# ── Sub-section header inside Skills block (e.g. "Languages:", "Frameworks:") ─
_SUBHEADER_RE = re.compile(r"^[A-Z][A-Za-z /]+:\s*", re.M)


class TextExtractor(BaseExtractor):
    SOURCE_TYPE = "resume"  # overridden for notes

    def extract(self, source: str) -> List[RawField]:
        path = Path(source)
        suffix = path.suffix.lower()

        # Determine source type for confidence weights
        if suffix == ".txt":
            # Heuristic: if file contains "note" or is very short → text_notes
            self.SOURCE_TYPE = "text_notes"
            self.base_confidence = self.confidence_weights.get("text_notes", 0.60)
        else:
            self.SOURCE_TYPE = "resume"
            self.base_confidence = self.confidence_weights.get("resume", 0.65)

        text = self._read_text(source, suffix)
        if not text:
            return []

        label = self._source_label(source)
        skill_lookup = self._load_skill_lookup()

        sections = self._split_sections(text)
        fields: List[RawField] = []

        # Contact block (top of document)
        contact_block = sections.get("_header", text[:800])
        fields.extend(self._parse_contact_block(contact_block, label, text))

        # Skills
        if "skills" in sections:
            fields.extend(self._parse_skills(sections["skills"], label, skill_lookup))

        # Experience
        if "experience" in sections:
            fields.extend(self._parse_experience(sections["experience"], label))

        # Education
        if "education" in sections:
            fields.extend(self._parse_education(sections["education"], label))

        # Summary → headline
        if "summary" in sections:
            summary = sections["summary"].strip()
            if summary:
                fields.append(RawField("headline", summary[:300], label,
                                       "section:summary", summary,
                                       self.base_confidence * 0.9))

        logger.info("TextExtractor: extracted %d fields from '%s'", len(fields), source)
        return fields

    # ── Text extraction layer ────────────────────────────────────────────────

    def _read_text(self, source: str, suffix: str) -> str:
        if suffix == ".txt":
            try:
                return Path(source).read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.warning("TXT read failed '%s': %s", source, exc)
                return ""
        if suffix == ".pdf":
            return self._read_pdf(source)
        if suffix in (".doc", ".docx"):
            return self._read_docx(source)
        return ""

    @staticmethod
    def _read_pdf(source: str) -> str:
        if not _PDF_AVAILABLE:
            logger.warning("pdfplumber not installed — PDF extraction skipped. "
                           "Run: pip install pdfplumber")
            return ""
        try:
            with _pdfplumber.open(source) as pdf:  # type: ignore[union-attr]
                pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(pages)
        except Exception as exc:
            logger.warning("PDF read failed '%s': %s", source, exc)
            return ""

    @staticmethod
    def _read_docx(source: str) -> str:
        if not _DOCX_AVAILABLE:
            logger.warning("python-docx not installed — DOCX extraction skipped. "
                           "Run: pip install python-docx")
            return ""
        try:
            doc = _DocxDocument(source)  # type: ignore[call-arg]
            return "\n".join(para.text for para in doc.paragraphs)
        except Exception as exc:
            logger.warning("DOCX read failed '%s': %s", source, exc)
            return ""

    # ── Section detection ────────────────────────────────────────────────────

    def _split_sections(self, text: str) -> Dict[str, str]:
        """
        Split document text into named sections based on common resume headers.
        Returns {section_name: section_content} + "_header" for the top block.
        """
        lines = text.splitlines()
        sections: Dict[str, str] = {}
        current_section = "_header"
        current_lines: List[str] = []

        for line in lines:
            matched_section = None
            for sec_name, pattern in _SECTION_HEADERS.items():
                if pattern.match(line):
                    matched_section = sec_name
                    break

            if matched_section:
                sections[current_section] = "\n".join(current_lines)
                current_section = matched_section
                current_lines = []
            else:
                current_lines.append(line)

        sections[current_section] = "\n".join(current_lines)
        return sections

    # ── Contact block ────────────────────────────────────────────────────────

    def _parse_contact_block(
        self, block: str, label: str, full_text: str
    ) -> List[RawField]:
        fields: List[RawField] = []
        conf = self.base_confidence

        # Name — heuristic: first non-empty, mostly-alpha line in document
        for line in full_text.splitlines()[:10]:
            line = line.strip()
            if (line and len(line) > 3 and
                    sum(c.isalpha() or c.isspace() for c in line) / len(line) > 0.8 and
                    not _EMAIL_RE.search(line) and
                    not _PHONE_RE.search(line)):
                name = normalize_name(line)
                if name:
                    fields.append(RawField("full_name", name, label,
                                           "heuristic:first_line", line, conf * 0.85))
                    break

        # Emails
        for email_raw in _EMAIL_RE.findall(block):
            email = normalize_email(email_raw)
            if email:
                fields.append(RawField("emails", email, label,
                                       "regex:email", email_raw, conf))

        # Phones
        seen_phones = set()
        for phone_raw in _PHONE_RE.findall(block):
            phone = normalize_phone(phone_raw.strip())
            if phone and phone not in seen_phones:
                fields.append(RawField("phones", phone, label,
                                       "regex:phone", phone_raw, conf))
                seen_phones.add(phone)

        # GitHub URL
        for url in _GITHUB_RE.findall(full_text):
            fields.append(RawField("links.github", url, label,
                                   "regex:github_url", url, conf))

        # LinkedIn URL
        for url in _LINKEDIN_RE.findall(full_text):
            fields.append(RawField("links.linkedin", url, label,
                                   "regex:linkedin_url", url, conf))

        # Portfolio URL (first non-github, non-linkedin URL)
        all_urls = _URL_RE.findall(block)
        for url in all_urls:
            if "github.com" not in url and "linkedin.com" not in url:
                fields.append(RawField("links.portfolio", url, label,
                                       "regex:url", url, conf * 0.7))
                break

        return fields

    # ── Skills ───────────────────────────────────────────────────────────────

    def _parse_skills(
        self, section: str, label: str, skill_lookup: dict
    ) -> List[RawField]:
        skill_items = []
        # Strip sub-section headers like "Languages:", "Frameworks:", "ML/AI:"
        cleaned = _SUBHEADER_RE.sub("", section)
        # Split by common delimiters
        tokens = re.split(r"[,|•\n\t]+", cleaned)
        for token in tokens:
            token = token.strip().strip(":-").strip()
            # Skip empty, too short, or too long tokens
            if not token or len(token) < 2 or len(token) > 40:
                continue
            canonical = normalize_skill(token, skill_lookup)
            skill_items.append({
                "name": canonical,
                "confidence": self.base_confidence,
                "sources": [label],
            })
        if skill_items:
            return [RawField("skills", skill_items, label,
                             "section:skills", section, self.base_confidence)]
        return []

    # ── Experience ───────────────────────────────────────────────────────────

    def _parse_experience(self, section: str, label: str) -> List[RawField]:
        entries = []
        # Split into job blocks on lines that start with a capital letter
        blocks = re.split(r"\n(?=[A-Z])", section)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue

            # ── Extract date range first, then remove it from the header line ──
            start_date = end_date = None
            date_match = _DATE_RANGE_RE.search(block)
            if date_match:
                start_date = normalize_date(date_match.group(1))
                end_raw    = date_match.group(2)
                end_date   = (
                    None
                    if end_raw.lower() in ("present", "current", "now", "ongoing")
                    else normalize_date(end_raw)
                )

            # ── Clean the header line: strip the date range from it ───────────
            header = _DATE_RANGE_RE.sub("", lines[0]).strip().strip("|-").strip()

            # ── Split "Title | Company" or "Title @ Company" or "Title at Co" ─
            title   = None
            company = None
            if header:
                sep = re.split(r"\s*[|@]\s*|\s+at\s+", header, maxsplit=1)
                if len(sep) == 2:
                    title   = sep[0].strip() or None
                    company = sep[1].strip() or None
                else:
                    title = header or None
                    # Second line may be the company if it doesn't contain a date
                    if len(lines) > 1 and not _DATE_RANGE_RE.search(lines[1]):
                        company = lines[1].strip() or None

            # ── Summary = bullet lines after header ───────────────────────────
            start_idx = 2 if (company and len(lines) > 1 and lines[1] == (company or "")) else 1
            summary_lines = [ln for ln in lines[start_idx:] if ln]
            summary = " ".join(summary_lines)[:500] if summary_lines else None

            if title or company:
                entries.append({
                    "company": company,
                    "title":   title,
                    "start":   start_date,
                    "end":     end_date,
                    "summary": summary,
                })

        if entries:
            return [RawField("experience", entries, label,
                             "section:experience", section, self.base_confidence)]
        return []

    # ── Education ────────────────────────────────────────────────────────────

    def _parse_education(self, section: str, label: str) -> List[RawField]:
        entries = []
        # Split on blank lines — each block is one institution
        blocks = re.split(r"\n\n+", section)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            institution = None
            degree      = None
            field_name  = None
            end_year    = None

            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]

            # ── Degree keyword ────────────────────────────────────────────────
            degree_match = _DEGREE_RE.search(block)
            if degree_match:
                degree = degree_match.group(0)

            # ── Year (take the maximum year found as graduation year) ──────────
            year_matches = _YEAR_RE.findall(block)
            if year_matches:
                end_year = max(int(y) for y in year_matches)

            # ── Institution: find the line that looks most like a school name ──
            # Prefer a line that does NOT contain a degree keyword or a year,
            # and is not a pipe-separated list.  Fall back to first line.
            for ln in lines:
                is_degree_line = bool(_DEGREE_RE.search(ln))
                has_year       = bool(_YEAR_RE.search(ln))
                has_colon      = ":" in ln          # excludes GPA/metadata lines
                is_short_alpha = (len(ln) > 3 and
                                  sum(c.isalpha() or c.isspace() for c in ln) / len(ln) > 0.6)
                if is_short_alpha and not is_degree_line and not has_year and not has_colon:
                    institution = ln
                    break
            if institution is None and lines:
                # Fallback: try pipe-separated segments first (e.g. "B.Tech | IIT Madras | 2025")
                first_line = lines[0]
                if "|" in first_line:
                    segments = [s.strip() for s in first_line.split("|")]
                    for seg in segments:
                        seg_clean = _DEGREE_RE.sub("", seg).strip()
                        seg_clean = _YEAR_RE.sub("", seg_clean).strip(" -–")
                        if (seg_clean and len(seg_clean) > 3 and
                                not _YEAR_RE.search(seg) and
                                not _DEGREE_RE.search(seg)):
                            institution = seg_clean.strip()
                            break
                if institution is None:
                    # Last resort: strip degree + year tokens from the whole first line
                    fallback = _DEGREE_RE.sub("", first_line)
                    fallback = _YEAR_RE.sub("", fallback)
                    fallback = re.sub(r"[|,\-–]", " ", fallback)
                    fallback = re.sub(r"\s{2,}", " ", fallback).strip()
                    institution = fallback or None


            # ── Field of study ────────────────────────────────────────────────
            for ln in lines:
                in_match = re.search(r"\bin\s+([A-Za-z][^|\n,]+)", ln, re.I)
                if in_match:
                    field_name = in_match.group(1).strip()
                    break

            if institution or degree:
                entries.append({
                    "institution": institution,
                    "degree":      degree,
                    "field":       field_name,
                    "end_year":    end_year,
                })

        if entries:
            return [RawField("education", entries, label,
                             "section:education", section, self.base_confidence)]
        return []
