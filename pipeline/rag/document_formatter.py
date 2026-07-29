"""
pipeline/rag/document_formatter.py

Formats canonical candidate profiles into dense, human-readable markdown summaries.
This text is used for both generating text embeddings and as LLM context prompts.
"""
from typing import Any, Dict, List, Optional

def format_candidate_for_rag(profile: Dict[str, Any]) -> str:
    """
    Convert a canonical candidate profile dictionary to a dense Markdown text representation.
    """
    lines = []

    # Name and ID
    name = profile.get("full_name") or "Unknown Candidate"
    candidate_id = profile.get("candidate_id") or "N/A"
    lines.append(f"Candidate Name: {name}")
    lines.append(f"Candidate ID: {candidate_id}")

    # Headline and Confidence
    headline = profile.get("headline")
    if headline:
        lines.append(f"Headline: {headline}")
    
    confidence = profile.get("overall_confidence")
    if confidence is not None:
        lines.append(f"Profile Confidence Score: {confidence:.2f}")

    # Experience details
    years_exp = profile.get("years_experience")
    if years_exp is not None:
        lines.append(f"Years of Experience: {years_exp}")

    # Contact & Links
    emails = profile.get("emails", [])
    if emails:
        lines.append(f"Emails: {', '.join(emails)}")

    phones = profile.get("phones", [])
    if phones:
        lines.append(f"Phones: {', '.join(phones)}")

    loc = profile.get("location") or {}
    city = loc.get("city")
    region = loc.get("region")
    country = loc.get("country")
    loc_parts = [p for p in [city, region, country] if p]
    if loc_parts:
        lines.append(f"Location: {', '.join(loc_parts)}")

    links = profile.get("links") or {}
    link_parts = []
    for platform in ["linkedin", "github", "portfolio"]:
        val = links.get(platform)
        if val:
            link_parts.append(f"{platform.capitalize()}: {val}")
    other_links = links.get("other", [])
    for idx, l in enumerate(other_links):
        link_parts.append(f"Link {idx+1}: {l}")
    if link_parts:
        lines.append(f"Links: {'; '.join(link_parts)}")

    # Skills
    skills = profile.get("skills", [])
    if skills:
        # We can list skills with their names, or maybe grouped
        skill_strs = []
        for s in skills:
            name_str = s.get("name")
            if name_str:
                conf = s.get("confidence")
                if conf is not None:
                    skill_strs.append(f"{name_str} (conf: {conf:.2f})")
                else:
                    skill_strs.append(name_str)
        lines.append(f"Skills: {', '.join(skill_strs)}")

    # Experience History
    experience = profile.get("experience", [])
    if experience:
        lines.append("\nWork Experience:")
        for exp in experience:
            title = exp.get("title") or "Position"
            company = exp.get("company") or "Unknown Company"
            start = exp.get("start") or "N/A"
            end = exp.get("end") or "Present"
            summary = exp.get("summary")
            
            exp_header = f"- {title} at {company} ({start} to {end})"
            lines.append(exp_header)
            if summary:
                # Indent summary lines
                indented_summary = "\n".join(f"  {line}" for line in summary.strip().splitlines())
                lines.append(indented_summary)

    # Education History
    education = profile.get("education", [])
    if education:
        lines.append("\nEducation:")
        for edu in education:
            inst = edu.get("institution") or "Unknown Institution"
            deg = edu.get("degree") or "Degree"
            field_name = edu.get("field")
            end_year = edu.get("end_year")
            
            edu_str = f"- {deg}"
            if field_name:
                edu_str += f" in {field_name}"
            edu_str += f" from {inst}"
            if end_year:
                edu_str += f" (Graduated: {end_year})"
            lines.append(edu_str)

    return "\n".join(lines)
