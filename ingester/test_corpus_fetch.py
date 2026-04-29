#!/usr/bin/env python3
from typing import Optional, List
# ingester/test_corpus_fetch.py
#
# Standalone test for the fetch_corpus() function.
# Run this BEFORE wiring fetch_corpus() into the HTTP handler to validate
# that the data model is correct and the join is clean.
#
# Usage:
#   cd ingester
#   python3 test_corpus_fetch.py
#   python3 test_corpus_fetch.py --db ../data/ingested/records.db
#   python3 test_corpus_fetch.py --verbose          # print one full sample record
#   python3 test_corpus_fetch.py --sample "Bahrami_2026_D1"  # inspect a specific sample
#
# Pass criteria (check each):
#   [ ] Sample count matches /api/samples count
#   [ ] All samples have sample_json (not None)
#   [ ] All samples have a catchall key (even if empty list)
#   [ ] Catchall item count is internally consistent
#   [ ] No orphaned catchall items (display_name mismatch)
#   [ ] Cross-check: one known sample's data matches /api/sample/{name}
#   [ ] Type filter works: --types correlation returns fewer catchall items
#   [ ] Unpromoted fields present in sample_json (fields beyond named columns)

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

# ── Inline copies of the constants and helpers from serve_materials.py ────
# (so this script runs standalone without importing the server)

ALL_NUMERIC_FIELDS = [
    ('Tc_K',                  'Tc (K)'),
    ('RRR',                   'RRR'),
    ('sheet_resistance_Ohm_sq', 'Sheet resistance (Ω/□)'),
    ('loss_tangent_substrate','Loss tangent substrate'),
    ('loss_tangent_interface','Loss tangent interface'),
    ('TLS_density',           'TLS density (GHz⁻¹·μm⁻²)'),
    ('Qi_internal',           'Qi internal'),
    ('Qi_single_photon',      'Qi single photon'),
    ('surface_oxide_nm',      'Surface oxide (nm)'),
    ('T1_us',                 'T1 (µs)'),
    ('T2_echo_us',            'T2 echo (µs)'),
    ('gate_1q_fidelity_pct',  '1Q fidelity (%)'),
    ('gate_2q_fidelity_pct',  '2Q fidelity (%)'),
    ('annealing_temperature_C','Anneal temp (°C)'),
    ('annealing_duration_s',  'Anneal duration (s)'),
    ('film_thickness_nm',     'Film thickness (nm)'),
    ('normal_state_resistance_Ohm',      'Normal state resistance (Ω)'),
    ('room_temperature_resistance_Ohm',  'Room temp resistance (Ω)'),
    ('derived_resistivity_uOhm_cm',      'Resistivity derived (µΩ·cm)'),
    ('derived_RRR_from_RvT',             'RRR derived from R vs T'),
    ('derived_sheet_resistance_Ohm_sq',  'Sheet resistance derived (Ω/□)'),
    ('derived_BCS_gap_meV',              'BCS gap derived (meV)'),
    ('derived_coherence_length_nm',      'Coherence length derived (nm)'),
    ('derived_kinetic_inductance_pH_sq', 'Kinetic inductance derived (pH/□)'),
]

PROFILE_SINGLE_FIELDS = [
    ('sim_material_class',   'Material class'),
    ('sim_transport_regime', 'Transport regime'),
    ('sim_device_type',      'Device type'),
    ('sim_coherence_tier',   'Coherence tier'),
    ('sim_growth_method',    'Growth method'),
]

PROFILE_LIST_FIELDS = [
    ('sim_loss_mechanisms',  'Loss mechanisms'),
    ('sim_science_focus',    'Science focus'),
    ('sim_key_correlations', 'Key correlations'),
]

VALID_CATCHALL_TYPES = {
    "correlation",
    "additional_measurement",
    "anomalous_observation",
    "schema_candidate",
}

# Named columns that exist in the samples table (used to identify unpromoted fields)
NAMED_SAMPLE_COLUMNS = {
    'substrate_material', 'substrate_orientation', 'film_material',
    'film_crystal_phase', 'film_thickness_nm', 'deposition_method',
    'deposition_temperature_C', 'annealing_temperature_C', 'annealing_duration_s',
    'junction_present', 'Tc_K', 'RRR', 'sheet_resistance_Ohm_sq',
    'loss_tangent_substrate', 'loss_tangent_interface', 'TLS_density',
    'Qi_internal', 'Qi_single_photon', 'surface_oxide_nm', 'T1_us',
    'T2_echo_us', 'gate_1q_fidelity_pct', 'gate_2q_fidelity_pct',
    'normal_state_resistance_Ohm', 'room_temperature_resistance_Ohm',
    'measured_structure_width_um', 'measured_structure_length_um',
}


def _parse_json_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def fetch_corpus(db_path: Path, types: Optional[List[str]] = None) -> List[dict]:
    """Standalone version of fetch_corpus() for testing."""
    if types:
        requested_types = [t for t in types if t in VALID_CATCHALL_TYPES]
    else:
        requested_types = list(VALID_CATCHALL_TYPES)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    numeric_cols        = ', '.join(f's.{f}' for f, _ in ALL_NUMERIC_FIELDS)
    profile_single_cols = ', '.join(f's.{f}' for f, _ in PROFILE_SINGLE_FIELDS)
    profile_list_cols   = ', '.join(f's.{f}' for f, _ in PROFILE_LIST_FIELDS)

    cur.execute(f"""
        SELECT
            s.display_name, s.sample_id, s.filename,
            s.film_material, s.film_crystal_phase,
            s.substrate_material, s.substrate_orientation,
            s.deposition_method, s.deposition_temperature_C,
            s.annealing_temperature_C, s.annealing_duration_s,
            s.junction_present, s.film_thickness_nm,
            s.Tc_confidence, s.RRR_confidence, s.Qi_confidence, s.T1_confidence,
            s.sample_json, s.derived_json,
            s.sim_profile_version,
            p.authors, p.title, p.doi, p.journal,
            p.human_reviewed, p.human_approved,
            {profile_single_cols},
            {profile_list_cols},
            {numeric_cols}
        FROM samples s
        JOIN papers p ON s.paper_id = p.id
        WHERE p.outcome = 'ingested'
        ORDER BY s.film_material, s.display_name
    """)

    rows = cur.fetchall()
    numeric_field_names = [f for f, _ in ALL_NUMERIC_FIELDS]

    samples_by_name = {}
    for row in rows:
        d = dict(row)
        for field in numeric_field_names:
            val = d.get(field)
            if val is not None:
                try:
                    d[field] = float(val)
                except (ValueError, TypeError):
                    d[field] = None
        for blob_field in ('sample_json', 'derived_json'):
            raw = d.get(blob_field)
            if raw:
                try:
                    d[blob_field] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d[blob_field] = None
        for field, _ in PROFILE_LIST_FIELDS:
            d[field] = _parse_json_list(d.get(field))
        d['catchall'] = []
        samples_by_name[d['display_name']] = d

    placeholders = ','.join('?' * len(requested_types))
    cur.execute(f"""
        SELECT
            c.display_name, c.item_type, c.description,
            c.value, c.source, c.notes, c.sample_id
        FROM catchall_items c
        JOIN papers p ON c.paper_id = p.id
        WHERE p.outcome = 'ingested'
          AND c.item_type IN ({placeholders})
        ORDER BY c.display_name, c.item_type
    """, requested_types)

    catchall_rows = cur.fetchall()
    conn.close()

    orphaned = 0
    for crow in catchall_rows:
        c = dict(crow)
        name = c.pop('display_name')
        if name in samples_by_name:
            samples_by_name[name]['catchall'].append(c)
        else:
            orphaned += 1

    return list(samples_by_name.values()), orphaned


# ── Test suite ─────────────────────────────────────────────────────────────

def run_tests(db_path: Path, verbose: bool, inspect_sample: object):
    print(f"\n{'='*60}")
    print(f"  fetch_corpus() test suite")
    print(f"  db: {db_path}")
    print(f"{'='*60}\n")

    passed = 0
    failed = 0

    def check(label: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        status = "✓ PASS" if condition else "✗ FAIL"
        print(f"  {status}  {label}")
        if detail:
            print(f"          {detail}")
        if condition:
            passed += 1
        else:
            failed += 1

    # ── Full corpus fetch ──────────────────────────────────────────────────
    print("[ Full corpus fetch ]")
    corpus, orphaned = fetch_corpus(db_path)

    check("Returns a non-empty list", len(corpus) > 0,
          f"Got {len(corpus)} samples")

    check("No orphaned catchall items", orphaned == 0,
          f"{orphaned} items had no matching sample" if orphaned else "")

    # ── Per-sample structure ───────────────────────────────────────────────
    print("\n[ Per-sample structure ]")

    missing_sample_json = [s['display_name'] for s in corpus if not s.get('sample_json')]
    check("All samples have sample_json",
          len(missing_sample_json) == 0,
          f"Missing in: {missing_sample_json[:5]}" if missing_sample_json else "")

    missing_catchall = [s['display_name'] for s in corpus if 'catchall' not in s]
    check("All samples have catchall key",
          len(missing_catchall) == 0,
          f"Missing in: {missing_catchall[:5]}" if missing_catchall else "")

    missing_display = [s for s in corpus if not s.get('display_name')]
    check("All samples have display_name", len(missing_display) == 0)

    # ── Catchall counts ────────────────────────────────────────────────────
    print("\n[ Catchall counts ]")

    type_counts = defaultdict(int)
    samples_with_catchall = 0
    for s in corpus:
        if s['catchall']:
            samples_with_catchall += 1
        for item in s['catchall']:
            type_counts[item['item_type']] += 1

    total_catchall = sum(type_counts.values())
    print(f"          Samples returned           : {len(corpus)}")
    print(f"          Samples with catchall items: {samples_with_catchall}")
    print(f"          Total catchall items        : {total_catchall}")
    for t in sorted(VALID_CATCHALL_TYPES):
        print(f"            {t:<35}: {type_counts[t]}")

    check("At least one correlation item exists", type_counts['correlation'] > 0,
          f"Found {type_counts['correlation']} correlations")

    check("Total catchall items > 0", total_catchall > 0)

    # ── Unpromoted fields in sample_json ──────────────────────────────────
    print("\n[ Unpromoted fields in sample_json ]")

    samples_with_unpromoted = 0
    all_unpromoted_keys = set()
    for s in corpus:
        raw = s.get('sample_json') or {}
        if isinstance(raw, dict):
            unpromoted = {k for k in raw.keys()
                         if k not in NAMED_SAMPLE_COLUMNS
                         and k not in ('sample_id', 'catchall')}
            if unpromoted:
                samples_with_unpromoted += 1
                all_unpromoted_keys.update(unpromoted)

    check("Some samples have unpromoted fields in sample_json",
          samples_with_unpromoted > 0,
          f"{samples_with_unpromoted} samples; example keys: {sorted(all_unpromoted_keys)[:8]}")

    # ── Coverage summary ───────────────────────────────────────────────────
    print("\n[ Coverage summary ]")

    key_fields = ['Tc_K', 'RRR', 'Qi_internal', 'T1_us', 'T2_echo_us',
                  'gate_2q_fidelity_pct', 'sheet_resistance_Ohm_sq']
    n = len(corpus)
    for field in key_fields:
        count = sum(1 for s in corpus if s.get(field) is not None)
        pct = 100 * count / n if n else 0
        print(f"          {field:<35}: {count:>3} / {n}  ({pct:.0f}%)")

    # ── Co-occurrence matrix (for mining readiness) ────────────────────────
    print("\n[ Co-occurrence: samples with both fields (mining readiness) ]")

    pairs = [
        ('RRR',     'T1_us',      'RRR → T1'),
        ('RRR',     'Qi_internal','RRR → Qi'),
        ('Tc_K',    'T1_us',      'Tc → T1'),
        ('Tc_K',    'Qi_internal','Tc → Qi'),
        ('surface_oxide_nm', 'Qi_internal', 'surface_oxide → Qi'),
        ('film_thickness_nm', 'Qi_internal', 'thickness → Qi'),
    ]
    for field_a, field_b, label in pairs:
        count = sum(1 for s in corpus
                    if s.get(field_a) is not None and s.get(field_b) is not None)
        print(f"          {label:<35}: {count:>3} samples")

    # ── Type filter test ──────────────────────────────────────────────────
    print("\n[ Type filter ]")

    corr_only, _ = fetch_corpus(db_path, types=['correlation'])
    corr_items = sum(len(s['catchall']) for s in corr_only)
    check("Filter types=['correlation'] returns only correlations",
          all(item['item_type'] == 'correlation'
              for s in corr_only for item in s['catchall']),
          f"{corr_items} correlation items across {len(corr_only)} samples")

    check("Filtered count <= unfiltered count",
          corr_items <= total_catchall,
          f"{corr_items} vs {total_catchall} total")

    # ── Specific sample inspection ─────────────────────────────────────────
    if inspect_sample:
        print(f"\n[ Sample inspection: {inspect_sample} ]")
        match = next((s for s in corpus if s['display_name'] == inspect_sample), None)
        if match:
            print(f"\n  Structured fields (non-null):")
            for field, label in ALL_NUMERIC_FIELDS:
                val = match.get(field)
                if val is not None:
                    print(f"    {label:<40}: {val}")
            print(f"\n  Catchall items ({len(match['catchall'])}):")
            for item in match['catchall']:
                print(f"    [{item['item_type']}] {item['description'][:80]}")
            if match.get('sample_json'):
                raw_keys = set(match['sample_json'].keys())
                unpromoted = raw_keys - NAMED_SAMPLE_COLUMNS - {'sample_id', 'catchall'}
                print(f"\n  Unpromoted fields in sample_json ({len(unpromoted)}):")
                for k in sorted(unpromoted):
                    print(f"    {k}")
        else:
            print(f"  Sample '{inspect_sample}' not found in corpus.")
            print(f"  Available display_names (first 10):")
            for s in corpus[:10]:
                print(f"    {s['display_name']}")

    # ── Verbose: print first sample in full ───────────────────────────────
    if verbose and corpus:
        print(f"\n[ Verbose: first sample record ]")
        sample = corpus[0]
        # Print without the full sample_json blob (too large)
        printable = {k: v for k, v in sample.items()
                     if k not in ('sample_json', 'derived_json')}
        print(json.dumps(printable, indent=2, ensure_ascii=False))

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed")
    if failed == 0:
        print(f"  ✓ All tests passed — safe to wire into HTTP handler")
    else:
        print(f"  ✗ Fix failures before wiring into HTTP handler")
    print(f"{'='*60}\n")

    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test fetch_corpus() against the local SQLite database."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("../data/ingested/records.db"),
        help="Path to records.db (default: ../data/ingested/records.db)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print first full sample record (excluding JSON blobs)"
    )
    parser.add_argument(
        "--sample",
        type=str,
        default=None,
        help="Inspect a specific sample by display_name"
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: database not found at {args.db}")
        print(f"Run build_sqlite.py first.")
        exit(1)

    ok = run_tests(args.db, verbose=args.verbose, inspect_sample=args.sample)
    exit(0 if ok else 1)
