# ingester/processed_ledger.py
# Tracks which papers have already been processed so we never ingest the same
# paper twice. Uses content hash (source_pdf_sha256) as the primary key once
# an entry has one recorded — it is the only identity check that is actually
# invariant to renames, filename collisions between unrelated papers, and
# accidental duplicate-content-different-name uploads. DOI and filename
# remain as fallbacks for legacy entries that predate hash tracking.
#
# The ledger is a simple JSON file: data/ingested/processed_ledger.json
# It is read at startup and updated after each paper is processed.

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def load_ledger(ledger_path: Path) -> dict:
    """
    Load the processed papers ledger from disk.
    Returns an empty ledger dict if the file doesn't exist yet.
    """
    if not ledger_path.exists():
        return {"processed": []}
    with open(ledger_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_ledger(ledger: dict, ledger_path: Path) -> None:
    """Save the ledger to disk."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)


def is_already_processed(ledger: dict,
                         filename: str,
                         doi: Optional[str] = None,
                         source_pdf_sha256: Optional[str] = None) -> bool:
    """
    Check if a paper has already been processed.

    Matching priority:
      1. Content hash — authoritative whenever BOTH the incoming file and
         the candidate ledger entry have a hash. Same hash = same file,
         regardless of filename. A filename match under a hash MISMATCH is
         deliberately NOT treated as already-processed — that's exactly the
         "different paper, same auto-generated filename" case (Kharzeev,
         Xu, Li, Li_b, Chowdhury, Aug 2026) that this function used to miss
         silently.
      2. DOI — used only when hash comparison isn't possible (no hash on
         one or both sides).
      3. Filename — last-resort fallback, for legacy entries recorded
         before hash tracking existed and that have no hash at all.
    """
    for entry in ledger.get("processed", []):
        entry_hash = entry.get("source_pdf_sha256")

        if source_pdf_sha256 and entry_hash:
            # Both sides have a hash — this is the only comparison that
            # matters. Don't fall through to filename/DOI below even on a
            # mismatch; a stale filename/DOI match must not override a
            # confirmed hash mismatch.
            if entry_hash == source_pdf_sha256:
                return True
            continue

        # No hash on one or both sides — pre-backfill legacy entry.
        # Fall back to the old DOI/filename matching.
        if doi and entry.get("doi") and entry["doi"].strip() == doi.strip():
            return True
        if entry.get("filename") == filename:
            return True

    return False


def record_processed(ledger: dict,
                     filename: str,
                     outcome: str,
                     doi: Optional[str] = None,
                     arxiv_id: Optional[str] = None,
                     reason: Optional[str] = None,
                     record_ids: Optional[list] = None,
                     source_pdf_sha256: Optional[str] = None) -> None:
    """
    Add a paper to the processed ledger.

    Args:
        ledger:             the ledger dict (modified in place)
        filename:           PDF filename
        outcome:            'ingested', 'skipped', or 'failed'
        doi:                DOI if Claude extracted one (None if not found)
        reason:             for skipped papers, why they were skipped
        record_ids:         for ingested papers, the record IDs created
        source_pdf_sha256:  sha256 of the PDF's raw bytes (from load_pdf()).
                            This is now the primary identity key going
                            forward — always pass it when available.
    """
    entry = {
        "filename":       filename,
        "doi":            doi,
        "arxiv_id":       arxiv_id,
        "date_processed": datetime.now().strftime("%Y-%m-%d"),
        "outcome":        outcome,
    }
    if reason:
        entry["reason"] = reason
    if record_ids:
        entry["record_ids"] = record_ids
    if source_pdf_sha256:
        entry["source_pdf_sha256"] = source_pdf_sha256

    ledger["processed"].append(entry)
