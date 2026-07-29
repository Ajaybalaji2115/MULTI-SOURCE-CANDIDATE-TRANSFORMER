#!/usr/bin/env python3
"""
main.py — CLI entry point for the Eightfold Candidate Data Transformer

Usage examples:
  # Full canonical output (default schema)
  python main.py --inputs data/sample_recruiter.csv data/sample_ats.json

  # With GitHub profile
  python main.py --inputs data/sample_recruiter.csv --github-url https://github.com/torvalds

  # Custom projected output
  python main.py --inputs data/sample_recruiter.csv data/sample_ats.json \\
                 --github-url https://github.com/Ajaybalaji2115 \\
                 --config configs/custom_config.json \\
                 --output result.json

  # Verbose logging
  python main.py --inputs data/sample_ats.json --verbose

  # Multiple file types
  python main.py --inputs data/sample_recruiter.csv \\
                           data/sample_ats.json \\
                           data/sample_resume.txt \\
                           data/sample_linkedin_export.json \\
                 --github-url https://github.com/Ajaybalaji2115 \\
                 --config configs/custom_config.json \\
                 --output output/result.json \\
                 --verbose
"""
import argparse
import json
import os
import sys

from pipeline.pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Eightfold Multi-Source Candidate Data Transformer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--inputs", "-i",
        nargs="+",
        metavar="FILE",
        default=[],
        help="One or more input files: CSV, JSON (ATS or LinkedIn), PDF, DOCX, or TXT",
    )
    parser.add_argument(
        "--github-url", "-g",
        metavar="URL",
        default=None,
        help="GitHub profile URL or username (e.g. https://github.com/torvalds or torvalds)",
    )
    parser.add_argument(
        "--config", "-c",
        metavar="CONFIG_JSON",
        default=None,
        help="Path to projection config JSON (default: configs/default_config.json)",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="OUTPUT_JSON",
        default=None,
        help="Write output JSON to this file (default: print to stdout)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable verbose logging",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.inputs and not args.github_url:
        print("ERROR: Provide at least one --inputs file or --github-url.", file=sys.stderr)
        sys.exit(1)

    # Validate input files exist
    for f in args.inputs:
        if not os.path.isfile(f):
            print(f"ERROR: Input file not found: '{f}'", file=sys.stderr)
            sys.exit(1)

    result = run_pipeline(
        inputs=args.inputs,
        github_url=args.github_url,
        config_path=args.config,
        verbose=args.verbose,
    )

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(output_json)
        print(f"[OK] Output written to: {args.output}")
        print(f"Total candidates processed: {len(result)}")
        for idx, cand in enumerate(result):
            name = cand.get("full_name") or cand.get("primary_email") or "Unknown"
            print(f"  Candidate #{idx+1}: {name}")
            print(f"    candidate_id       : {cand.get('candidate_id', 'N/A')}")
            print(f"    overall_confidence : {cand.get('overall_confidence', 'N/A')}")
            meta = cand.get("_pipeline_meta", {})
            print(f"    raw fields found   : {meta.get('raw_fields_extracted', '?')}")
            warns = meta.get("validation_warnings", [])
            errs  = meta.get("validation_errors",   [])
            if warns:
                print(f"    warnings           : {len(warns)}")
                for w in warns:
                    print(f"      [WARN] {w}")
            if errs:
                print(f"    errors             : {len(errs)}")
                for e in errs:
                    print(f"      [FAIL] {e}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
