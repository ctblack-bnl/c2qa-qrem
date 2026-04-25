#!/usr/bin/env python3
"""
generate_qubit_profile.py
Generates a QREM qubit hardware profile YAML from a materials database sample.

For each QREM hardware profile field:
  - If the sample has a measured value → use it, mark as 'measured'
  - If not → fall back to transmon_baseline_2026.yaml defaults, mark as 'assumed'

The provenance block records every field's source so scientists can see
exactly what came from data vs what was assumed.

Usage (standalone):
    python3 generate_qubit_profile.py <display_name> [--db path/to/records.db]

Usage (from serve_materials.py):
    from generate_qubit_profile import generate_profile
    result = generate_profile(sample_dict, profiles_dir)
"""

import yaml
import sqlite3
from pathlib import Path
from datetime import date


# ── Field mappings: database column → QREM profile section.field ─────────
# Each entry: (db_column, yaml_section, yaml_field, units_note)
FIELD_MAPPINGS = [
    # Coherence
    ('T1_us',               'coherence', 'T1_us',                    'µs'),
    ('T2_echo_us',          'coherence', 'T2_us',                    'µs'),
    # Gates
    ('gate_1q_fidelity_pct','gates',     'single_qubit_fidelity_pct','%'),
    ('gate_2q_fidelity_pct','gates',     'two_qubit_fidelity_pct',   '%'),
    ('readout_fidelity_pct','gates',     'readout_fidelity_pct',     '%'),
    ('readout_time_ns',     'gates',     'readout_time_ns',          'ns'),
    ('single_qubit_gate_time_ns', 'gates', 'single_qubit_gate_time_ns', 'ns'),
    ('two_qubit_gate_time_ns',    'gates', 'two_qubit_gate_time_ns',    'ns'),
]

# Defaults — loaded from transmon_baseline_2026.yaml at runtime
DEFAULT_PROFILE_NAME = 'transmon_baseline_2026'


def load_defaults(profiles_dir: str) -> dict:
    """Load the baseline qubit profile to use as fallback defaults."""
    path = Path(profiles_dir) / 'qubits' / f'{DEFAULT_PROFILE_NAME}.yaml'
    if not path.exists():
        # Hard-coded fallback if file not found
        return {
            'coherence': {'T1_us': 200, 'T2_us': 300},
            'gates': {
                'single_qubit_fidelity_pct': 99.9,
                'single_qubit_gate_time_ns': 20,
                'two_qubit_fidelity_pct':    99.9,
                'two_qubit_gate_time_ns':    200,
                'readout_fidelity_pct':      99.5,
                'readout_time_ns':           500,
            }
        }
    with open(path) as f:
        return yaml.safe_load(f)


def generate_profile(sample: dict, profiles_dir: str) -> dict:
    """
    Generate a qubit profile dict from a sample record.

    Args:
        sample:       dict of sample fields from the database
        profiles_dir: path to the hardware_profiles/ directory

    Returns:
        dict with keys:
          'yaml_str'       — the YAML content as a string
          'filename'       — suggested filename (e.g. 'Wang_2026_Transmon_5.yaml')
          'measured_fields' — list of fields taken from corpus
          'assumed_fields'  — list of fields using defaults
          'display_name'   — sample display name
    """
    display_name = sample.get('display_name') or sample.get('sample_id', 'unknown')
    defaults = load_defaults(profiles_dir)

    # Sanitize display_name for use as filename
    filename_stem = display_name.replace(' ', '_').replace('/', '_')
    filename = f'{filename_stem}.yaml'

    measured_fields = []
    assumed_fields  = []

    # Build coherence section
    coherence = {}
    for db_col, section, yaml_field, units in FIELD_MAPPINGS:
        if section != 'coherence':
            continue
        val = sample.get(db_col)
        if val is not None:
            coherence[yaml_field] = float(val)
            measured_fields.append(yaml_field)
        else:
            coherence[yaml_field] = defaults.get('coherence', {}).get(yaml_field)
            assumed_fields.append(yaml_field)

    # Build gates section
    gates = {}
    for db_col, section, yaml_field, units in FIELD_MAPPINGS:
        if section != 'gates':
            continue
        val = sample.get(db_col)
        if val is not None:
            gates[yaml_field] = float(val)
            measured_fields.append(yaml_field)
        else:
            gates[yaml_field] = defaults.get('gates', {}).get(yaml_field)
            assumed_fields.append(yaml_field)

    # Build provenance section
    provenance = {
        'derived_from_sample': display_name,
        'source_doi':          sample.get('doi'),
        'source_authors':      sample.get('authors'),
        'source_journal':      sample.get('journal'),
        'film_material':       sample.get('film_material'),
        'substrate_material':  sample.get('substrate_material'),
        'film_thickness_nm':   sample.get('film_thickness_nm'),
        'date_generated':      str(date.today()),
        'generated_by':        'generate_qubit_profile.py',
        'defaults_from':       DEFAULT_PROFILE_NAME,
        'measured_fields':     measured_fields,
        'assumed_fields':      assumed_fields,
    }
    # Remove None values from provenance for cleaner output
    provenance = {k: v for k, v in provenance.items() if v is not None}

    # Assemble the full profile
    profile = {
        'profile_type':  'qubits',
        'name':          filename_stem,
        'description':   _build_description(sample, measured_fields),
        'platform':      'superconducting',
        'source':        f"Extracted from corpus: {display_name}",
        'coherence':     coherence,
        'gates':         gates,
        'provenance':    provenance,
    }

    # Generate YAML with a helpful header comment
    yaml_str = _build_yaml_string(profile, display_name, measured_fields, assumed_fields)

    return {
        'yaml_str':        yaml_str,
        'filename':        filename,
        'measured_fields': measured_fields,
        'assumed_fields':  assumed_fields,
        'display_name':    display_name,
        'profile':         profile,
    }


def _build_description(sample: dict, measured_fields: list) -> str:
    """Build a human-readable description for the profile."""
    parts = []
    if sample.get('film_material'):
        parts.append(sample['film_material'])
    if sample.get('substrate_material'):
        parts.append(f"on {sample['substrate_material']}")
    if sample.get('authors'):
        # Get first author surname
        first_author = sample['authors'].split(',')[0].split()[-1]
        parts.append(f"({first_author} et al.)")
    if measured_fields:
        parts.append(f"— {len(measured_fields)} measured field(s)")
    else:
        parts.append("— all defaults (no device performance data in corpus)")
    return ' '.join(parts)


def _build_yaml_string(profile: dict, display_name: str,
                        measured_fields: list, assumed_fields: list) -> str:
    """Build the YAML string with header comments."""
    lines = []
    lines.append(f"# qubits/{profile['name']}.yaml")
    lines.append(f"# Generated by Hardware Profile Updater from corpus sample: {display_name}")
    lines.append(f"# Generated: {profile['provenance']['date_generated']}")
    lines.append(f"#")
    lines.append(f"# Measured fields ({len(measured_fields)}): {', '.join(measured_fields) if measured_fields else 'none'}")
    lines.append(f"# Assumed fields  ({len(assumed_fields)}): {', '.join(assumed_fields) if assumed_fields else 'none'}")
    lines.append(f"#")
    lines.append(f"# Fields marked [MEASURED] came directly from the corpus.")
    lines.append(f"# Fields marked [ASSUMED] use defaults from {profile['provenance']['defaults_from']}.")
    lines.append(f"# Review assumed fields before using this profile for quantitative analysis.")
    lines.append('')

    # Write profile_type, name, description, platform, source
    for key in ['profile_type', 'name', 'description', 'platform', 'source']:
        lines.append(f"{key}: {_yaml_scalar(profile[key])}")
    lines.append('')

    # Coherence section with inline comments
    lines.append('coherence:')
    coherence_comments = {
        'T1_us': 'Energy relaxation time (µs)',
        'T2_us': 'Dephasing time (µs)',
    }
    for field, val in profile['coherence'].items():
        tag = '[MEASURED]' if field in measured_fields else '[ASSUMED] '
        comment = coherence_comments.get(field, '')
        lines.append(f"  {field}: {val}    # {tag} {comment}")
    lines.append('')

    # Gates section with inline comments
    lines.append('gates:')
    gate_comments = {
        'single_qubit_fidelity_pct': 'Single-qubit gate fidelity (%)',
        'single_qubit_gate_time_ns': 'Single-qubit gate time (ns)',
        'two_qubit_fidelity_pct':    'Two-qubit gate fidelity (%) — primary driver of code distance',
        'two_qubit_gate_time_ns':    'Two-qubit gate time (ns)',
        'readout_fidelity_pct':      'Readout fidelity (%)',
        'readout_time_ns':           'Readout time (ns)',
    }
    for field, val in profile['gates'].items():
        tag = '[MEASURED]' if field in measured_fields else '[ASSUMED] '
        comment = gate_comments.get(field, '')
        lines.append(f"  {field}: {val}    # {tag} {comment}")
    lines.append('')

    # Provenance section
    lines.append('provenance:')
    for key, val in profile['provenance'].items():
        if isinstance(val, list):
            if val:
                lines.append(f"  {key}:")
                for item in val:
                    lines.append(f"    - {item}")
            else:
                lines.append(f"  {key}: []")
        else:
            lines.append(f"  {key}: {_yaml_scalar(val)}")

    return '\n'.join(lines) + '\n'


def _yaml_scalar(val) -> str:
    """Format a scalar value for YAML output."""
    if val is None:
        return 'null'
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, str):
        # Quote strings that need it
        if any(c in val for c in [':', '#', '[', ']', '{', '}', ',', '&', '*', '?', '|', '>', '!', "'", '"']):
            return f'"{val}"'
        return val
    return str(val)


def save_profile(result: dict, profiles_dir: str) -> Path:
    """Write the generated YAML to the qubits/ directory."""
    output_path = Path(profiles_dir) / 'qubits' / result['filename']
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result['yaml_str'])
    return output_path


def fetch_sample_from_db(display_name: str, db_path: str) -> dict:
    """Fetch a sample record from the SQLite database."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT s.*, p.title, p.authors, p.doi, p.journal
        FROM samples s
        JOIN papers p ON s.paper_id = p.id
        WHERE s.display_name = ?
        LIMIT 1
    """, (display_name,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Sample not found: {display_name}")
    return dict(row)


# ── CLI entry point ───────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='Generate a QREM qubit profile from a corpus sample')
    parser.add_argument('display_name', help='Sample display name (e.g. Wang_2026_Transmon_5)')
    parser.add_argument('--db', default='../data/ingested/records.db', help='Path to records.db')
    parser.add_argument('--profiles-dir', default='../src/qrem/hardware_profiles', help='Path to hardware_profiles/')
    parser.add_argument('--dry-run', action='store_true', help='Print YAML without saving')
    args = parser.parse_args()

    sample = fetch_sample_from_db(args.display_name, args.db)
    result = generate_profile(sample, args.profiles_dir)

    print(f"\nGenerated profile for: {result['display_name']}")
    print(f"Filename: {result['filename']}")
    print(f"Measured fields ({len(result['measured_fields'])}): {', '.join(result['measured_fields']) or 'none'}")
    print(f"Assumed fields  ({len(result['assumed_fields'])}): {', '.join(result['assumed_fields'])}")
    print()
    print(result['yaml_str'])

    if not args.dry_run:
        path = save_profile(result, args.profiles_dir)
        print(f"Saved to: {path}")
    else:
        print("[dry-run] Not saved.")
