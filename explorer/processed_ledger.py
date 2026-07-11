# ingester/processed_ledger.py
# Tracks which papers have already been processed so we never ingest the same
# paper twice. Uses DOI as the primary key (globally unique and stable),
# with filename as a fallback for papers without a DOI (e.g. preprints).
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
                         doi: Optional[str] = None) -> bool:
    """
    Check if a paper has already been processed.
    Matches on DOI first (if available), then falls back to filename.
    """
    for entry in ledger.get("processed", []):
        # DOI match — most reliable
        if doi and entry.get("doi") and entry["doi"].strip() == doi.strip():
            return True
        # Filename match — fallback for papers without DOI
        if entry.get("filename") == filename:
            return True
    return False


def record_processed(ledger: dict,
                     filename: str,
                     outcome: str,
                     doi: Optional[str] = None,
                     arxiv_id: Optional[str] = None,
                     reason: Optional[str] = None,
                     record_ids: Optional[list] = None) -> None:
    """
    Add a paper to the processed ledger.

    Args:
        ledger:     the ledger dict (modified in place)
        filename:   PDF filename
        outcome:    'ingested', 'skipped', or 'failed'
        doi:        DOI if Claude extracted one (None if not found)
        reason:     for skipped papers, why they were skipped
        record_ids: for ingested papers, the record IDs created
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

    ledger["processed"].append(entry)
