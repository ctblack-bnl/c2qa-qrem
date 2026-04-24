# ingester/pipeline_ingest.py
# Main pipeline for the publications ingester.
# Reads PDFs from a specified directory, calls Claude to extract structured
# materials characterization data, and writes records to a JSONL ledger.
#
# Two-pass design per paper:
#   Pass 1 — Relevance check: is this paper worth ingesting?
#   Pass 2 — Full extraction: extract all structured data (only if relevant)
#
# Usage:
#   cd ingester
#   python3 pipeline_ingest.py --papers-dir ../data/papers --out ../data/ingested/records.jsonl
#
# Key design principles (same as SEM pipeline):
#   - Append-only JSONL ledger
#   - Idempotent: already-processed papers are skipped
#   - AI proposes, humans approve
#   - Every extracted value has confidence + source reference
#   - Never invent values — not_extracted is always valid

import json
import time
import traceback
import base64
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import get_deployment_name
from json_utils import safe_json_dumps
from openai_client import make_client
from io_jsonl import append_jsonl
from processed_ledger import (
    load_ledger, save_ledger,
    is_already_processed, record_processed
)
from prompts import RELEVANCE_PROMPT, build_extraction_prompt


# ---------------------------------------------------------------------------
# PDF discovery
# ---------------------------------------------------------------------------

def find_all_pdfs(papers_dir: Path) -> list:
    """Recursively find all PDF files under papers_dir."""
    return sorted([
        p for p in papers_dir.rglob("*.pdf")
        if p.is_file()
    ])


# ---------------------------------------------------------------------------
# PDF → base64
# ---------------------------------------------------------------------------

def pdf_to_base64(pdf_path: Path) -> str:
    """Read a PDF file and return it as a base64-encoded string."""
    with open(pdf_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Claude API calls
# ---------------------------------------------------------------------------

def call_relevance_check(client: Any, deployment: str, pdf_b64: str) -> dict:
    """
    Pass 1: Ask Claude if this paper is relevant and what type it is.
    Returns parsed JSON dict from Claude's response.
    """
    response = client.chat.completions.create(
        model=deployment,
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": RELEVANCE_PROMPT
                    },
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        }
                    }
                ]
            }
        ]
    )
    raw = response.choices[0].message.content
    return raw


def call_extraction(client: Any, deployment: str,
                    pdf_b64: str, relevance: str, paper_type: str) -> str:
    """
    Pass 2: Full structured extraction with streaming progress output.
    Only called for high and medium relevance papers.
    Returns raw string response from Claude.
    """
    prompt = build_extraction_prompt(relevance, paper_type)

    print("  Streaming extraction (tokens will appear below):", flush=True)
    print("  " + "-"*40, flush=True)

    # Use the underlying Anthropic client directly for streaming
    from anthropic import AnthropicFoundry
    from config import get_api_key, get_azure_base_url, get_deployment_name

    anthropic_client = AnthropicFoundry(
        api_key  = get_api_key(),
        base_url = get_azure_base_url(),
    )

    text_content = ""
    with anthropic_client.messages.stream(
        model      = deployment,
        max_tokens = 16000,
        messages   = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "document",
                        "source": {
                            "type":       "base64",
                            "media_type": "application/pdf",
                            "data":       pdf_b64,
                        }
                    }
                ]
            }
        ]
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            text_content += text

    print("\n  " + "-"*40, flush=True)
    return text_content


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

def extract_json(raw: str) -> Optional[dict]:
    """
    Extract and parse a JSON object from Claude's response.
    Handles cases where Claude wraps JSON in markdown code fences.
    """
    if not raw:
        return None

    # Strip markdown code fences if present
    text = raw.strip()

    # Remove opening fence (```json or ```)
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1:].strip()

    # Remove closing fence (```)
    if text.endswith("```"):
        text = text[:-3].strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find the first { and last } and parse between them
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_ingestion(
    papers_dir: Path,
    out_path: Path,
    ledger_path: Path,
) -> None:
    print("=== publications ingester starting ===", flush=True)

    # --- Setup ---
    client     = make_client()
    deployment = get_deployment_name()
    print(f"Deployment: {deployment}", flush=True)

    # --- Load processed ledger ---
    ledger = load_ledger(ledger_path)
    already_done = len(ledger.get("processed", []))
    print(f"Already processed: {already_done} papers", flush=True)

    # --- Find all PDFs ---
    pdf_paths = find_all_pdfs(papers_dir)
    total = len(pdf_paths)
    print(f"Found {total} PDF(s) in {papers_dir.resolve()}", flush=True)

    if total == 0:
        print("No PDFs found. Drop papers into the papers directory and try again.")
        return

    success = failed = skipped = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for i, pdf_path in enumerate(pdf_paths, start=1):
        filename = pdf_path.name
        print("=" * 60, flush=True)
        print(f"[{i}/{total}] {filename}", flush=True)

        # --- Check if already processed ---
        if is_already_processed(ledger, filename):
            print(f"  Skipping — already in processed ledger.", flush=True)
            skipped += 1
            continue

        # --- Load PDF ---
        try:
            pdf_b64 = pdf_to_base64(pdf_path)
            print(f"  PDF loaded ({len(pdf_b64) // 1024} KB base64)", flush=True)
        except Exception as e:
            print(f"  ERROR loading PDF: {e}", flush=True)
            failed += 1
            continue

        # ---------------------------------------------------------------
        # PASS 1 — Relevance check
        # ---------------------------------------------------------------
        print("  Pass 1: relevance check...", flush=True)
        relevance_raw  = None
        relevance_json = None
        relevance_err  = None

        try:
            start = time.time()
            relevance_raw = call_relevance_check(client, deployment, pdf_b64)
            elapsed = time.time() - start
            print(f"  Relevance check done in {elapsed:.1f}s", flush=True)
            print(f"  Raw (first 200 chars): {(relevance_raw or '')[:200]}", flush=True)

            relevance_json = extract_json(relevance_raw)
            if not relevance_json:
                raise ValueError("Could not parse relevance JSON from response")

        except Exception as e:
            relevance_err = {"type": type(e).__name__, "message": str(e)}
            print(f"  Relevance check FAILED: {e}", flush=True)

        # If relevance check failed entirely, log and move on
        if relevance_err or not relevance_json:
            record = {
                "filename":        filename,
                "processed_at":    datetime.now().isoformat(timespec="seconds"),
                "pass":            "relevance_check",
                "error":           relevance_err,
                "relevance_raw":   relevance_raw,
            }
            append_jsonl(out_path, record)
            record_processed(ledger, filename, outcome="failed",
                             reason="relevance check error")
            save_ledger(ledger, ledger_path)
            failed += 1
            continue

        # --- Read relevance decision ---
        relevance    = relevance_json.get("relevance", "low").lower()
        paper_type   = relevance_json.get("paper_type", "unclear").lower()
        doi          = relevance_json.get("doi")
        skip         = relevance_json.get("skip", True)
        skip_reason  = relevance_json.get("relevance_reason", "")

        print(f"  Relevance: {relevance} | Type: {paper_type} | DOI: {doi}", flush=True)

        # --- Skip low relevance papers ---
        if relevance == "low" or skip is True or str(skip).lower() == "true":
            print(f"  Skipping — low relevance: {skip_reason}", flush=True)
            record = {
                "filename":        filename,
                "processed_at":    datetime.now().isoformat(timespec="seconds"),
                "pass":            "relevance_check",
                "outcome":         "skipped",
                "relevance":       relevance,
                "relevance_reason": skip_reason,
                "doi":             doi,
                "title":           relevance_json.get("title"),
                "authors":         relevance_json.get("authors"),
                "relevance_raw":   relevance_raw,
                "relevance_json":  relevance_json,
                "extraction_raw":  None,
                "extraction_json": None,
                "error":           None,
            }
            append_jsonl(out_path, record)
            record_processed(ledger, filename, outcome="skipped",
                             doi=doi, reason=skip_reason)
            save_ledger(ledger, ledger_path)
            skipped += 1
            continue

        # ---------------------------------------------------------------
        # PASS 2 — Full extraction
        # ---------------------------------------------------------------
        print(f"  Pass 2: full extraction (type={paper_type})...", flush=True)
        extraction_raw  = None
        extraction_json = None
        extraction_err  = None

        try:
            start = time.time()
            extraction_raw = call_extraction(
                client, deployment, pdf_b64, relevance, paper_type
            )
            elapsed = time.time() - start
            print(f"  Extraction done in {elapsed:.1f}s", flush=True)
            print(f"  Raw (first 200 chars): {(extraction_raw or '')[:200]}", flush=True)

            extraction_json = extract_json(extraction_raw)
            if not extraction_json:
                raise ValueError("Could not parse extraction JSON from response")

        except Exception as e:
            extraction_err = {"type": type(e).__name__, "message": str(e)}
            print(f"  Extraction FAILED: {e}", flush=True)

        # --- Build and write the full record ---
        record_ids = []  # future: generate IDs from center + date + seq

        record = {
            "filename":         filename,
            "processed_at":     datetime.now().isoformat(timespec="seconds"),
            "pass":             "extraction",
            "outcome":          "ingested" if not extraction_err else "failed",
            "relevance":        relevance,
            "relevance_reason": skip_reason,
            "doi":              doi,
            "title":            relevance_json.get("title"),
            "authors":          relevance_json.get("authors"),
            "journal":          relevance_json.get("journal_or_preprint"),
            "paper_type":       paper_type,
            "relevance_raw":    relevance_raw,
            "relevance_json":   relevance_json,
            "extraction_raw":   extraction_raw,
            "extraction_json":  extraction_json,
            "error":            extraction_err,
            "human_reviewed":   False,   # all records start as unreviewed
            "human_approved":   False,
        }

        try:
            append_jsonl(out_path, record)
            print("  Record written to JSONL.", flush=True)
        except Exception as e:
            print(f"  WRITE FAILED: {e}", flush=True)
            traceback.print_exc()
            failed += 1
            continue

        if not extraction_err:
            record_processed(ledger, filename, outcome="ingested",
                             doi=doi, record_ids=record_ids)
            success += 1
            print(f"  [{i}/{total}] Done [OK]", flush=True)
        else:
            record_processed(ledger, filename, outcome="failed",
                             doi=doi, reason=str(extraction_err))
            failed += 1
            print(f"  [{i}/{total}] Done [FAILED — extraction error]", flush=True)

        save_ledger(ledger, ledger_path)

    print("=" * 60, flush=True)
    print("\n=== SUMMARY ===", flush=True)
    print(f"  Success : {success}", flush=True)
    print(f"  Failed  : {failed}", flush=True)
    print(f"  Skipped : {skipped}", flush=True)
    print("=== all done ===", flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest scientific publications into the materials characterization database."
    )
    parser.add_argument(
        "--papers-dir",
        type=Path,
        default=Path("../data/papers"),
        help="Directory containing PDF files to ingest (default: ../data/papers)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("../data/ingested/records.jsonl"),
        help="Output JSONL file path (default: ../data/ingested/records.jsonl)"
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("../data/ingested/processed_ledger.json"),
        help="Processed papers ledger path (default: ../data/ingested/processed_ledger.json)"
    )
    args = parser.parse_args()

    run_ingestion(
        papers_dir=args.papers_dir,
        out_path=args.out,
        ledger_path=args.ledger,
    )
