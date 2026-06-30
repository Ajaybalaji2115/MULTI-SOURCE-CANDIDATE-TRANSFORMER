import os
import sys
import subprocess

# Ensure reportlab is installed
try:
    import reportlab
except ImportError:
    print("Installing reportlab...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab"])

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_pdf():
    pdf_filename = "Ajay_Balaji_ajay.balaji@gmail.com_Eightfold.pdf"
    
    # 0.5 inch margins (36 points) to ensure it fits on exactly one page
    doc = SimpleDocTemplate(
        pdf_filename,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=15,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1, # Center
        spaceAfter=3
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8.5,
        leading=10,
        textColor=colors.HexColor('#4B5563'),
        alignment=1, # Center
        spaceAfter=10
    )
    
    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=11,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=6,
        spaceAfter=3,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=10.5,
        textColor=colors.HexColor('#1F2937'),
        spaceAfter=3
    )
    
    bullet_style = ParagraphStyle(
        'BulletText',
        parent=body_style,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=2
    )
    
    story = []
    
    # Title
    story.append(Paragraph("Eightfold Engineering Intern Assignment: Technical Design", title_style))
    story.append(Paragraph("Candidate: Ajay Balaji | Email: ajay.balaji@gmail.com | Role: Multi-Source Candidate Data Transformer", subtitle_style))
    
    # Section 1: Pipeline Architecture
    story.append(Paragraph("1. Pipeline Architecture", section_heading))
    arch_text = (
        "The pipeline is designed as a modular, deterministic, and explainable data flow that transforms heterogeneous, "
        "messy candidate records into structured, canonical profiles. The stages are executed in the following sequence:"
    )
    story.append(Paragraph(arch_text, body_style))
    
    steps = [
        "<b>1. Ingest & Route (Detect):</b> Identifies source types (CSV, ATS JSON, LinkedIn JSON, Resume PDF/DOCX/TXT) using file extension, MIME, or URL pattern heuristics.",
        "<b>2. Extract & Pre-normalize:</b> Extractor classes parse raw content and emit <code>RawField</code> evidence objects. Initial normalization (e.g., E.164 phone parsing, YYYY-MM date parsing, ISO-3166-1 country lookup, and canonical skill mapping) is performed during extraction.",
        "<b>3. Candidate Grouping (Clustering):</b> Groups <code>RawField</code>s into clusters using a Union-Find (Disjoint Set) algorithm. Records are matched if they share a normalized email, a normalized phone, or a normalized name and a social link (GitHub/LinkedIn).",
        "<b>4. Merge & Conflict Resolution:</b> Consolidates raw fields in each cluster into a single <code>CanonicalProfile</code> using a completeness-first policy and calculates an overall confidence score.",
        "<b>5. Validate (Canonical):</b> Mutates fixable fields and verifies the profile against the <code>CANONICAL_JSON_SCHEMA</code>.",
        "<b>6. Project:</b> Transforms the canonical profile into the desired output schema based on a runtime <code>config.json</code>.",
        "<b>7. Validate Output & Emit:</b> Verifies required fields in the projected output and handles missing fields (null/omit/error)."
    ]
    for step in steps:
        story.append(Paragraph(f"• {step}", bullet_style))
        
    # Section 2: Merge & Conflict Resolution Policy
    story.append(Paragraph("2. Merge & Conflict Resolution Policy", section_heading))
    merge_text = (
        "When multiple sources supply competing values for the same candidate field, the pipeline resolves conflicts deterministically:"
    )
    story.append(Paragraph(merge_text, body_style))
    
    merge_rules = [
        "<b>Completeness-First:</b> Evaluates value richness using a completeness score (e.g., longer/richer strings and filled objects score higher). For example, <code>'Ajay Balaji'</code> (score 0.11) wins over <code>'Ajay B.'</code> (score 0.07).",
        "<b>Confidence Tiebreaker:</b> If completeness scores are equal, the value from the source with the higher base confidence wins (CSV: 0.90, ATS: 0.85, GitHub: 0.75, LinkedIn: 0.70, Resume: 0.65, Notes: 0.60).",
        "<b>Source Type Priority:</b> If a tie still exists, structured sources (CSV/ATS) are prioritized over unstructured sources.",
        "<b>Agreement Bonus:</b> Boosts confidence by +0.05 for each additional source that provides the same normalized value (capped at 1.0).",
        "<b>Array Fields:</b> Fields like <code>emails</code>, <code>phones</code>, and <code>skills</code> are merged via a union operation, deduplicated, and sorted by confidence descending. Skills are mapped to canonical names using an alias lookup table."
    ]
    for rule in merge_rules:
        story.append(Paragraph(f"• {rule}", bullet_style))
        
    # Section 3: Runtime Custom-Output Config (Projection Layer)
    story.append(Paragraph("3. Runtime Custom-Output Config (Projection Layer)", section_heading))
    proj_text = (
        "The projection layer reshapes the internal <code>CanonicalProfile</code> into the final output without changing any engine code. "
        "The runtime config.json supports:"
    )
    story.append(Paragraph(proj_text, body_style))
    
    proj_features = [
        "<b>Field Selection & Renaming:</b> Projects a subset of fields and maps them using the <code>'from'</code> key (e.g., mapping <code>emails[0]</code> to <code>primary_email</code> or <code>skills[].name</code> to a flat string list).",
        "<b>Per-Field Renormalization:</b> Applies additional normalization during projection (e.g., <code>E164</code> for phones, <code>canonical</code> for skills, or <code>iso3166</code> for countries).",
        "<b>Metadata Toggles:</b> Top-level <code>include_confidence</code> and <code>include_provenance</code> booleans toggle the inclusion of confidence scores and the detailed provenance array.",
        "<b>Missing Value Handling:</b> The <code>on_missing</code> key dictates behavior when a required field is null or missing: <code>'null'</code> (inject null), <code>'omit'</code> (exclude field), or <code>'error'</code> (raise a blocking <code>ValueError</code>)."
    ]
    for feat in proj_features:
        story.append(Paragraph(f"• {feat}", bullet_style))
        
    # Section 4: Edge Cases Handled
    story.append(Paragraph("4. Edge Cases Handled", section_heading))
    
    edge_cases = [
        "<b>Garbage/Malformed Sources:</b> Catching file read and parsing exceptions. Malformed rows/objects degrade gracefully by skipping bad records rather than crashing the pipeline.",
        "<b>Date & Year Validation:</b> Ensures experience start dates do not exceed end dates (nulling the end date and raising a warning if they do). Validates that education graduation years are numeric.",
        "<b>No Reliable Identifiers:</b> If a candidate lacks emails, phones, and social links, the pipeline falls back to generating a random <code>UUID4</code> for the <code>candidate_id</code>, flagging it in the provenance with a low confidence score (0.1).",
        "<b>Scale & Batching:</b> The Union-Find grouping algorithm allows thousands of candidate records across massive files to be clustered and processed in parallel, maintaining high throughput and memory efficiency."
    ]
    for case in edge_cases:
        story.append(Paragraph(f"• {case}", bullet_style))
        
    doc.build(story)
    print(f"Successfully generated PDF: {pdf_filename}")

if __name__ == "__main__":
    generate_pdf()
