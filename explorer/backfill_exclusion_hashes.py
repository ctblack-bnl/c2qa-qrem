# ingester/backfill_exclusion_hashes.py
# One-time migration: populate source_pdf_sha256 on every exclusions.json
# entry, so build_sqlite.py's exclusion filter can match by content hash
# instead of relying on filename/DOI/arXiv ID alone.
#
# Most exclusions.json entries already have a DOI or arXiv ID, which
# survives a rename fine on its own. The real gap is the handful of entries
# with BOTH doi and arxiv_id null — those rely purely on filename matching
# against the already-ingested records.jsonl row, which is safe as long as
# that paper was already ingested before any rename happens, but NOT safe
# if the PDF is renamed before ever being ingested (a future ingestion run
# would create a record under the new name that exclusions.json, still
# holding the old name, can no longer recognize).
#
# This script closes that gap the same way the other two backfills did:
# compute the hash now, while filenames are still current, and store it
# alongside the existing fields.
#
# Usage:
#   cd explorer   # (or wherever exclusions.json and records.jsonl live)
#   python3 backfill_exclusion_hashes.py \
#       --exclusions ../data/ingested/exclusions.json \
#       --records ../data/ingested/records.jsonl \
#       --papers-dir ../data/papers \
#       --dry-run
#
#   (drop --dry-run once the report looks sane, to actually write the file)

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


def build_disk_filename_index(papers_dir: Path) -> tuple:
    """filename -> Path, for every PDF still on disk, plus the set of
    filenames that match more than one file (ambiguous — can't resolve
    which physical file an entry meant)."""
    index = {}
    collisions = set()
    for p in papers_dir.rglob("*.pdf"):
        if p.is_file():
            if p.name in index and index[p.name] != p:
                collisions.add(p.name)
            index.setdefault(p.name, p)
    return index, collisions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclusions", type=Path, required=True)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--papers-dir", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true",
                     help="Report what would change without writing the file.")
    args = ap.parse_args()

    excl_data = json.loads(args.exclusions.read_text(encoding="utf-8"))
    records_map = build_records_hash_map(args.records)
    disk_index = None
    disk_collisions = set()

    filled_from_records = 0
    filled_from_disk = 0
    already_had = 0
    unresolved = []

    for entry in excl_data.get("exclusions", []):
        if entry.get("source_pdf_sha256"):
            already_had += 1
            continue

        fn = entry.get("filename")
        if not fn:
            unresolved.append((entry, "no filename on this entry"))
            continue

        h = records_map.get(fn)
        if h:
            entry["source_pdf_sha256"] = h
            filled_from_records += 1
            continue

        if disk_index is None:
            disk_index, disk_collisions = build_disk_filename_index(args.papers_dir)

        if fn in disk_collisions:
            unresolved.append((entry, "ambiguous on-disk filename collision"))
            continue

        p = disk_index.get(fn)
        if p:
            entry["source_pdf_sha256"] = hash_file(p)
            filled_from_disk += 1
            continue

        unresolved.append((entry, "not found in records.jsonl or on disk"))

    print(f"Already had hash   : {already_had}")
    print(f"Filled from records: {filled_from_records}")
    print(f"Filled from disk   : {filled_from_disk}")
    print(f"Unresolved         : {len(unresolved)}")
    if unresolved:
        print("\nUnresolved (need manual attention):")
        for entry, why in unresolved:
            print(f"  - {entry.get('filename')}  ({why})  "
                  f"[doi={entry.get('doi')}, arxiv_id={entry.get('arxiv_id')}]")

    if args.dry_run:
        print("\n--dry-run: exclusions.json NOT written.")
        return

    args.exclusions.write_text(
        json.dumps(excl_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nexclusions.json updated in place: {args.exclusions}")


if __name__ == "__main__":
    main()
