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
import hashlib
import uuid
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

from prompts import (
    RELEVANCE_PROMPT, build_extraction_prompt, build_profile_prompt,
    SCHEMA_VERSION, EXTRACTION_PROMPT_VERSION,
)


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
# PDF → base64 + sha256 (single read — version lineage stamps, Phase 4 item #5)
# ---------------------------------------------------------------------------

def load_pdf(pdf_path: Path) -> tuple:
    """
    Read a PDF file once and return (base64_string, sha256_hex).
    Replaces the old pdf_to_base64() — folded the hash in here rather than
    reading the file a second time, since nothing else in this codebase
    was found to import pdf_to_base64 directly.
    """
    raw = pdf_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("utf-8")
    sha256_hex = hashlib.sha256(raw).hexdigest()
    return b64, sha256_hex


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
        # 64000 -> 128000 (Aug 14 2026): Bland 2025 (~59 samples) hit the old
        # 64000 ceiling and got silently truncated mid-JSON, confirmed by
        # inspecting the raw response — it ended cleanly mid-object, no
        # exception, the signature of a max_tokens cutoff rather than a
        # network failure. Schema growth since the original "Bland only
        # fails at Pass 3" observation (fabrication_group_id, T2_unspecified_us,
        # junction fields, R-vs-T fields, Qi measurement context, etc. all
        # added since) is the likely reason this wasn't a problem before.
        # 128000 is Anthropic's documented ceiling for some Sonnet 4.6
        # configurations, though docs are inconsistent about whether a beta
        # header is required for this deployment — if the API rejects this
        # value outright, that error will state the real ceiling directly,
        # which is more informative than another silent truncation.
        max_tokens = 128000,
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

def call_profile_generation(client: Any, deployment: str, samples: list,
                             chunk_size: int = 15) -> dict:
    """
    Pass 3: Generate similarity profiles for all samples in the extracted record.
    Returns a dict keyed by sample_id.

    Processes samples in chunks (chunk_size per call) rather than all in one
    call. The profile schema is verbose enough per sample — 10 fields
    including a free-text profile_notes and three list-valued fields — that
    a single-call request for a large paper can exceed the response token
    budget. This happened consistently for Bland 2025 (57+ samples) before
    this fix (Aug 14 2026): the old single-call design, capped at
    max_tokens=4000, needed roughly 7,400+ tokens for that many profiles —
    the response got silently truncated mid-JSON, producing invalid JSON
    that failed to parse, which failed Pass 3 for the entire paper even
    though most individual profiles would have generated correctly on their
    own. Each chunk now fails independently: a failure partway through a
    large paper loses only that chunk's profiles, not every profile
    generated so far, which is a real behavior change from the old
    all-or-nothing failure mode — previously any exception here zeroed out
    similarity_profiles for the whole paper.
    """
    if not samples:
        return {}

    n_chunks = (len(samples) + chunk_size - 1) // chunk_size
    result = {}
    for chunk_num, i in enumerate(range(0, len(samples), chunk_size), start=1):
        chunk = samples[i:i + chunk_size]
        print(f"    Pass 3 chunk {chunk_num}/{n_chunks} "
              f"({len(chunk)} sample(s))...", flush=True)
        try:
            prompt = build_profile_prompt(chunk)

            response = client.chat.completions.create(
                model=deployment,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.choices[0].message.content.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

            profiles_list = json.loads(raw)
            if not isinstance(profiles_list, list):
                raise ValueError(f"Expected JSON array, got {type(profiles_list)}")

            for p in profiles_list:
                sid = p.get("sample_id")
                if not sid:
                    print(f"    WARNING: profile missing sample_id, skipping entry", flush=True)
                    continue
                p["profile_version"] = "1.0"
                result[sid] = p

            print(f"    Pass 3 chunk {chunk_num}/{n_chunks} done — "
                  f"{len(profiles_list)} profile(s)", flush=True)

        except Exception as e:
            chunk_ids = [s.get("sample_id", "unknown") for s in chunk]
            print(f"    Pass 3 chunk {chunk_num}/{n_chunks} FAILED (non-fatal, "
                  f"continuing with remaining chunks): {e}", flush=True)
            print(f"      samples lost from this chunk: {chunk_ids}", flush=True)
            continue

    return result

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

def load_dedup_skip_filenames(out_path: Path) -> set:
    """
    Load the set of filenames that should be skipped entirely because a
    human has already recorded a deduplication decision for them (the
    "losing" side of an arXiv-preprint/published-version pair).

    Mirrors build_sqlite.py's dedup-parsing logic exactly (same
    deduplication.json schema: a "decisions" list, each with "decision",
    "paper_a", "paper_b", "keep") — this is deliberately the same file
    build_sqlite.py already reads, not a separate mechanism.

    Added Aug 2026 to fix a recurring annoyance: neither normal ingestion
    nor --relevance-only mode previously consulted deduplication.json at
    all, so every triage/test pass re-processed both the arXiv and
    published version of an already-deduplicated paper every time, with
    the losing copy's relevance count inflating totals for no reason.

    Deliberately scoped to deduplication.json ONLY, not exclusions.json.
    Exclusions need to stay fully re-checkable at Pass 1 — that's exactly
    what let the Aug 6 relevance-gate dry run confirm Hays/Delord/WangX
    are independently excluded under the new gate, not just carried over
    from the old one. A dedup decision carries no such question — the
    losing paper's fate was never about relevance, so re-checking it has
    no informational value, only repeated cost.
    """
    dedup_path = out_path.parent / "deduplication.json"
    skip_filenames = set()
    if not dedup_path.exists():
        return skip_filenames
    try:
        dedup = json.loads(dedup_path.read_text())
        for decision in dedup.get("decisions", []):
            if decision.get("decision") == "duplicate":
                keep = decision.get("keep")
                paper_a = decision.get("paper_a")
                paper_b = decision.get("paper_b")
                if keep == paper_a:
                    skip_filenames.add(paper_b)
                elif keep == paper_b:
                    skip_filenames.add(paper_a)
    except Exception as e:
        print(f"  Warning: could not load deduplication.json: {e}", flush=True)
    return skip_filenames


def run_ingestion(
    papers_dir: Path,
    out_path: Path,
    ledger_path: Path,
    relevance_only: bool = False,
    report_out: Path = None,
) -> None:
    print("=== publications ingester starting ===", flush=True)
    if relevance_only:
        print("=== RELEVANCE-ONLY MODE — Pass 1 only, ledger untouched, Pass 2/3 skipped ===", flush=True)

    # --- Setup ---
    client     = make_client()
    deployment = get_deployment_name()
    print(f"Deployment: {deployment}", flush=True)

    # --- Version lineage stamps (Phase 4 item #5) ---
    # model_identifier: the configured deployment name (not the actual served
    # model string from the API response — simpler, single source for all
    # three passes, at the cost of not catching a silent Azure-side alias
    # repoint). ingestion_batch_id: one ID per run_ingestion() call, stamped
    # on every record this run produces (including failed/skipped ones).
    model_identifier   = deployment
    ingestion_batch_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    print(f"Ingestion batch ID: {ingestion_batch_id}", flush=True)

    # --- Load processed ledger ---
    ledger = load_ledger(ledger_path)
    already_done = len(ledger.get("processed", []))
    print(f"Already processed: {already_done} papers", flush=True)

    # --- Load deduplication skip list (applies in ALL modes, including
    # --relevance-only — a known-duplicate file's fate was never about
    # relevance, so re-checking it has no informational value) ---
    dedup_skip_filenames = load_dedup_skip_filenames(out_path)
    if dedup_skip_filenames:
        print(f"Deduplication: will skip {len(dedup_skip_filenames)} "
              f"known-duplicate file(s): {dedup_skip_filenames}", flush=True)

    # --- Find all PDFs ---
    pdf_paths = find_all_pdfs(papers_dir)
    total = len(pdf_paths)
    print(f"Found {total} PDF(s) in {papers_dir.resolve()}", flush=True)

    if total == 0:
        print("No PDFs found. Drop papers into the papers directory and try again.")
        return

    success = failed = skipped = classified = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for i, pdf_path in enumerate(pdf_paths, start=1):
        filename = pdf_path.name
        print("=" * 60, flush=True)
        print(f"[{i}/{total}] {filename}", flush=True)

        # --- Check deduplication decisions FIRST — applies in both normal
        # and --relevance-only mode, regardless of ledger status. A known
        # duplicate is skipped unconditionally; there's nothing to
        # re-verify here the way there is for exclusions. ---
        if filename in dedup_skip_filenames:
            print(f"  Skipping — known duplicate per deduplication.json.", flush=True)
            skipped += 1
            continue

        # --- Check if already processed (skipped entirely in relevance-only
        # mode — we need to re-check papers already in the corpus, and this
        # mode never reads or writes the ledger anyway) ---
        if not relevance_only and is_already_processed(ledger, filename):
            print(f"  Skipping — already in processed ledger.", flush=True)
            skipped += 1
            continue

        # --- Load PDF ---
        try:
            pdf_b64, source_pdf_sha256 = load_pdf(pdf_path)
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

        # -----------------------------------------------------------------
        # RELEVANCE-ONLY MODE — write a lightweight report row and move on.
        # Never touches out_path or the processed ledger — this is purely
        # for validating a relevance-gate change against the existing
        # papers folder (including already-ingested papers) without
        # incurring Pass 2/3 cost or affecting real ingestion state.
        # -----------------------------------------------------------------
        if relevance_only:
            report_row = {
                "filename":              filename,
                "checked_at":            datetime.now().isoformat(timespec="seconds"),
                "relevance":             (relevance_json or {}).get("relevance"),
                "relevance_reason":      (relevance_json or {}).get("relevance_reason"),
                "funding_acknowledgments": (relevance_json or {}).get("funding_acknowledgments"),
                "paper_type":            (relevance_json or {}).get("paper_type"),
                "doi":                   (relevance_json or {}).get("doi"),
                "title":                 (relevance_json or {}).get("title"),
                "error":                 relevance_err,
            }
            append_jsonl(report_out, report_row)
            classified += 1
            print(f"  [{i}/{total}] relevance={report_row['relevance']} "
                  f"funding={report_row['funding_acknowledgments']} "
                  f"(report row written, ledger untouched)", flush=True)
            continue

        # If relevance check failed entirely, log and move on
        if relevance_err or not relevance_json:
            record = {
                "filename":        filename,
                "processed_at":    datetime.now().isoformat(timespec="seconds"),
                "pass":            "relevance_check",
                "error":           relevance_err,
                "relevance_raw":   relevance_raw,
                "schema_version":            SCHEMA_VERSION,
                "extraction_prompt_version": EXTRACTION_PROMPT_VERSION,
                "model_identifier":          model_identifier,
                "ingestion_batch_id":        ingestion_batch_id,
                "source_pdf_sha256":         source_pdf_sha256,
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
                "schema_version":            SCHEMA_VERSION,
                "extraction_prompt_version": EXTRACTION_PROMPT_VERSION,
                "model_identifier":          model_identifier,
                "ingestion_batch_id":        ingestion_batch_id,
                "source_pdf_sha256":         source_pdf_sha256,
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
            "schema_version":            SCHEMA_VERSION,
            "extraction_prompt_version": EXTRACTION_PROMPT_VERSION,
            "model_identifier":          model_identifier,
            "ingestion_batch_id":        ingestion_batch_id,
            "source_pdf_sha256":         source_pdf_sha256,
        }

        # ---------------------------------------------------------------
        # PASS 3 — Similarity profile generation (only if extraction succeeded)
        # ---------------------------------------------------------------
        if not extraction_err and extraction_json:
            samples = extraction_json.get("samples", [])
            if samples:
                print(f"  Pass 3: generating similarity profiles for {len(samples)} sample(s)...", flush=True)
                try:
                    start = time.time()
                    profiles = call_profile_generation(client, deployment, samples)
                    elapsed = time.time() - start
                    print(f"  Profile generation done in {elapsed:.1f}s — {len(profiles)} profile(s)", flush=True)
                    record["similarity_profiles"] = profiles
                except Exception as e:
                    print(f"  Pass 3 FAILED (non-fatal): {e}", flush=True)
                    record["similarity_profiles"] = {}
            else:
                record["similarity_profiles"] = {}

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
    if relevance_only:
        print(f"  Classified: {classified} paper(s), report written to {report_out}", flush=True)
        print(f"  Skipped (dedup): {skipped}", flush=True)
        print(f"  PDF load errors: {failed}", flush=True)
    else:
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
    parser.add_argument(
        "--relevance-only",
        action="store_true",
        help=(
            "Run Pass 1 (relevance check) only, against every PDF in "
            "--papers-dir including already-ingested ones. Never reads or "
            "writes the processed ledger, never runs Pass 2/3. Writes a "
            "lightweight classification report to --report-out. Use this "
            "to validate a relevance-gate / prompts.py change against the "
            "existing corpus without the cost of full re-extraction."
        )
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("../data/ingested/relevance_check_report.jsonl"),
        help=(
            "Output path for --relevance-only mode's classification report "
            "(default: ../data/ingested/relevance_check_report.jsonl). "
            "Ignored in normal ingestion mode."
        )
    )
    args = parser.parse_args()

    run_ingestion(
        papers_dir=args.papers_dir,
        out_path=args.out,
        ledger_path=args.ledger,
        relevance_only=args.relevance_only,
        report_out=args.report_out,
    )
