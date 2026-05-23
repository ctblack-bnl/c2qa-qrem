#!/usr/bin/env python3
"""
compute_class_defaults.py
Generates per-material corpus-average YAML files from records.db.

For each material class with n >= MIN_SAMPLES samples, produces two files:

  hardware_profiles/qubits/Ta_corpus_average.yaml
    — device performance profile with corpus-averaged T1, T2.
    — appears in Baby QREM qubit dropdown as "Ta (corpus average, N=35)"
    — Mode 1 use case: "I want to make qubits from tantalum"

  hardware_profiles/material_defaults/Ta_material_defaults.yaml
    — material property defaults for t1_decomposition.py.
    — corpus-averaged fields: tan_delta, Tc_K, mean_free_path_nm
    — non-averaged fields (geometry, junction, QP floor, radiation)
      carried through from transmon_general_defaults.yaml with CLASS_DEFAULT label.
    — Mode 2 use case: "I made a Ta film — fill in what I didn't measure"

Provenance labels:
  [CORPUS AVERAGE — Ta, N=35]  — computed from corpus
  [CLASS DEFAULT]              — carried from transmon_general_defaults.yaml
  [ASSUMED]                    — baseline device defaults

Mixed-variant composition is tracked and noted in provenance, e.g.:
  "5 x tan_delta_effective_surface, 3 x loss_tangent_interface"

Usage:
    cd ingester
    python3 compute_class_defaults.py
    python3 compute_class_defaults.py --db ../data/ingested/records.db \\
        --profiles-dir ../src/qrem/hardware_profiles --min-samples 3

Called automatically at end of build_sqlite.py (planned).
"""

import argparse
import math
import sqlite3
import yaml
from datetime import date
from pathlib import Path


# ── Configuration ─────────────────────────────────────────────────────────────

MIN_SAMPLES = 3   # Minimum samples to report a corpus average (vs fall back to CLASS_DEFAULT)

# Fields to average for the qubits/ corpus-average YAML (device properties)
# Each entry: (db_column, yaml_section, yaml_field, units, comment)
DEVICE_AVG_FIELDS = [
    ('T1_us',               'coherence', 'T1_us',                    'µs', 'Energy relaxation time'),
    ('derived_T2_us',       'coherence', 'T2_us',                    'µs', 'Dephasing time (echo preferred; falls back to Ramsey)'),
    ('gate_1q_fidelity_pct','gates',     'single_qubit_fidelity_pct','%',  'Single-qubit gate fidelity'),
    ('gate_2q_fidelity_pct','gates',     'two_qubit_fidelity_pct',   '%',  'Two-qubit gate fidelity'),
]

# Fields to average for the material_defaults/ YAML (material properties)
# Each entry: (db_column, yaml_key_in_defaults, units, comment)
MATERIAL_AVG_FIELDS = [
    ('Tc_K',             'Tc_K_pad_fallback',          'K',
     'Critical temperature — corpus average for this material class'),
    ('derived_tan_delta', 'tan_delta_effective_surface', 'dimensionless',
     'Surface loss tangent — corpus average (see composition in provenance)'),
    ('mean_free_path_nm', 'mean_free_path_nm',           'nm',
     'Electron mean free path — corpus average for this material class'),
    ('derived_Qi',        'Qi',                          'dimensionless',
     'Internal quality factor — corpus average (see composition in provenance)'),
]

# Composition tracking: which raw variants feed each derived_X field
# Maps derived column → list of (raw_db_column, short_label) in priority order
COMPOSITION_SOURCES = {
    'derived_tan_delta': [
        ('tan_delta_effective_surface', 'tan_delta_effective_surface'),
        ('loss_tangent_interface',      'loss_tangent_interface'),
        ('loss_tangent_substrate',      'loss_tangent_substrate'),
    ],
    'derived_T2_us': [
        ('T2_echo_us',   'T2_echo'),
        ('T2_ramsey_us', 'T2_ramsey'),
    ],
    'derived_Qi': [
        ('Qi_single_photon',           'Qi_single_photon'),
        ('Qi_internal',                'Qi_internal'),
    ],
}

# Paths relative to the ingester/ directory
DEFAULT_DB_PATH       = Path('../data/ingested/records.db')
DEFAULT_PROFILES_DIR  = Path('../src/qrem/hardware_profiles')
GENERAL_DEFAULTS_NAME = 'transmon_general_defaults.yaml'
BASELINE_PROFILE_NAME = 'transmon_baseline_2026.yaml'


# ── Statistics helpers ─────────────────────────────────────────────────────────

def _mean_std(values: list) -> tuple:
    """Return (mean, std, n) for a list of floats. std=None if n < 2."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return None, None, 0
    mean = sum(vals) / n
    if n < 2:
        return mean, None, n
    variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return mean, math.sqrt(variance), n


def _composition_string(rows: list, db_col: str) -> str:
    """
    For a derived_X field, count how many samples contributed each raw variant.
    Returns a human-readable string like "5 x tan_delta_effective_surface, 3 x loss_tangent_interface".
    rows: list of sqlite3.Row objects for this material class.
    """
    if db_col not in COMPOSITION_SOURCES:
        return ''
    sources = COMPOSITION_SOURCES[db_col]
    counts = {}
    for row in rows:
        val = row[db_col]
        if val is None:
            continue
        # Find which raw variant this sample used (first non-null in priority order)
        for raw_col, label in sources:
            raw_val = row[raw_col] if raw_col in row.keys() else None
            if raw_val is not None:
                counts[label] = counts.get(label, 0) + 1
                break
    if not counts:
        return ''
    parts = [f"{n} x {label}" for label, n in sorted(counts.items(),
                                                       key=lambda x: -x[1])]
    return ', '.join(parts)


def _prov_label(material: str, n: int) -> str:
    """Corpus average provenance label."""
    return f'CORPUS_AVERAGE — {material}, N={n}'


# ── Database queries ───────────────────────────────────────────────────────────

def query_material_classes(conn: sqlite3.Connection) -> list:
    """Return list of (derived_material, n_samples) for known materials."""
    cur = conn.cursor()
    cur.execute("""
        SELECT derived_material, COUNT(*) as n
        FROM samples
        WHERE derived_material NOT IN ('other', 'unknown')
        GROUP BY derived_material
        ORDER BY n DESC
    """)
    return cur.fetchall()


def query_samples_for_material(conn: sqlite3.Connection, material: str) -> list:
    """Return all sample rows for a material class."""
    cur = conn.cursor()
    # Fetch all columns we need for averaging + composition tracking
    cols = [
        'display_name',
        'T1_us', 'derived_T2_us', 'T2_echo_us', 'T2_ramsey_us',
        'Tc_K', 'derived_tan_delta', 'tan_delta_effective_surface',
        'loss_tangent_interface', 'loss_tangent_substrate',
        'mean_free_path_nm', 'derived_Qi', 'Qi_single_photon', 'Qi_internal',
    ]
    cur.execute(f"""
        SELECT {', '.join(cols)}
        FROM samples
        WHERE derived_material = ?
    """, (material,))
    return cur.fetchall()


def _to_float(val) -> float:
    """Safely coerce a DB value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ── YAML generation helpers ────────────────────────────────────────────────────

def _fmt_float(val, sig: int = 3) -> str:
    """Format a float for YAML — use scientific notation for very small values."""
    if val is None:
        return 'null'
    try:
        val = float(val)
    except (TypeError, ValueError):
        return str(val)
    if val != 0 and abs(val) < 1e-2:
        return f'{val:.{sig}e}'
    return f'{val:.{sig}g}'


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, return empty dict if not found."""
    if not path.exists():
        print(f"  Warning: {path} not found — using empty dict")
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ── Corpus-average qubit profile (qubits/ directory) ──────────────────────────

def generate_corpus_average_qubit_yaml(
        material: str,
        rows: list,
        baseline: dict,
        profiles_dir: Path) -> str:
    """
    Generate Ta_corpus_average.yaml content.
    Structure mirrors generate_qubit_profile.py output for consistency.
    """
    today = str(date.today())
    n_total = len(rows)

    # ── Compute device averages ───────────────────────────────────────────
    coherence_out = {}
    coherence_provenance = {}   # field → (label, note)

    for db_col, section, yaml_field, units, comment in DEVICE_AVG_FIELDS:
        vals = [_to_float(row[db_col]) for row in rows]
        mean, std, n = _mean_std(vals)

        if n >= MIN_SAMPLES and mean is not None:
            coherence_out[yaml_field] = round(mean, 2)
            comp = _composition_string(rows, db_col)
            comp_note = f' ({comp})' if comp else ''
            std_note = f' ± {std:.1f}' if std is not None else ''
            coherence_provenance[yaml_field] = (
                f'[CORPUS AVERAGE — {material}, N={n}]',
                f'Mean {mean:.1f}{std_note} µs across {n} samples{comp_note}'
            )
        else:
            # Fall back to baseline
            fallback = baseline.get('coherence', {}).get(yaml_field)
            coherence_out[yaml_field] = fallback
            coherence_provenance[yaml_field] = (
                '[ASSUMED]',
                f'Insufficient corpus data (N={n} < {MIN_SAMPLES}) — using baseline default'
            )

    # Gates — corpus average when N >= MIN_SAMPLES, otherwise baseline assumed
    gates_baseline = baseline.get('gates', {})
    gates_out = {}
    gates_provenance = {}  # yaml_field → (tag, note)
    for db_col, section, yaml_field, units, comment in DEVICE_AVG_FIELDS:
        if section != 'gates':
            continue
        vals = [_to_float(row[db_col]) for row in rows]
        mean, std, n = _mean_std(vals)
        if n >= MIN_SAMPLES and mean is not None:
            gates_out[yaml_field] = round(mean, 3)
            std_note = f' ± {std:.3f}' if std is not None else ''
            gates_provenance[yaml_field] = (
                f'[CORPUS AVERAGE — {material}, N={n}]',
                f'Mean {mean:.3f}{std_note}% across {n} samples'
            )
        else:
            gates_out[yaml_field] = gates_baseline.get(yaml_field)
            gates_provenance[yaml_field] = (
                '[ASSUMED]',
                f'Insufficient corpus data (N={n} < {MIN_SAMPLES}) — gate engineering, not material'
            )

    # Material fields — corpus averages for the Stage 4 decomposition panel
    # These give the decomposition model something real to work with
    material_avgs = {}   # yaml_field → (value, provenance_label, note)
    for db_col, yaml_key, units, comment in MATERIAL_AVG_FIELDS:
        vals = [_to_float(row[db_col]) for row in rows]
        mean, std, n = _mean_std(vals)
        if n >= MIN_SAMPLES and mean is not None:
            comp = _composition_string(rows, db_col)
            comp_note = f' ({comp})' if comp else ''
            std_note = f' ± {_fmt_float(std)}' if std is not None else ''
            material_avgs[yaml_key] = (
                mean,
                f'CORPUS_AVERAGE — {material}, N={n}',
                f'Mean {_fmt_float(mean)}{std_note}{comp_note}'
            )
        else:
            material_avgs[yaml_key] = (
                None,
                'null',
                f'Insufficient data (N={n} < {MIN_SAMPLES})'
            )

    # Map yaml_key names back to the materials section fields
    mat_section = {
        'Tc_K':                        material_avgs.get('Tc_K_pad_fallback', (None, 'null', ''))[0],
        'tan_delta':                   material_avgs.get('tan_delta_effective_surface', (None, 'null', ''))[0],
        'mean_free_path_nm':           material_avgs.get('mean_free_path_nm', (None, 'null', ''))[0],
        'Qi':                          material_avgs.get('Qi', (None, 'null', ''))[0],
        'Q_TLS_0':                     None,  # rarely reported; left null
        'f_qubit_GHz':                 None,  # device-specific; not averaged
    }
    mat_prov = {
        'Tc_K':           material_avgs.get('Tc_K_pad_fallback', (None, 'null', '')),
        'tan_delta':      material_avgs.get('tan_delta_effective_surface', (None, 'null', '')),
        'mean_free_path_nm': material_avgs.get('mean_free_path_nm', (None, 'null', '')),
        'Qi':             material_avgs.get('Qi', (None, 'null', '')),
        'Q_TLS_0':        (None, 'null', 'Rarely reported — left null'),
        'f_qubit_GHz':    (None, 'null', 'Device-specific — not averaged across corpus'),
    }

    # ── Build YAML string ─────────────────────────────────────────────────
    lines = []
    lines += [
        f'# qubits/{material}_corpus_average.yaml',
        f'# Generated by compute_class_defaults.py',
        f'# Generated: {today}',
        f'#',
        f'# Corpus-average device profile for material class: {material}',
        f'# Based on {n_total} samples in records.db',
        f'# Minimum threshold for corpus average: N >= {MIN_SAMPLES}',
        f'#',
        f'# [CORPUS AVERAGE] fields: mean computed from corpus, labeled with N.',
        f'# [ASSUMED]        fields: insufficient corpus data — baseline default used.',
        f'# null material fields: not enough data to average.',
        f'#',
        f'# Mode 1 use: select this profile in Baby QREM to benchmark',
        f'# what a typical {material} qubit achieves in the current corpus.',
        f'# Mode 2 use: load a partial measurement and fill gaps from this profile.',
        '',
        f'profile_type: qubits',
        f'name: {material}_corpus_average',
        f'description: "{material} — corpus average across {n_total} samples ({today})"',
        f'platform: superconducting',
        f'source: "Corpus average computed from records.db by compute_class_defaults.py"',
        '',
        'coherence:',
    ]

    for yaml_field in ['T1_us', 'T2_us']:
        val = coherence_out.get(yaml_field)
        tag, note = coherence_provenance.get(yaml_field, ('[ASSUMED]', ''))
        val_str = _fmt_float(val) if val is not None else 'null'
        lines.append(f'  {yaml_field}: {val_str}    # {tag}  {note}')

    lines += ['', 'gates:']
    gate_comments = {
        'single_qubit_fidelity_pct': 'Single-qubit gate fidelity (%)',
        'single_qubit_gate_time_ns': 'Single-qubit gate time (ns)',
        'two_qubit_fidelity_pct':    'Two-qubit gate fidelity (%) — primary driver of code distance',
        'two_qubit_gate_time_ns':    'Two-qubit gate time (ns)',
        'readout_fidelity_pct':      'Readout fidelity (%)',
        'readout_time_ns':           'Readout time (ns)',
    }
    for field, comment in gate_comments.items():
        if field in gates_provenance:
            tag, note = gates_provenance[field]
            val = gates_out.get(field)
        else:
            tag, note = '[ASSUMED]', 'gate engineering, not material'
            val = gates_baseline.get(field)
        lines.append(f'  {field}: {val}    # {tag}  {comment} — {note}')

    lines += [
        '',
        '# Stage 4: corpus-averaged material properties — feed t1_decomposition.py.',
        '# null = insufficient corpus data for this material class.',
        'materials:',
    ]
    mat_comments = {
        'Tc_K':              'Superconducting critical temperature (K)',
        'tan_delta':         'Surface loss tangent — best available variant (see composition in provenance)',
        'mean_free_path_nm': 'Electron mean free path (nm) — determines clean vs dirty vortex limit',
        'Qi':                'Internal quality factor (see composition in provenance)',
        'Q_TLS_0':           'Unsaturated TLS quality factor — rarely reported, left null',
    }
    for field in ['Tc_K', 'tan_delta', 'mean_free_path_nm', 'Qi', 'Q_TLS_0']:
        val, prov_label, note = mat_prov.get(field, (None, 'null', ''))
        val_str = _fmt_float(val) if val is not None else 'null'
        tag = f'[{prov_label}]' if prov_label != 'null' else '[null]'
        comment = mat_comments.get(field, '')
        lines.append(f'  {field}: {val_str}    # {tag}  {comment}')

    lines += [
        '',
        '# Stage 4: device parameters.',
        'device:',
        f'  f_qubit_GHz: null    # [null]  Device-specific — not averaged across corpus',
        '',
        '# Stage 4: geometry inputs — device-specific, not material averages.',
        'surface_participation:',
        f'  p_MS_pad: null       # [null]  FEM-derived, device-specific',
        f'  p_MS_resonator: null # [null]  FEM-derived, device-specific',
        '',
        'provenance:',
        f'  generated_by: compute_class_defaults.py',
        f'  date_generated: {today}',
        f'  derived_material: {material}',
        f'  n_samples_total: {n_total}',
        f'  min_samples_threshold: {MIN_SAMPLES}',
        f'  defaults_from: {BASELINE_PROFILE_NAME}',
        f'  defaults_path: ../material_defaults/{material}_material_defaults.yaml',
        f'  corpus_composition:',
    ]

    # Composition breakdown per averaged field
    for db_col, _, yaml_field, _, _ in DEVICE_AVG_FIELDS:
        comp = _composition_string(rows, db_col)
        if comp:
            lines.append(f'    {yaml_field}: "{comp}"')
    for db_col, yaml_key, _, _ in MATERIAL_AVG_FIELDS:
        comp = _composition_string(rows, db_col)
        if comp:
            lines.append(f'    {yaml_key}: "{comp}"')

    return '\n'.join(lines) + '\n'


# ── Per-material analytical defaults (material_defaults/ directory) ────────────

def generate_material_defaults_yaml(
        material: str,
        rows: list,
        general_defaults: dict,
        profiles_dir: Path) -> str:
    """
    Generate Ta_material_defaults.yaml content.
    Structure mirrors transmon_general_defaults.yaml.
    Material-dependent fields: replaced with corpus averages where N >= MIN_SAMPLES.
    All other fields: carried through from general_defaults with CLASS_DEFAULT label.
    """
    today = str(date.today())
    n_total = len(rows)

    # ── Compute material averages ─────────────────────────────────────────
    avgs = {}   # yaml_key → (mean, std, n, composition_str)
    for db_col, yaml_key, units, comment in MATERIAL_AVG_FIELDS:
        vals = [_to_float(row[db_col]) for row in rows]
        mean, std, n = _mean_std(vals)
        comp = _composition_string(rows, db_col)
        avgs[yaml_key] = (mean, std, n, comp)

    def _avg_field(yaml_key: str, fallback_path: list, fallback_default=None):
        """
        Return (value, provenance_label, notes_str) for a material-averaged field.
        Falls back to general_defaults if insufficient corpus data.
        """
        mean, std, n, comp = avgs.get(yaml_key, (None, None, 0, ''))
        if n >= MIN_SAMPLES and mean is not None:
            std_note = f' ± {_fmt_float(std)}' if std is not None else ''
            comp_note = f' ({comp})' if comp else ''
            return (
                mean,
                f'CORPUS_AVERAGE — {material}, N={n}',
                f'Mean {_fmt_float(mean)}{std_note} across {n} {material} samples{comp_note}'
            )
        else:
            # Carry through from general_defaults
            node = general_defaults
            for key in fallback_path:
                if isinstance(node, dict):
                    node = node.get(key)
                else:
                    node = None
                    break
            if isinstance(node, dict):
                val = node.get('value', fallback_default)
                orig_note = node.get('notes', '')
            else:
                val = node if node is not None else fallback_default
                orig_note = ''
            return (
                val,
                'CLASS_DEFAULT',
                f'Insufficient corpus data (N={n} < {MIN_SAMPLES}) — from transmon_general_defaults.yaml. {orig_note}'.strip()
            )

    # Material-specific averageable fields
    tc_val, tc_prov, tc_note             = _avg_field('Tc_K_pad_fallback',
                                                        ['quasiparticle', 'Tc_K_pad_fallback'])
    tan_val, tan_prov, tan_note          = _avg_field('tan_delta_effective_surface',
                                                        ['tan_delta_effective_surface'])
    mfp_val, mfp_prov, mfp_note         = _avg_field('mean_free_path_nm', [], None)

    # Non-averaged fields — always from general_defaults
    def _carry(path: list, fallback=None):
        """Carry a value from general_defaults unchanged."""
        node = general_defaults
        for key in path:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                return fallback, 'CLASS_DEFAULT', ''
        if isinstance(node, dict):
            return node.get('value', fallback), 'CLASS_DEFAULT', node.get('notes', '')
        return (node if node is not None else fallback), 'CLASS_DEFAULT', ''

    # ── Build YAML string ─────────────────────────────────────────────────
    lines = []
    lines += [
        f'# hardware_profiles/material_defaults/{material}_material_defaults.yaml',
        f'# Generated by compute_class_defaults.py',
        f'# Generated: {today}',
        f'#',
        f'# Material-specific T1 decomposition defaults for: {material}',
        f'# Based on {n_total} samples in records.db',
        f'#',
        f'# [CORPUS AVERAGE] fields: computed from corpus — improve as more papers are ingested.',
        f'# [CLASS DEFAULT]  fields: carried from transmon_general_defaults.yaml unchanged.',
        f'#   These are geometry/system parameters not derivable from material measurements.',
        f'#',
        f'# Used by t1_decomposition.py when a {material} sample is missing a field.',
        f'# Regenerate by running: python3 compute_class_defaults.py',
        '',
        f'model_type: transmon_analytical',
        f'description: "T1 decomposition defaults — {material}, corpus average ({today})"',
        f'material: {material}',
        f'substrate: mixed',
        f'notes: >',
        f'  Per-material defaults for {material}. Corpus-averaged fields use mean across',
        f'  {n_total} samples grouped by derived_material = "{material}" in records.db.',
        f'  Non-material fields (geometry, junction, QP floor, radiation) are carried',
        f'  from transmon_general_defaults.yaml unchanged.',
        '',
    ]

    # ── Surface participation (geometry — always CLASS_DEFAULT) ───────────
    p_ms_res_val, _, p_ms_res_note = _carry(['surface_participation', 'p_MS_resonator'])
    p_ms_pad_val, _, p_ms_pad_note = _carry(['surface_participation', 'p_MS_pad'])

    lines += [
        '# =============================================================================',
        '# SURFACE PARTICIPATION RATIOS — geometry-dependent, not material averages',
        '# =============================================================================',
        'surface_participation:',
        '  p_MS_resonator:',
        f'    value: {_fmt_float(p_ms_res_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: >',
        f'      {p_ms_res_note.strip()}',
        '  p_MS_pad:',
        f'    value: {_fmt_float(p_ms_pad_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: >',
        f'      {p_ms_pad_note.strip()}',
        '',
    ]

    # ── Junction TLS (always CLASS_DEFAULT) ───────────────────────────────
    pj_val, _, pj_note   = _carry(['junction_tls', 'p_junction_surface'])
    tdj_val, _, tdj_note = _carry(['junction_tls', 'tan_delta_junction'])

    lines += [
        '# =============================================================================',
        '# JUNCTION TLS — Al/AlOx tunnel barrier, not material-dependent',
        '# =============================================================================',
        'junction_tls:',
        '  p_junction_surface:',
        f'    value: {_fmt_float(pj_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: "{pj_note.strip()}"',
        '  tan_delta_junction:',
        f'    value: {_fmt_float(tdj_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: "{tdj_note.strip()}"',
        '',
    ]

    # ── Effective surface loss tangent (CORPUS AVERAGE if available) ───────
    tan_val_str = _fmt_float(tan_val) if tan_val is not None else 'null'
    lines += [
        '# =============================================================================',
        f'# EFFECTIVE SURFACE LOSS TANGENT — corpus average for {material}',
        '# =============================================================================',
        'tan_delta_effective_surface:',
        f'  value: {tan_val_str}',
        f'  provenance: "{tan_prov}"',
        f'  material: {material}',
        f'  notes: >',
        f'    {tan_note.strip()}',
        '',
    ]

    # ── Interface loss tangents (always CLASS_DEFAULT) ────────────────────
    td_ms_val, _, td_ms_note = _carry(['interface_loss_tangents', 'tan_delta_MS'])
    td_sa_val, _, td_sa_note = _carry(['interface_loss_tangents', 'tan_delta_SA'])
    td_ma_val, _, td_ma_note = _carry(['interface_loss_tangents', 'tan_delta_MA'])
    td_bk_val, _, td_bk_note = _carry(['interface_loss_tangents', 'tan_delta_bulk'])

    lines += [
        '# =============================================================================',
        '# INTERFACE LOSS TANGENTS — geometry/substrate specific, CLASS_DEFAULT',
        '# =============================================================================',
        'interface_loss_tangents:',
        '  tan_delta_MS:',
        f'    value: {_fmt_float(td_ms_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: "{td_ms_note.strip()}"',
        '  tan_delta_SA:',
        f'    value: {_fmt_float(td_sa_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: "{td_sa_note.strip()}"',
        '  tan_delta_MA:',
        f'    value: {_fmt_float(td_ma_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: "{td_ma_note.strip()}"',
        '  tan_delta_bulk:',
        f'    value: {_fmt_float(td_bk_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: "{td_bk_note.strip()}"',
        '',
    ]

    # ── Quasiparticle (Tc is corpus average; rest CLASS_DEFAULT) ──────────
    t_op_val, _, t_op_note    = _carry(['quasiparticle', 'T_operating_mK'])
    tc_junc_val, _, tc_j_note = _carry(['quasiparticle', 'Tc_K_junction'])
    t1_noneq_val, _, noneq_note = _carry(['quasiparticle', 'T1_QP_nonequilibrium_us'])
    tc_val_str = _fmt_float(tc_val) if tc_val is not None else 'null'

    lines += [
        '# =============================================================================',
        f'# QUASIPARTICLE — Tc_K_pad_fallback corpus average for {material}; rest CLASS_DEFAULT',
        '# =============================================================================',
        'quasiparticle:',
        '  T_operating_mK:',
        f'    value: {_fmt_float(t_op_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: "{t_op_note.strip()}"',
        '  Tc_K_junction:',
        f'    value: {_fmt_float(tc_junc_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: "{tc_j_note.strip()}"',
        '  Tc_K_pad_fallback:',
        f'    value: {tc_val_str}',
        f'    provenance: "{tc_prov}"',
        f'    notes: >',
        f'      {tc_note.strip()}',
        '  T1_QP_nonequilibrium_us:',
        f'    value: {_fmt_float(t1_noneq_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: >',
        f'      {noneq_note.strip()}',
        '',
    ]

    # ── Vortex (mean_free_path informs clean/dirty; T1 defaults CLASS_DEFAULT) ─
    coh_len_val, _, coh_len_note   = _carry(['vortex', 'coherence_length_nm'])
    t1v_clean_val, _, t1vc_note    = _carry(['vortex', 'T1_vortex_us_default_clean'])
    t1v_dirty_val, _, t1vd_note    = _carry(['vortex', 'T1_vortex_us_default_dirty'])
    t1v_unk_val, _, t1vu_note      = _carry(['vortex', 'T1_vortex_us_default_unknown'])
    mfp_val_str = _fmt_float(mfp_val) if mfp_val is not None else 'null'

    lines += [
        '# =============================================================================',
        f'# VORTEX — mean_free_path corpus average for {material}; T1 defaults CLASS_DEFAULT',
        '# =============================================================================',
        'vortex:',
        '  mean_free_path_nm:',
        f'    value: {mfp_val_str}',
        f'    provenance: "{mfp_prov}"',
        f'    notes: >',
        f'      {mfp_note.strip() if mfp_note.strip() else "Insufficient corpus data (N<3) — not enough mean_free_path_nm measurements for " + material + " to compute corpus average."}',
        '  coherence_length_nm:',
        f'    value: {_fmt_float(coh_len_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: >',
        f'      {coh_len_note.strip()}',
        '  T1_vortex_us_default_clean:',
        f'    value: {_fmt_float(t1v_clean_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: >',
        f'      {t1vc_note.strip()}',
        '  T1_vortex_us_default_dirty:',
        f'    value: {_fmt_float(t1v_dirty_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: >',
        f'      {t1vd_note.strip()}',
        '  T1_vortex_us_default_unknown:',
        f'    value: {_fmt_float(t1v_unk_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: >',
        f'      {t1vu_note.strip()}',
        '',
    ]

    # ── Radiation (always CLASS_DEFAULT) ─────────────────────────────────
    t1_rad_val, _, t1_rad_note = _carry(['radiation', 'T1_radiation_us'])

    lines += [
        '# =============================================================================',
        '# RADIATION — system/packaging parameter, not material. Always CLASS_DEFAULT.',
        '# =============================================================================',
        'radiation:',
        '  T1_radiation_us:',
        f'    value: {_fmt_float(t1_rad_val)}',
        '    provenance: CLASS_DEFAULT',
        f'    notes: >',
        f'      {t1_rad_note.strip()}',
        '',
        '# =============================================================================',
        '# PROVENANCE',
        '# =============================================================================',
        'corpus_provenance:',
        f'  generated_by: compute_class_defaults.py',
        f'  date_generated: {today}',
        f'  derived_material: {material}',
        f'  n_samples_total: {n_total}',
        f'  min_samples_threshold: {MIN_SAMPLES}',
        f'  general_defaults_source: {GENERAL_DEFAULTS_NAME}',
    ]

    # Composition notes
    comp_lines = []
    for db_col, yaml_key, _, _ in MATERIAL_AVG_FIELDS:
        comp = _composition_string(rows, db_col)
        if comp:
            comp_lines.append(f'    {yaml_key}: "{comp}"')
    if comp_lines:
        lines.append('  corpus_composition:')
        lines.extend(comp_lines)

    return '\n'.join(lines) + '\n'


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate per-material corpus-average YAML files for Baby QREM.'
    )
    parser.add_argument('--db',
        type=Path, default=DEFAULT_DB_PATH,
        help=f'Path to records.db (default: {DEFAULT_DB_PATH})')
    parser.add_argument('--profiles-dir',
        type=Path, default=DEFAULT_PROFILES_DIR,
        help=f'Path to hardware_profiles/ directory (default: {DEFAULT_PROFILES_DIR})')
    parser.add_argument('--min-samples',
        type=int, default=3,
        help='Minimum samples for a corpus average (default: 3)')
    parser.add_argument('--dry-run',
        action='store_true',
        help='Print output without writing files')
    parser.add_argument('--material',
        type=str, default=None,
        help='Process only this material class (e.g. Ta)')
    global MIN_SAMPLES
    args = parser.parse_args()
    MIN_SAMPLES = args.min_samples

    profiles_dir  = args.profiles_dir
    qubits_dir    = profiles_dir / 'qubits'
    mat_def_dir   = profiles_dir / 'material_defaults'

    # Load reference YAMLs
    general_defaults = _load_yaml(profiles_dir / 'material_defaults' / GENERAL_DEFAULTS_NAME)
    if not general_defaults:
        # Try legacy path
        general_defaults = _load_yaml(profiles_dir / 'mapping_models' / 'transmon_analytical_defaults.yaml')
    baseline = _load_yaml(profiles_dir / 'qubits' / BASELINE_PROFILE_NAME)

    if not general_defaults:
        print(f'Warning: could not load general defaults YAML — non-averaged fields will be null')
    if not baseline:
        print(f'Warning: could not load baseline profile YAML — gate defaults will be null')

    # Connect to DB
    if not args.db.exists():
        print(f'Error: database not found: {args.db}')
        return
    conn = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row

    # Get material classes
    material_classes = query_material_classes(conn)
    print(f'\nMaterial classes in corpus:')
    for mat, n in material_classes:
        marker = '✓' if n >= MIN_SAMPLES else '✗'
        print(f'  {marker} {mat:<15} N={n}'
              + ('' if n >= MIN_SAMPLES else f' (below threshold of {MIN_SAMPLES})'))

    print()

    # Filter if --material specified
    if args.material:
        material_classes = [(m, n) for m, n in material_classes if m == args.material]
        if not material_classes:
            print(f'Material "{args.material}" not found in corpus.')
            conn.close()
            return

    # Create output directories
    if not args.dry_run:
        qubits_dir.mkdir(parents=True, exist_ok=True)
        mat_def_dir.mkdir(parents=True, exist_ok=True)

    generated = []

    for material, n_total in material_classes:
        if n_total < MIN_SAMPLES:
            print(f'Skipping {material} — only {n_total} sample(s), need {MIN_SAMPLES}')
            continue

        rows = query_samples_for_material(conn, material)
        print(f'Processing {material} ({len(rows)} samples)...')

        # Generate qubit corpus-average YAML
        qubit_yaml = generate_corpus_average_qubit_yaml(
            material, rows, baseline, profiles_dir)
        qubit_filename = f'{material}_corpus_average.yaml'

        # Generate material defaults YAML
        mat_yaml = generate_material_defaults_yaml(
            material, rows, general_defaults, profiles_dir)
        mat_filename = f'{material}_material_defaults.yaml'

        if args.dry_run:
            print(f'\n{"="*60}')
            print(f'  qubits/{qubit_filename}')
            print(f'{"="*60}')
            print(qubit_yaml)
            print(f'\n{"="*60}')
            print(f'  material_defaults/{mat_filename}')
            print(f'{"="*60}')
            print(mat_yaml)
        else:
            (qubits_dir / qubit_filename).write_text(qubit_yaml)
            (mat_def_dir / mat_filename).write_text(mat_yaml)
            print(f'  Wrote: qubits/{qubit_filename}')
            print(f'  Wrote: material_defaults/{mat_filename}')
            generated.append(material)

    conn.close()

    if not args.dry_run and generated:
        print(f'\nDone. Generated files for: {", ".join(generated)}')
        print(f'These profiles now appear in the Baby QREM qubit dropdown.')
        print(f'Regenerate after any build_sqlite.py run to keep averages current.')
        print()
        print('Next step: rename mapping_models/ → material_defaults/ and')
        print('rename transmon_analytical_defaults.yaml → transmon_general_defaults.yaml')
        print('then update ANALYTICAL_DEFAULTS_RELATIVE in generate_qubit_profile.py.')


if __name__ == '__main__':
    main()
