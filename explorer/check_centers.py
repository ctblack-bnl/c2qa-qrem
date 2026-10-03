#!/usr/bin/env python3
"""
check_centers.py -- audit centers.derive_centers() against the real corpus.

Read-only: never writes to records.jsonl or records.db.

Usage (from explorer/):
    python3 check_centers.py
    python3 check_centers.py --records ../data/ingested/records.jsonl --show-all

Reports:
  * how many records have no acknowledgment text / name no center / name each center
  * multi-center records
  * records flagged for human review (matched nothing but look center-like)
"""

import argparse
import json
from collections import Counter

from centers import centers_for_record, needs_review, display_string


def get_ack(record):
    # Confirmed path in the live corpus: /relevance_json/funding_acknowledgments
    rj = record.get("relevance_json") or {}
    return rj.get("funding_acknowledgments")


def label(record):
    for k in ("filename", "source_filename", "pdf_filename", "file"):
        if record.get(k):
            return str(record[k])
    return record.get("source_doi") or record.get("doi") or "<unlabeled>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="../data/ingested/records.jsonl")
    ap.add_argument("--show-all", action="store_true",
                    help="print every record's derived centers")
    args = ap.parse_args()

    per_center = Counter()
    n = missing = none_named = no_ack = multi = 0
    review, multi_rows = [], []

    with open(args.records, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            n += 1
            ack = get_ack(rec)
            codes = centers_for_record(rec)
            if args.show_all:
                print(f"{display_string(codes):<22} {label(rec)}")
            if codes is None:
                missing += 1
                continue
            if not codes:
                none_named += 1
                if not ack:
                    no_ack += 1
                if needs_review(ack):
                    review.append((label(rec), ack))
                continue
            for c in codes:
                per_center[c] += 1
            if len(codes) > 1:
                multi += 1
                multi_rows.append((label(rec), codes))

    print(f"\nrecords read:                    {n}")
    print(f"no Pass 1 output (unknown):       {missing}")
    print(f"Pass 1 ran, no center named:      {none_named}")
    print(f"    of which no acknowledgment at all: {no_ack}")
    print("per-center record counts (a multi-center record counts once per center):")
    for c, k in sorted(per_center.items()):
        print(f"    {c:<8} {k}")
    print(f"multi-center records:             {multi}")
    for lab, codes in multi_rows:
        print(f"    {', '.join(codes):<16} {lab}")

    print(f"\nflagged for human review (matched nothing, look center-like): {len(review)}")
    for lab, ack in review:
        print(f"  - {lab}\n      {ack[:300]}")


if __name__ == "__main__":
    main()
