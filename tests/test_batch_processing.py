"""tests/test_batch_processing.py — Unit tests for candidate grouping, other links, and provenance toggles."""
import pytest
from pipeline.schema import RawField, CanonicalProfile
from pipeline.pipeline import group_fields_by_candidate
from pipeline.project import project
from pipeline.merge import merge


def test_group_fields_by_candidate_matching_emails():
    # Two records sharing an email should be grouped together
    fields = [
        RawField("full_name", "Ajay Balaji", "csv:file1.csv:row_0", "test"),
        RawField("emails", "ajay.balaji@gmail.com", "csv:file1.csv:row_0", "test"),
        RawField("emails", "ajay.balaji@gmail.com", "ats:file2.json:record_0", "test"),
        RawField("headline", "Developer", "ats:file2.json:record_0", "test"),
        # Another candidate
        RawField("full_name", "Priya Sharma", "csv:file1.csv:row_1", "test"),
        RawField("emails", "priya@outlook.com", "csv:file1.csv:row_1", "test"),
    ]
    groups = group_fields_by_candidate(fields)
    assert len(groups) == 2

    # Verify group sizes
    # Group 1 (Ajay) has 4 fields
    # Group 2 (Priya) has 2 fields
    group_lens = [len(g) for g in groups]
    assert 4 in group_lens
    assert 2 in group_lens


def test_group_fields_by_candidate_matching_names_and_socials():
    # Two records sharing a name and a GitHub link should be grouped together
    fields = [
        RawField("full_name", "Ajay Balaji", "csv:file1.csv:row_0", "test"),
        RawField("links.github", "https://github.com/ajay", "csv:file1.csv:row_0", "test"),
        # Record 2: same name and same GitHub link
        RawField("full_name", "Ajay Balaji", "resume:resume.txt", "test"),
        RawField("links.github", "https://github.com/ajay", "resume:resume.txt", "test"),
        # Record 3: same name but NO shared link/email -> should be separate
        RawField("full_name", "Ajay Balaji", "csv:file1.csv:row_1", "test"),
    ]
    groups = group_fields_by_candidate(fields)
    assert len(groups) == 2


def test_links_other_merged():
    fields = [
        RawField("links.other", "https://example.com/blog", "csv:file1.csv:row_0", "test"),
        RawField("links.other", "https://example.com/blog", "resume:resume.txt", "test"), # duplicate
        RawField("links.other", "https://another-link.com", "resume:resume.txt", "test"),
    ]
    profile = merge(fields)
    assert len(profile.links["other"]) == 2
    assert "https://example.com/blog" in profile.links["other"]
    assert "https://another-link.com" in profile.links["other"]


def test_include_provenance_toggle():
    profile = CanonicalProfile()
    profile.candidate_id = "123"
    profile.full_name = "Ajay Balaji"
    profile.emails = ["ajay@gmail.com"]
    profile.provenance = [{"field": "full_name", "source": "test", "method": "test", "confidence": 1.0}]

    # Case 1: include_provenance = True (default)
    config_with_prov = {"fields": [], "include_provenance": True}
    out_with_prov = project(profile, config_with_prov)
    assert "provenance" in out_with_prov
    assert len(out_with_prov["provenance"]) == 1

    # Case 2: include_provenance = False
    config_no_prov = {"fields": [], "include_provenance": False}
    out_no_prov = project(profile, config_no_prov)
    assert "provenance" not in out_no_prov
