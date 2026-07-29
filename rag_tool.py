#!/usr/bin/env python3
"""
rag_tool.py - CLI tool for candidate semantic search & query chatbot (RAG)

Examples:
  # Build index from the pipeline output JSON:
  python rag_tool.py --index output/result.json

  # Run a query:
  python rag_tool.py --query "Which candidates have Go experience and are located in San Francisco?"

  # Start the interactive chat agent:
  python rag_tool.py --interactive
"""
import argparse
import json
import os
import sys
import logging

from pipeline.rag import VectorStore, query_rag, get_api_key

# Set up clean output styling
def print_separator():
    print("=" * 70)

def print_section(title: str):
    print("\n" + f" {title} ".center(70, "-"))

def main():
    parser = argparse.ArgumentParser(
        prog="rag_tool.py",
        description="RAG Search and QA Chatbot Tool for Canonical Candidate Profiles",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--index",
        metavar="JSON_FILE",
        help="Path to pipeline canonical JSON result file to build/update the index"
    )
    group.add_argument(
        "--query",
        metavar="QUERY_STRING",
        help="Run a semantic search and generate a response using the database context"
    )
    group.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Start an interactive chatbot session to query the candidate database"
    )
    
    parser.add_argument(
        "--db",
        default="output/rag_index.json",
        help="Path to the vector store index file (default: output/rag_index.json)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=3,
        help="Max candidates to retrieve as context (default: 3)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable detailed logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    # 1. Indexing Mode
    if args.index:
        if not os.path.isfile(args.index):
            print(f"ERROR: File not found: '{args.index}'", file=sys.stderr)
            sys.exit(1)

        try:
            with open(args.index, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"ERROR: Failed to parse candidate JSON file: {e}", file=sys.stderr)
            sys.exit(1)

        # Candidate output could be a list of profiles or a single profile
        if isinstance(data, dict):
            profiles = [data]
        elif isinstance(data, list):
            profiles = data
        else:
            print("ERROR: Invalid format. Output JSON must be a dict or a list of dicts.", file=sys.stderr)
            sys.exit(1)

        api_key = get_api_key()
        if not api_key:
            print("WARNING: GEMINI_API_KEY environment variable is not set.")
            print("   The tool will run in MOCK MODE, generating mock embedding vectors.")
            print("   To use real Google Gemini embeddings, please run: set GEMINI_API_KEY=your_key_here")
            print_separator()

        print(f"Indexing {len(profiles)} candidates into '{args.db}'...")
        store = VectorStore(index_path=args.db)
        store.index_candidates(profiles, rebuild=True)
        print("[OK] Indexing completed successfully.")
        sys.exit(0)

    # Validate index exists for query/interactive modes
    if not os.path.exists(args.db):
        print(f"ERROR: Index file '{args.db}' does not exist.", file=sys.stderr)
        print("Please build the index first using: python rag_tool.py --index <canonical_output.json>", file=sys.stderr)
        sys.exit(1)

    # Check API key for LLM mode
    api_key = get_api_key()
    if not api_key:
        print("WARNING: Running in MOCK RAG mode (GEMINI_API_KEY environment variable is not set).")
        print("   Retrieve queries will use mock embeddings and local heuristic answers.")
        print("   For standard RAG, set GEMINI_API_KEY environment variable.")
        print_separator()

    # 2. Single Query Mode
    if args.query:
        print(f"Querying: '{args.query}'...\n")
        res = query_rag(args.query, index_path=args.db, limit=args.limit)
        
        print_section("RETRIEVED CANDIDATES")
        for idx, cand in enumerate(res["retrieved_candidates"]):
            print(f"#{idx+1} {cand['full_name']} (Similarity: {cand['score']:.4f})")
            print(f"   Emails: {', '.join(cand['emails'])}")
            
        print_section("GENERATED ANSWER")
        print(res["answer"])
        print_separator()
        sys.exit(0)

    # 3. Interactive chatbot mode
    if args.interactive:
        print_separator()
        print("Eightfold Candidate Transformer RAG Chatbot".center(70))
        print("Type your questions about candidates below. Type 'exit' or 'quit' to stop.")
        print_separator()
        
        while True:
            try:
                query = input("\nQuery > ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break
                
            if not query:
                continue
                
            if query.lower() in ("exit", "quit"):
                print("Goodbye!")
                break
                
            print("\nSearching database and generating response...")
            res = query_rag(query, index_path=args.db, limit=args.limit)
            
            print_section("RETRIEVED CANDIDATES")
            for idx, cand in enumerate(res["retrieved_candidates"]):
                print(f"#{idx+1} {cand['full_name']} (Similarity: {cand['score']:.4f}) - {', '.join(cand['emails'])}")
                
            print_section("ANSWER")
            print(res["answer"])
            print_separator()

if __name__ == "__main__":
    main()
