#!/usr/bin/env python3
"""
generate_qubit_profile.py
Generates a QREM qubit hardware profile YAML from a materials database sample.

For each QREM hardware profile field:
  - If the sample has a measured value → use it, mark as [MEASURED]
  - If not → fall back to transmon_baseline_2026.yaml defaults, mark as [ASSUMED]

Stage 4 extension (May 2026):
  Three new optional sections are written alongside coherence/gates:
    materials:             — raw material properties (Tc, Qi, Q_TLS_0, mean_free_path)
    device:                — device parameters (qubit frequency)
    surface_participation: — geometry inputs (p_MS_pad, p_MS_resonator)
  These feed compute_t1_decomposition() in t1_decomposition.py at estimation time.
  Fields that are null in the corpus are written as null — the decomposition
  falls back gracefully through the tier hierarchy for any missing input.

  A defaults_path field is added to provenance so the estimator knows where to
  find transmon_analytical_defaults.yaml at runtime.

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
# Note: T2_us uses fallback logic in generate_profile() — not listed here.
FIELD_MAPPINGS = [
    # Coherence
    ('T1_us',               'coherence', 'T1_us',                    'µs'),
    # Gates
    ('gate_1q_fidelity_pct','gates',     'single_qubit_fidelity_pct','%'),
    ('gate_2q_fidelity_pct','gates',     'two_qubit_fidelity_pct',   '%'),
    ('readout_fidelity_pct','gates',     'readout_fidelity_pct',     '%'),
    ('readout_time_ns',     'gates',     'readout_time_ns',          'ns'),
    ('single_qubit_gate_time_ns', 'gates', 'single_qubit_gate_time_ns', 'ns'),
    ('two_qubit_gate_time_ns',    'gates', 'two_qubit_gate_time_ns',    'ns'),
]

# Derived field fallback chains — mirrors build_sqlite.py derived_X pattern.
# Each entry: (yaml_field, [(db_col, provenance_label), ...], section, units, comment)
# First non-null value in the db_col list wins.
DERIVED_COHERENCE_FIELDS = [
    # T2: echo preferred (refocuses low-frequency noise); fall back to Ramsey
    ('T2_us', [
        ('T2_echo_us',    'T2_echo'),
        ('T2_ramsey_us',  'T2_ramsey'),
    ], 'coherence', 'µs', 'Dephasing time (µs)'),
]

DERIVED_MATERIAL_FIELDS = [
    # Qi: single-photon preferred (TLS-unsaturated regime); fall back to internal Qi
    ('Qi', [
        ('Qi_single_photon',           'Qi_single_photon'),
        ('Qi_internal', 'Qi_internal'),
    ], 'materials', 'dimensionless',
     'Internal quality factor — single-photon preferred (TLS unsaturated). Q_TLS_0 preferred over Qi for loss model.'),

    # tan_delta: effective surface preferred; fall back to interface, then substrate
    ('tan_delta', [
        ('tan_delta_effective_surface', 'tan_delta_effective_surface'),
        ('loss_tangent_interface',      'loss_tangent_interface'),
        ('loss_tangent_substrate',      'loss_tangent_substrate'),
    ], 'materials', 'dimensionless',
     'Surface loss tangent — best available: tan_delta_effective_surface → loss_tangent_interface → loss_tangent_substrate'),
]

# Stage 4: material field mappings — db column → yaml field, units, comment
# These go into the new materials/device/surface_participation sections.
# All are optional — null if not in corpus record.
# Note: Qi and tan_delta use fallback logic via DERIVED_MATERIAL_FIELDS — not listed here.
MATERIAL_FIELD_MAPPINGS = [
    # (db_column, yaml_section, yaml_field, units, comment)
    ('Tc_K',                        'materials',           'Tc_K',           'K',         'Superconducting critical temperature'),
    ('Q_TLS_0',                     'materials',           'Q_TLS_0',        'dimensionless', 'Unsaturated TLS quality factor — preferred over Qi for loss model'),
    ('mean_free_path_nm',           'materials',           'mean_free_path_nm', 'nm',      'Electron mean free path — determines clean vs dirty limit'),
    ('qubit_frequency_GHz',         'device',              'f_qubit_GHz',    'GHz',       'Qubit operating frequency — required for pad TLS calculation'),
    ('p_MS_pad',                    'surface_participation','p_MS_pad',       'dimensionless', 'Qubit pad metal-substrate surface participation ratio (FEM-derived)'),
    ('p_MS_resonator',              'surface_participation','p_MS_resonator', 'dimensionless', 'Resonator metal-substrate surface participation ratio (FEM-derived)'),
]

# Defaults — loaded from transmon_baseline_2026.yaml at runtime
DEFAULT_PROFILE_NAME = 'transmon_baseline_2026'

# Relative path from qubits/ directory to the material_defaults/ directory.
MATERIAL_DEFAULTS_DIR = '../material_defaults'
GENERAL_DEFAULTS_NAME = 'transmon_general_defaults.yaml'


def _resolve_defaults_path(derived_material: str, profiles_dir: str) -> str:
    """
    Return the relative defaults_path for a given derived_material.
    Looks for a per-material file in material_defaults/; falls back to
    transmon_general_defaults.yaml if not found.
    Path is relative to the qubits/ directory (where the profile YAML lives).
    """
    if derived_material and derived_material not in ('other', 'unknown'):
        candidate = (Path(profiles_dir) / 'material_defaults' /
                     f'{derived_material}_material_defaults.yaml')
        if candidate.exists():
            return f'{MATERIAL_DEFAULTS_DIR}/{derived_material}_material_defaults.yaml'
    return f'{MATERIAL_DEFAULTS_DIR}/{GENERAL_DEFAULTS_NAME}'


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
          'yaml_str'        — the YAML content as a string
          'filename'        — suggested filename (e.g. 'Wang_2026_Transmon_5.yaml')
          'measured_fields' — list of fields taken from corpus (coherence + gates)
          'assumed_fields'  — list of fields using defaults (coherence + gates)
          'material_fields' — list of material fields found in corpus (Stage 4)
          'display_name'    — sample display name
          'profile'         — the profile dict
    """
    display_name = sample.get('display_name') or sample.get('sample_id', 'unknown')
    defaults = load_defaults(profiles_dir)

    # Sanitize display_name for use as filename
    filename_stem = display_name.replace(' ', '_').replace('/', '_')
    filename = f'{filename_stem}.yaml'

    measured_fields = []
    assumed_fields  = []

    # ── Build coherence section ───────────────────────────────────────────
    coherence = {}
    t2_provenance_tags = {}   # yaml_field → provenance label string, for YAML comments

    # Simple one-to-one fields (T1)
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

    # Derived coherence fields with fallback chains (T2: echo → Ramsey)
    for yaml_field, fallback_chain, section, units, comment in DERIVED_COHERENCE_FIELDS:
        val = None
        provenance_label = None
        for db_col, label in fallback_chain:
            candidate = sample.get(db_col)
            if candidate is not None:
                val = float(candidate)
                provenance_label = label
                break
        if val is not None:
            coherence[yaml_field] = val
            measured_fields.append(yaml_field)
            t2_provenance_tags[yaml_field] = f'[MEASURED — {provenance_label}]'
        else:
            coherence[yaml_field] = defaults.get('coherence', {}).get(yaml_field)
            assumed_fields.append(yaml_field)
            t2_provenance_tags[yaml_field] = '[ASSUMED] '

    # ── Build gates section ───────────────────────────────────────────────
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

    # ── Build Stage 4 material sections ──────────────────────────────────
    # These are always written — null if not in corpus.
    # The t1_decomposition fallback hierarchy handles nulls gracefully.
    materials             = {}
    device                = {}
    surface_participation = {}
    material_fields       = []   # tracks which Stage 4 fields have actual values
    material_provenance_tags = {}  # yaml_field → provenance label string, for YAML comments

    # Simple one-to-one material fields
    for db_col, yaml_section, yaml_field, units, comment in MATERIAL_FIELD_MAPPINGS:
        val = sample.get(db_col)
        if val is not None:
            try:
                val = float(val)
            except (TypeError, ValueError):
                pass
            material_fields.append(yaml_field)
            material_provenance_tags[yaml_field] = '[MEASURED]'
        else:
            material_provenance_tags[yaml_field] = '[null]   '

        if yaml_section == 'materials':
            materials[yaml_field] = val
        elif yaml_section == 'device':
            device[yaml_field] = val
        elif yaml_section == 'surface_participation':
            surface_participation[yaml_field] = val

    # Derived material fields with fallback chains (Qi, tan_delta)
    for yaml_field, fallback_chain, section, units, comment in DERIVED_MATERIAL_FIELDS:
        val = None
        provenance_label = None
        for db_col, label in fallback_chain:
            candidate = sample.get(db_col)
            if candidate is not None:
                try:
                    val = float(candidate)
                except (TypeError, ValueError):
                    val = candidate
                provenance_label = label
                break
        if val is not None:
            material_fields.append(yaml_field)
            material_provenance_tags[yaml_field] = f'[MEASURED — {provenance_label}]'
        else:
            material_provenance_tags[yaml_field] = '[null]   '
        materials[yaml_field] = val

    # ── Build provenance section ──────────────────────────────────────────
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
        'defaults_path':       _resolve_defaults_path(sample.get('derived_material'), profiles_dir),
        'measured_fields':     measured_fields,
        'assumed_fields':      assumed_fields,
        'material_fields':     material_fields,
    }
    # Remove None scalar values from provenance for cleaner output
    # (keep lists even if empty)
    provenance = {
        k: v for k, v in provenance.items()
        if v is not None or isinstance(v, list)
    }

    # ── Assemble full profile ─────────────────────────────────────────────
    profile = {
        'profile_type':         'qubits',
        'name':                 filename_stem,
        'description':          _build_description(sample, measured_fields, material_fields),
        'platform':             'superconducting',
        'source':               f"Extracted from corpus: {display_name}",
        'coherence':            coherence,
        'gates':                gates,
        'materials':            materials,
        'device':               device,
        'surface_participation': surface_participation,
        'provenance':           provenance,
    }

    yaml_str = _build_yaml_string(
        profile, display_name,
        measured_fields, assumed_fields, material_fields,
        t2_provenance_tags, material_provenance_tags
    )

    return {
        'yaml_str':        yaml_str,
        'filename':        filename,
        'measured_fields': measured_fields,
        'assumed_fields':  assumed_fields,
        'material_fields': material_fields,
        'display_name':    display_name,
        'profile':         profile,
    }


def _build_description(sample: dict, measured_fields: list,
                        material_fields: list) -> str:
    """Build a human-readable description for the profile."""
    parts = []
    if sample.get('film_material'):
        parts.append(sample['film_material'])
    if sample.get('substrate_material'):
        parts.append(f"on {sample['substrate_material']}")
    if sample.get('authors'):
        first_author = sample['authors'].split(',')[0].split()[-1]
        parts.append(f"({first_author} et al.)")
    if measured_fields:
        parts.append(f"— {len(measured_fields)} device field(s) measured")
    else:
        parts.append("— no device performance data in corpus")
    if material_fields:
        parts.append(f"+ {len(material_fields)} material field(s) for T1 decomposition")
    return ' '.join(parts)


def _build_yaml_string(profile: dict, display_name: str,
                        measured_fields: list, assumed_fields: list,
                        material_fields: list,
                        t2_provenance_tags: dict,
                        material_provenance_tags: dict) -> str:
    """Build the YAML string with header comments and inline provenance tags."""
    lines = []

    # ── Header ───────────────────────────────────────────────────────────
    lines.append(f"# qubits/{profile['name']}.yaml")
    lines.append(f"# Generated by Hardware Profile Updater from corpus sample: {display_name}")
    lines.append(f"# Generated: {profile['provenance']['date_generated']}")
    lines.append(f"#")
    lines.append(f"# Device fields — measured ({len(measured_fields)}): "
                 f"{', '.join(measured_fields) if measured_fields else 'none'}")
    lines.append(f"# Device fields — assumed  ({len(assumed_fields)}): "
                 f"{', '.join(assumed_fields) if assumed_fields else 'none'}")
    lines.append(f"# Material fields — corpus  ({len(material_fields)}): "
                 f"{', '.join(material_fields) if material_fields else 'none'}")
    lines.append(f"#")
    lines.append(f"# [MEASURED] fields came directly from the corpus.")
    lines.append(f"# [ASSUMED]  fields use defaults from "
                 f"{profile['provenance']['defaults_from']}.")
    lines.append(f"# [DERIVED]  fields will be computed at estimation time by t1_decomposition.py.")
    lines.append(f"# Material fields with null values fall back through the tier hierarchy")
    lines.append(f"# in t1_decomposition.py — see loss_channel_model_v2-5.md.")
    lines.append(f"# Review assumed fields before using for quantitative analysis.")
    lines.append('')

    # ── Top-level scalars ─────────────────────────────────────────────────
    for key in ['profile_type', 'name', 'description', 'platform', 'source']:
        lines.append(f"{key}: {_yaml_scalar(profile[key])}")
    lines.append('')

    # ── Coherence section ─────────────────────────────────────────────────
    coherence_comments = {
        'T1_us': 'Energy relaxation time (µs)',
        'T2_us': 'Dephasing time (µs)',
    }
    lines.append('coherence:')
    for field, val in profile['coherence'].items():
        if field in t2_provenance_tags:
            tag = t2_provenance_tags[field]
        else:
            tag = '[MEASURED]' if field in measured_fields else '[ASSUMED] '
        comment = coherence_comments.get(field, '')
        lines.append(f"  {field}: {val}    # {tag} {comment}")
    lines.append('')

    # ── Gates section ─────────────────────────────────────────────────────
    gate_comments = {
        'single_qubit_fidelity_pct': 'Single-qubit gate fidelity (%)',
        'single_qubit_gate_time_ns': 'Single-qubit gate time (ns)',
        'two_qubit_fidelity_pct':    'Two-qubit gate fidelity (%) — primary driver of code distance',
        'two_qubit_gate_time_ns':    'Two-qubit gate time (ns)',
        'readout_fidelity_pct':      'Readout fidelity (%)',
        'readout_time_ns':           'Readout time (ns)',
    }
    lines.append('gates:')
    for field, val in profile['gates'].items():
        tag = '[MEASURED]' if field in measured_fields else '[ASSUMED] '
        comment = gate_comments.get(field, '')
        lines.append(f"  {field}: {val}    # {tag} {comment}")
    lines.append('')

    # ── Materials section (Stage 4) ───────────────────────────────────────
    lines.append('# Stage 4: raw material properties — feed t1_decomposition.py at estimation time.')
    lines.append('# null = not reported in paper; decomposition falls back to class defaults.')
    lines.append('materials:')
    mat_comments = {
        'Tc_K':             'Superconducting critical temperature (K)',
        'Qi':               'Internal quality factor — single-photon preferred, falls back to internal Qi. Q_TLS_0 preferred over Qi for loss model.',
        'Q_TLS_0':          'Unsaturated TLS quality factor — preferred over Qi for loss model',
        'tan_delta':        'Surface loss tangent — best available: tan_delta_effective_surface → loss_tangent_interface → loss_tangent_substrate',
        'mean_free_path_nm':'Electron mean free path (nm) — determines clean vs dirty vortex limit',
    }
    for field, val in profile['materials'].items():
        tag = material_provenance_tags.get(field, '[null]   ')
        comment = mat_comments.get(field, '')
        lines.append(f"  {field}: {_yaml_scalar(val)}    # {tag} {comment}")
    lines.append('')

    # ── Device section (Stage 4) ──────────────────────────────────────────
    lines.append('# Stage 4: device parameters — feed t1_decomposition.py at estimation time.')
    lines.append('device:')
    dev_comments = {
        'f_qubit_GHz': 'Qubit operating frequency (GHz) — required for pad TLS calculation',
    }
    for field, val in profile['device'].items():
        tag = material_provenance_tags.get(field, '[null]   ')
        comment = dev_comments.get(field, '')
        lines.append(f"  {field}: {_yaml_scalar(val)}    # {tag} {comment}")
    lines.append('')

    # ── Surface participation section (Stage 4) ───────────────────────────
    lines.append('# Stage 4: geometry inputs (FEM-derived) — rarely reported in papers.')
    lines.append('# null → class defaults from transmon_analytical_defaults.yaml are used.')
    lines.append('surface_participation:')
    sp_comments = {
        'p_MS_pad':       'Qubit pad metal-substrate participation ratio (FEM). Joshi 2026: 1.3e-4',
        'p_MS_resonator': 'Resonator metal-substrate participation ratio (FEM). Default: 8.63e-4',
    }
    for field, val in profile['surface_participation'].items():
        tag = material_provenance_tags.get(field, '[null]   ')
        comment = sp_comments.get(field, '')
        lines.append(f"  {field}: {_yaml_scalar(val)}    # {tag} {comment}")
    lines.append('')

    # ── Provenance section ────────────────────────────────────────────────
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
        if any(c in val for c in [':', '#', '[', ']', '{', '}', ',', '&', '*',
                                   '?', '|', '>', '!', "'", '"']):
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

    parser = argparse.ArgumentParser(
        description='Generate a QREM qubit profile from a corpus sample'
    )
    parser.add_argument('display_name',
                        help='Sample display name (e.g. Wang_2026_Transmon_5)')
    parser.add_argument('--db', default='../data/ingested/records.db',
                        help='Path to records.db')
    parser.add_argument('--profiles-dir', default='../qrem/hardware_profiles',
                        help='Path to hardware_profiles/')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print YAML without saving')
    args = parser.parse_args()

    sample = fetch_sample_from_db(args.display_name, args.db)
    result = generate_profile(sample, args.profiles_dir)

    print(f"\nGenerated profile for: {result['display_name']}")
    print(f"Filename: {result['filename']}")
    print(f"Device measured  ({len(result['measured_fields'])}): "
          f"{', '.join(result['measured_fields']) or 'none'}")
    print(f"Device assumed   ({len(result['assumed_fields'])}): "
          f"{', '.join(result['assumed_fields'])}")
    print(f"Material fields  ({len(result['material_fields'])}): "
          f"{', '.join(result['material_fields']) or 'none'}")
    print()
    print(result['yaml_str'])

    if not args.dry_run:
        path = save_profile(result, args.profiles_dir)
        print(f"Saved to: {path}")
    else:
        print("[dry-run] Not saved.")
