# ingester/backfill_ledger_hashes.py
# One-time migration: populate source_pdf_sha256 on existing ledger entries
# so the hash-primary is_already_processed() check doesn't treat the entire
# existing corpus as unseen.
#
# Strategy, per ledger entry missing source_pdf_sha256:
#   1. Look it up by filename in records.jsonl (which has stamped
#      source_pdf_sha256 on every record since Aug 2026) and copy the hash.
#   2. If not found there, try to locate the PDF on disk under --papers-dir
#      (rglob by filename) and hash it directly.
#   3. If neither works, leave it unresolved and report it — these need a
#      human look (likely a renamed/moved/deleted file with no record).
#
# Usage:
#   cd ingester
#   python3 backfill_ledger_hashes.py \
#       --ledger ../data/ingested/processed_ledger.json \
#       --records ../data/ingested/records.jsonl \
#       --papers-dir ../data/papers \
#       --dry-run
#
#   (drop --dry-run once the report looks sane, to actually write the ledger)

import argparse
import hashlib
import json
from pathlib import Path


def build_records_hash_map(records_path: Path) -> dict:
    """filename -> source_pdf_sha256, last-write-wins if a filename recurs."""
    mapping = {}
    if not records_path.exists():
        return mapping
    with open(records_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            fn = rec.get("filename")
            h = rec.get("source_pdf_sha256")
            if fn and h:
                mapping[fn] = h
    return mapping


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_disk_filename_index(papers_dir: Path) -> dict:
    """filename -> Path, for every PDF still on disk. First match wins;
    if a filename collision is still unresolved on disk, this backfill
    can't disambiguate it either — it'll show up in the unresolved report."""
    index = {}
    for p in papers_dir.rglob("*.pdf"):
        if p.is_file():
            index.setdefault(p.name, p)
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--papers-dir", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true",
                     help="Report what would change without writing the ledger.")
    args = ap.parse_args()

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    records_map = build_records_hash_map(args.records)
    disk_index = None  # built lazily only if needed

    filled_from_records = 0
    filled_from_disk = 0
    already_had_hash = 0
    unresolved = []

    for entry in ledger.get("processed", []):
        if entry.get("source_pdf_sha256"):
            already_had_hash += 1
            continue

        fn = entry.get("filename")
        h = records_map.get(fn)
        if h:
            entry["source_pdf_sha256"] = h
            filled_from_records += 1
            continue

        if disk_index is None:
            disk_index = build_disk_filename_index(args.papers_dir)
        p = disk_index.get(fn)
        if p:
            entry["source_pdf_sha256"] = hash_file(p)
            filled_from_disk += 1
            continue

        unresolved.append(entry)

    print(f"Already had hash   : {already_had_hash}")
    print(f"Filled from records: {filled_from_records}")
    print(f"Filled from disk   : {filled_from_disk}")
    print(f"Unresolved         : {len(unresolved)}")
    if unresolved:
        print("\nUnresolved entries (need manual attention):")
        for e in unresolved:
            print(f"  - {e.get('filename')}  (outcome={e.get('outcome')}, "
                  f"date={e.get('date_processed')}, doi={e.get('doi')})")

    if args.dry_run:
        print("\n--dry-run: ledger NOT written.")
        return

    args.ledger.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nLedger updated in place: {args.ledger}")


if __name__ == "__main__":
    main()
