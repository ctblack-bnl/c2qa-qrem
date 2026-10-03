# ingester/backfill_dedup_hashes.py
# One-time migration: populate content hashes on every deduplication.json
# decision entry, so the dedup skip-list (currently filename-only) can be
# switched to hash-based matching without losing track of any existing
# decision when files get renamed.
#
# Why this is needed: pipeline_ingest.py's load_dedup_skip_filenames() skips
# the "losing" side of a duplicate pair by exact filename match, BEFORE the
# ledger is even consulted. That losing file was often never actually
# ingested (no records.jsonl row, no ledger entry, no hash on file anywhere)
# — it's protected purely by this filename string match. If that file gets
# renamed (e.g. by a content-hash-appending renamer), the skip-list no
# longer recognizes it, and it would be ingested for real as if it were a
# brand-new paper, creating a duplicate database entry for content a human
# already explicitly decided to exclude.
#
# This script closes that gap in the same spirit as backfill_ledger_hashes.py:
# compute the hash now, while filenames are still current, and store it
# alongside the existing filename fields rather than replacing them (so the
# human-readable filenames stay in the file for context, but matching can
# move to hash).
#
# Usage:
#   cd explorer   # (or wherever deduplication.json and pipeline_ingest.py live)
#   python3 backfill_dedup_hashes.py \
#       --dedup ../data/ingested/deduplication.json \
#       --papers-dir ../data/papers \
#       --dry-run
#
#   (drop --dry-run once the report looks sane, to actually write the file)

import argparse
import hashlib
import json
from pathlib import Path


def build_disk_filename_index(papers_dir: Path) -> dict:
    """filename -> Path, for every PDF still on disk. First match wins; if a
    genuine filename collision is still unresolved on disk, this backfill
    can't tell which physical file a given decision entry meant — that case
    is reported as unresolved rather than guessed at."""
    index = {}
    collisions = set()
    for p in papers_dir.rglob("*.pdf"):
        if p.is_file():
            if p.name in index and index[p.name] != p:
                collisions.add(p.name)
            index.setdefault(p.name, p)
    return index, collisions


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dedup", type=Path, required=True)
    ap.add_argument("--papers-dir", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true",
                     help="Report what would change without writing the file.")
    args = ap.parse_args()

    dedup = json.loads(args.dedup.read_text(encoding="utf-8"))
    disk_index, on_disk_collisions = build_disk_filename_index(args.papers_dir)

    if on_disk_collisions:
        print("WARNING: these filenames currently match more than one file on "
              "disk — the backfill can't tell which physical file a decision "
              "entry meant, so hashes for these will be reported as "
              "unresolved. Sort these out (they're likely exactly the known "
              "collision set) before trusting this backfill fully:")
        for fn in sorted(on_disk_collisions):
            print(f"  - {fn}")
        print()

    filled = 0
    already_had = 0
    unresolved = []

    for decision in dedup.get("decisions", []):
        for key in ("paper_a", "paper_b"):
            fn = decision.get(key)
            hash_key = f"{key}_sha256"
            if not fn:
                continue
            if decision.get(hash_key):
                already_had += 1
                continue
            if fn in on_disk_collisions:
                unresolved.append((decision, key, fn, "ambiguous on-disk filename collision"))
                continue
            p = disk_index.get(fn)
            if not p:
                unresolved.append((decision, key, fn, "not found on disk"))
                continue
            decision[hash_key] = hash_file(p)
            filled += 1

    print(f"Already had hash : {already_had}")
    print(f"Filled           : {filled}")
    print(f"Unresolved       : {len(unresolved)}")
    if unresolved:
        print("\nUnresolved (need manual attention):")
        for decision, key, fn, why in unresolved:
            print(f"  - {key}={fn}  ({why})  "
                  f"[decision: keep={decision.get('keep')}, "
                  f"decided_at={decision.get('decided_at')}]")

    if args.dry_run:
        print("\n--dry-run: deduplication.json NOT written.")
        return

    args.dedup.write_text(
        json.dumps(dedup, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\ndeduplication.json updated in place: {args.dedup}")


if __name__ == "__main__":
    main()
