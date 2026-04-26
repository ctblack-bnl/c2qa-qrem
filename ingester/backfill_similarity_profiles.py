#!/usr/bin/env python3
# ingester/backfill_similarity_profiles.py
#
# One-off script to run Pass 3 (similarity profile generation) over all
# existing ingested records in records.jsonl that do not yet have a
# similarity_profile field.
#
# Usage:
#   cd ingester
#   python3 backfill_similarity_profiles.py [--dry-run] [--limit N]
#
# Output:
#   Writes records_with_profiles.jsonl alongside the original.
#   The original records.jsonl is never modified.
#   When satisfied, swap manually:
#     mv ../data/ingested/records.jsonl ../data/ingested/records_backup.jsonl
#     mv ../data/ingested/records_with_profiles.jsonl ../data/ingested/records.jsonl
#     python3 build_sqlite.py
#
# Design:
#   - Reads records.jsonl line by line
#   - For records with outcome='ingested' and no similarity_profile:
#       runs Pass 3 for each sample in the record
#       appends the profiles to the record under 'similarity_profiles'
#         (keyed by sample_id)
#   - All other records are passed through unchanged
#   - Progress is printed to stdout
#   - Errors on individual records are logged and skipped — never fatal

import argparse
import json
import sys
import time
from pathlib import Path

# Add ingester directory to path so we can import our modules
INGESTER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(INGESTER_DIR))

from prompts import build_profile_prompt, PROFILE_VERSION
from openai_client import make_client
from config import get_deployment_name
from json_utils import safe_json_dumps

REPO_ROOT   = INGESTER_DIR.parent
JSONL_IN    = REPO_ROOT / "data" / "ingested" / "records.jsonl"
JSONL_OUT   = REPO_ROOT / "data" / "ingested" / "records_with_profiles.jsonl"


def call_claude_for_profiles(client, sample_records: list, filename: str) -> dict:
    """
    Call Claude with the Pass 3 prompt for a list of sample records.
    Returns a dict keyed by sample_id → profile dict.
    Raises on API error.
    """
    # Build a combined record for the prompt — all samples from this paper together
    # so Claude has full context (e.g. can compare samples within the paper)
    prompt = build_profile_prompt(sample_records)

    # Scale token budget with number of samples — each profile is ~200-300 tokens
    max_tokens = max(2000, len(sample_records) * 400)

    response = client.chat.completions.create(
        model=get_deployment_name(),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if present (defensive)
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    profiles_list = json.loads(raw)

    if not isinstance(profiles_list, list):
        raise ValueError(f"Expected JSON array, got {type(profiles_list)}")

    # Key by sample_id
    result = {}
    for p in profiles_list:
        sid = p.get("sample_id")
        if not sid:
            print(f"  WARNING: profile missing sample_id in {filename}, skipping entry")
            continue
        p["profile_version"] = PROFILE_VERSION
        result[sid] = p

    return result


def backfill(dry_run: bool = False, limit: int = None):
    if not JSONL_IN.exists():
        print(f"ERROR: {JSONL_IN} not found")
        sys.exit(1)

    print(f"C2QA Materials — Pass 3 Similarity Profile Backfill")
    print(f"  Input:   {JSONL_IN}")
    print(f"  Output:  {JSONL_OUT}")
    print(f"  Dry run: {dry_run}")
    if limit:
        print(f"  Limit:   {limit} records")
    print()

    client = make_client()

    # Read all records
    records = []
    with open(JSONL_IN, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"  WARNING: skipping malformed line: {e}")

    print(f"Read {len(records)} records from JSONL")

    # Count what needs profiling
    needs_profile = [
        r for r in records
        if r.get("outcome") == "ingested"
        and not r.get("similarity_profiles")
        and r.get("extraction_json", {}).get("samples")
    ]
    already_done = sum(1 for r in records if r.get("similarity_profiles"))
    skipped_not_ingested = len(records) - len(needs_profile) - already_done

    print(f"  Already have profiles: {already_done}")
    print(f"  Need profiling:        {len(needs_profile)}")
    print(f"  Skipped (not ingested or no samples): {skipped_not_ingested}")
    print()

    if limit:
        needs_profile = needs_profile[:limit]
        print(f"  Processing first {limit} records (--limit flag)")
        print()

    if dry_run:
        print("DRY RUN — no API calls, no output file written.")
        print("Records that would be profiled:")
        for r in needs_profile:
            samples = r.get("extraction_json", {}).get("samples", [])
            print(f"  {r.get('filename', '?')} — {len(samples)} samples")
        return

    # Process
    updated_records = []
    n_success = 0
    n_failed  = 0

    for i, record in enumerate(records):
        filename = record.get("filename", f"record_{i}")

        # Pass through records that don't need profiling
        if record.get("outcome") != "ingested" \
                or record.get("similarity_profiles") \
                or not record.get("extraction_json", {}).get("samples"):
            updated_records.append(record)
            continue

        # Skip if beyond limit
        if limit and n_success + n_failed >= limit:
            updated_records.append(record)
            continue

        samples = record["extraction_json"]["samples"]
        n = len(samples)
        print(f"[{n_success + n_failed + 1}/{len(needs_profile)}] {filename} — {n} sample(s)")

        try:
            profiles = call_claude_for_profiles(client, samples, filename)

            # Validate we got a profile for each sample
            missing = [s.get("sample_id") for s in samples if s.get("sample_id") not in profiles]
            if missing:
                print(f"  WARNING: missing profiles for sample_ids: {missing}")

            # Report what we got
            for sid, profile in profiles.items():
                mat   = profile.get("material_class", "?")
                dev   = profile.get("device_type", "?")
                tier  = profile.get("coherence_tier", "?")
                focus = ", ".join(profile.get("science_focus", []))
                print(f"  {sid}: {mat} / {dev} / {tier} / [{focus}]")

            # Attach profiles to record
            updated_record = dict(record)
            updated_record["similarity_profiles"] = profiles
            updated_records.append(updated_record)
            n_success += 1

        except Exception as e:
            print(f"  ERROR: {e}")
            # Pass through unchanged — don't lose the record
            updated_records.append(record)
            n_failed += 1

        # Brief pause to avoid rate limiting
        time.sleep(1)

    # Write output
    print()
    print(f"Writing {len(updated_records)} records to {JSONL_OUT}...")
    with open(JSONL_OUT, "w", encoding="utf-8") as f:
        for record in updated_records:
            f.write(safe_json_dumps(record) + "\n")

    print()
    print(f"Done.")
    print(f"  Profiles generated: {n_success}")
    print(f"  Failed:             {n_failed}")
    print(f"  Output:             {JSONL_OUT}")
    print()
    print("Next steps:")
    print("  1. Inspect a few profiles: python3 -c \"import json; [print(json.dumps(r.get('similarity_profiles',{}), indent=2)) for r in [json.loads(l) for l in open('../data/ingested/records_with_profiles.jsonl')] if r.get('similarity_profiles')][:3]\"")
    print("  2. If satisfied, swap files:")
    print("       mv ../data/ingested/records.jsonl ../data/ingested/records_backup.jsonl")
    print("       mv ../data/ingested/records_with_profiles.jsonl ../data/ingested/records.jsonl")
    print("  3. Rebuild SQLite:")
    print("       python3 build_sqlite.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill Pass 3 similarity profiles for existing ingested records"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be processed without making API calls"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N records (useful for testing)"
    )
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, limit=args.limit)
