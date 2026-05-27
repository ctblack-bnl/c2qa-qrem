#!/usr/bin/env python3
# backfill_t1_context.py
#
# Backfills T1_measurement_context into existing records in records.jsonl.
#
# For records that have T1_us but no T1_measurement_context, infers the
# context from the similarity profile device_type:
#
#   transmon / fluxonium / gatemon / multi_qubit_device → qubit_state
#   resonator                                           → resonator_photon
#   anything else (film_only, junction_only, unknown)   → unknown
#
# Records without T1_us are left unchanged.
# Records that already have T1_measurement_context are left unchanged.
#
# Writes a new records.jsonl in place (via temp file).
# Run build_sqlite.py afterward to rebuild the SQLite database.
#
# Usage:
#   cd ingester
#   python3 backfill_t1_context.py --dry-run   # preview changes
#   python3 backfill_t1_context.py             # apply changes

import json
import os
import shutil
import argparse
from datetime import datetime

RECORDS_PATH = "../data/ingested/records.jsonl"

QUBIT_DEVICE_TYPES = {
    'transmon',
    'fluxonium',
    'gatemon',
    'multi_qubit_device',
}

RESONATOR_DEVICE_TYPES = {
    'resonator',
}


def infer_t1_context(device_type: str) -> tuple:
    """
    Infer T1_measurement_context value and confidence from device_type.
    Returns (value, confidence, source_note).
    """
    if device_type in QUBIT_DEVICE_TYPES:
        return (
            'qubit_state',
            'high',
            f"Backfilled from similarity_profile device_type='{device_type}' "
            f"by backfill_t1_context.py"
        )
    elif device_type in RESONATOR_DEVICE_TYPES:
        return (
            'resonator_photon',
            'high',
            f"Backfilled from similarity_profile device_type='{device_type}' "
            f"by backfill_t1_context.py"
        )
    else:
        return (
            'unknown',
            'low',
            f"Backfilled — device_type='{device_type}' ambiguous; "
            f"needs human review. Set by backfill_t1_context.py"
        )


def process_records(dry_run: bool = False):
    records_path = os.path.join(os.path.dirname(__file__), RECORDS_PATH)
    temp_path    = records_path + ".backfill_tmp"

    stats = {
        'total':          0,
        'skipped_no_t1':  0,
        'skipped_exists': 0,
        'qubit_state':    0,
        'resonator_photon': 0,
        'unknown':        0,
        'not_ingested':   0,
    }

    unknown_records = []  # collect for review report

    with open(records_path, 'r') as f_in, open(temp_path, 'w') as f_out:
        for line in f_in:
            stats['total'] += 1
            r = json.loads(line)

            # Only process ingested records
            if r.get('outcome') != 'ingested':
                stats['not_ingested'] += 1
                f_out.write(line)
                continue

            samples          = r.get('extraction_json', {}).get('samples', [])
            similarity_profiles = r.get('similarity_profiles', {})
            modified         = False

            for sample in samples:
                # Skip if no T1_us
                if 'T1_us' not in sample:
                    stats['skipped_no_t1'] += 1
                    continue

                # Skip if T1_measurement_context already present
                if 'T1_measurement_context' in sample:
                    stats['skipped_exists'] += 1
                    continue

                # Look up device_type from similarity profile
                sample_id   = sample.get('sample_id', '')
                profile     = similarity_profiles.get(sample_id, {})
                device_type = profile.get('device_type', 'unknown')

                value, confidence, source = infer_t1_context(device_type)

                if not dry_run:
                    sample['T1_measurement_context'] = {
                        'value':      value,
                        'confidence': confidence,
                        'source':     source,
                    }
                    modified = True

                # Track stats
                stats[value] += 1

                if value == 'unknown':
                    unknown_records.append({
                        'doi':        r.get('doi'),
                        'title':      r.get('title'),
                        'sample_id':  sample_id,
                        'device_type': device_type,
                    })

                action = "WOULD SET" if dry_run else "SET"
                print(
                    f"  {action} T1_measurement_context='{value}' "
                    f"[{confidence}] — {r.get('authors', '?')} "
                    f"sample '{sample_id}' (device_type='{device_type}')"
                )

            # Write record (modified or not)
            if modified:
                f_out.write(json.dumps(r) + '\n')
            else:
                f_out.write(line)

    # Replace original with temp file
    if not dry_run:
        shutil.move(temp_path, records_path)
        print(f"\nrecords.jsonl updated in place.")
        print(f"Run 'python3 build_sqlite.py' to rebuild the SQLite database.")
    else:
        os.remove(temp_path)
        print(f"\nDry run — no changes written.")

    # Summary
    print(f"\n--- Backfill Summary ---")
    print(f"  Total records processed : {stats['total']}")
    print(f"  Not ingested (skipped)  : {stats['not_ingested']}")
    print(f"  No T1_us (skipped)      : {stats['skipped_no_t1']}")
    print(f"  Already had context     : {stats['skipped_exists']}")
    print(f"  Set → qubit_state       : {stats['qubit_state']}")
    print(f"  Set → resonator_photon  : {stats['resonator_photon']}")
    print(f"  Set → unknown           : {stats['unknown']}")

    if unknown_records:
        print(f"\n--- Records needing human review (T1_measurement_context=unknown) ---")
        for rec in unknown_records:
            print(f"  {rec['authors'] if 'authors' in rec else rec['doi']} "
                  f"| sample '{rec['sample_id']}' "
                  f"| device_type='{rec['device_type']}'")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Backfill T1_measurement_context into records.jsonl'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing anything'
    )
    args = parser.parse_args()

    print(f"Backfilling T1_measurement_context ({'DRY RUN' if args.dry_run else 'LIVE'})...")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    process_records(dry_run=args.dry_run)
