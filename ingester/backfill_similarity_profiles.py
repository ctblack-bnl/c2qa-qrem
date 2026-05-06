#!/usr/bin/env python3
# ingester/backfill_similarity_profiles.py
#
# One-off script to run Pass 3 (similarity profile generation) over all
# existing ingested records in records.jsonl that do not yet have a
# similarity_profile field.
#
# Usage:
#   cd ingester
#   python3 backfill_similarity_profiles.py [--dry-run] [--limit N] [--filter PATTERN]
#
# Examples:
#   # Backfill all records missing profiles
#   python3 backfill_similarity_profiles.py
#
#   # Force reprocess a specific paper (even if it already has a profile)
#   python3 backfill_similarity_profiles.py --filter Zaman
#
#   # Dry run to see what would be processed
#   python3 backfill_similarity_profiles.py --filter Zaman --dry-run
#
#   # Test on first 3 records needing profiles
#   python3 backfill_similarity_profiles.py --limit 3
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
#   - For records with outcome='ingested' and no similarity_profile
#     (or matching --filter pattern):
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


def backfill(dry_run: bool = False, limit: int = None, filter_pattern: str = None):
    if not JSONL_IN.exists():
        print(f"ERROR: {JSONL_IN} not found")
        sys.exit(1)

    print(f"C2QA Materials — Pass 3 Similarity Profile Backfill")
    print(f"  Input:          {JSONL_IN}")
    print(f"  Output:         {JSONL_OUT}")
    print(f"  Dry run:        {dry_run}")
    print(f"  Filter pattern: {filter_pattern or '(none — missing profiles only)'}")
    if limit:
        print(f"  Limit:          {limit} records")
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

    # Classify records
    def needs_processing(record):
        """
        A record needs processing if:
          - outcome is 'ingested'
          - has samples to profile
          AND either:
            - has no similarity_profiles yet (normal backfill), OR
            - matches the filter pattern (forced reprocess)
        """
        if record.get("outcome") != "ingested":
            return False
        if not record.get("extraction_json", {}).get("samples"):
            return False
        has_profile = bool(record.get("similarity_profiles"))
        force_this  = (filter_pattern is not None and
                       filter_pattern.lower() in record.get("filename", "").lower())
        if force_this:
            return True
        return not has_profile

    to_process = [r for r in records if needs_processing(r)]
    already_done = sum(
        1 for r in records
        if r.get("similarity_profiles")
        and not (filter_pattern and
                 filter_pattern.lower() in r.get("filename", "").lower())
    )
    skipped_other = len(records) - len(to_process) - already_done

    print(f"  Already have profiles (keeping): {already_done}")
    print(f"  To process:                      {len(to_process)}")
    if filter_pattern:
        forced   = sum(1 for r in to_process if r.get("similarity_profiles"))
        missing  = sum(1 for r in to_process if not r.get("similarity_profiles"))
        print(f"    Forced reprocess (--filter):   {forced}")
        print(f"    Missing profiles:              {missing}")
    print(f"  Skipped (not ingested / no samples): {skipped_other}")
    print()

    if limit:
        to_process = to_process[:limit]
        print(f"  Processing first {limit} records (--limit flag)")
        print()

    if not to_process:
        print("Nothing to process — all eligible records already have profiles.")
        if filter_pattern:
            print(f"  (No records matched filter pattern '{filter_pattern}')")
        return

    if dry_run:
        print("DRY RUN — no API calls, no output file written.")
        print("Records that would be processed:")
        for r in to_process:
            samples  = r.get("extraction_json", {}).get("samples", [])
            has_prof = "REPROCESS" if r.get("similarity_profiles") else "NEW"
            print(f"  [{has_prof}] {r.get('filename', '?')} — {len(samples)} sample(s)")
        return

    # Build a set of filenames to process for fast lookup
    to_process_filenames = {r.get("filename") for r in to_process}

    # Process — iterate all records in order, replacing those that need it
    updated_records = []
    n_success = 0
    n_failed  = 0
    process_counter = 0

    for i, record in enumerate(records):
        filename = record.get("filename", f"record_{i}")

        # Pass through records not in our processing set
        if filename not in to_process_filenames:
            updated_records.append(record)
            continue

        # Skip if beyond limit
        if limit and process_counter >= limit:
            updated_records.append(record)
            continue

        samples = record["extraction_json"]["samples"]
        n       = len(samples)
        process_counter += 1
        reprocess_flag = " [REPROCESS]" if record.get("similarity_profiles") else " [NEW]"
        print(f"[{process_counter}/{len(to_process)}] {filename} — "
              f"{n} sample(s){reprocess_flag}")

        try:
            profiles = call_claude_for_profiles(client, samples, filename)

            # Validate we got a profile for each sample
            missing_sids = [
                s.get("sample_id") for s in samples
                if s.get("sample_id") not in profiles
            ]
            if missing_sids:
                print(f"  WARNING: missing profiles for sample_ids: {missing_sids}")

            # Report what we got
            for sid, profile in profiles.items():
                mat   = profile.get("material_class", "?")
                dev   = profile.get("device_type", "?")
                tier  = profile.get("coherence_tier", "?")
                focus = ", ".join(profile.get("science_focus", []))
                old_mat = ""
                if record.get("similarity_profiles", {}).get(sid):
                    old = record["similarity_profiles"][sid].get("material_class", "?")
                    if old != mat:
                        old_mat = f" (was: {old})"
                print(f"  {sid}: {mat}{old_mat} / {dev} / {tier} / [{focus}]")

            # Attach updated profiles to record
            updated_record = dict(record)
            updated_record["similarity_profiles"] = profiles
            updated_records.append(updated_record)
            n_success += 1

        except Exception as e:
            import traceback
            traceback.print_exc()
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
    print(f"  Profiles generated/updated : {n_success}")
    print(f"  Failed (kept original)     : {n_failed}")
    print(f"  Output                     : {JSONL_OUT}")
    print()
    print("Next steps:")
    print("  1. Inspect updated profiles:")
    print("       python3 -c \"import json; [print(r['filename'], json.dumps(r.get('similarity_profiles',{}), indent=2)) for r in [json.loads(l) for l in open('../data/ingested/records_with_profiles.jsonl')] if 'Zaman' in r.get('filename','')]\"")
    print("  2. If satisfied, swap files:")
    print("       mv ../data/ingested/records.jsonl ../data/ingested/records_backup.jsonl")
    print("       mv ../data/ingested/records_with_profiles.jsonl ../data/ingested/records.jsonl")
    print("  3. Rebuild SQLite:")
    print("       python3 build_sqlite.py")
    print("  4. Re-run Phase A:")
    print("       python3 pipeline_mining.py phase-a")


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
    parser.add_argument(
        "--filter", type=str, default=None,
        dest="filter_pattern",
        help=(
            "Force reprocess records whose filename contains this string, "
            "even if they already have profiles. Case-insensitive. "
            "Example: --filter Zaman"
        )
    )
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, limit=args.limit, filter_pattern=args.filter_pattern)
