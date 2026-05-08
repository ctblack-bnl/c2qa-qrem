#!/usr/bin/env python3
# ingester/pipeline_mining.py  —  Stage 04: Corpus Mining
# Phase A — Evidence Extraction (mechanical, no AI)
#
# Reads the corpus database and produces three outputs:
#
#   1. EVIDENCE TABLES  — one per matched hypothesis, ready for Phase B AI reasoning.
#      Seeded by author-stated correlations, cross-sample evidence scanned from
#      full materials corpus. Only materials characterization samples included.
#
#   2. CORPUS GAP REPORT  — hypotheses that are stated or partially mappable
#      but lack cross-sample evidence. Documents what we'd like to know but
#      can't yet measure. Feeds schema promotion decisions.
#
#   3. MEASUREMENT FREQUENCY REPORT  — which fields appear most often in
#      additional_measurements across the corpus, regardless of whether any
#      author stated an explicit correlation. These are signals the community
#      keeps measuring for a reason — candidates for new hypotheses.
#
# OUT OF SCOPE (documented but not fed to Phase B):
#   - Device/circuit physics papers (dispersive coupling, Rabi rates,
#     Bell fidelity, parity lifetime, etc.)
#   - Exotic domain papers (SiV spin, IIP3, Floquet simulation)
#
# Bug fixes vs previous version:
#   - Parser now handles "vs" inside parentheses correctly
#   - Unmatched list split into proper buckets (gap vs out-of-scope)
#
# Usage:
#   cd ingester
#   python3 pipeline_mining.py phase-a
#   python3 pipeline_mining.py phase-a --db ../data/ingested/records.db
#   python3 pipeline_mining.py phase-a --out ../data/ingested/mining_evidence.jsonl
#   python3 pipeline_mining.py phase-a --verbose
#
# Pass criteria before running Phase B:
#   [ ] Evidence table count is reasonable
#   [ ] Corpus gaps list makes sense on inspection
#   [ ] Out of scope list contains only non-materials items
#   [ ] Measurement frequency report surfaces plausible candidates
#   [ ] No evidence table has 0 records fed to Phase B

import argparse
import json
import re
import sqlite3
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

# ── Field name mapping ─────────────────────────────────────────────────────────
#
# Maps terms that appear in correlation descriptions/values to the canonical
# SQLite column name (or sample_json key prefixed with "json:").
#
# Rules:
#   - Keys are lowercase, stripped. Match is case-insensitive substring.
#   - Values are exact SQLite column names or "json:key" for sample_json fields.
#   - More specific entries should come before general ones.
#   - To add a new mapping: add the term and its column name here.
#   - To override a wrong mapping: correct it here and re-run Phase A.

FIELD_MAP: Dict[str, str] = {
    # Superconducting properties
    "tc_k":                         "Tc_K",
    "tc ":                          "Tc_K",
    "critical temperature":         "Tc_K",
    "superconducting transition":   "Tc_K",
    "transition temperature":       "Tc_K",
    "rrr":                          "RRR",
    "residual resistance ratio":    "RRR",
    "residual resistivity ratio":   "RRR",
    "film purity":                  "RRR",
    "mean free path":               "mean_free_path_nm",
    "sheet resistance":             "sheet_resistance_Ohm_sq",
    "kinetic inductance":           "kinetic_inductance_sheet_pH_sq",
    "lk,sq":                        "kinetic_inductance_sheet_pH_sq",
    "lk ":                          "kinetic_inductance_sheet_pH_sq",
    "london penetration depth":     "json:London_penetration_depth_nm",
    "penetration depth":            "json:London_penetration_depth_nm",
    "upper critical field":         "json:upper_critical_field_T",
    "hc2":                          "json:upper_critical_field_T",
    "coherence length":             "derived_coherence_length_nm",
    "vortex activation":            "vortex_activation_temperature_K",
    "vortex motion":                "vortex_activation_temperature_K",
    "tact":                         "vortex_activation_temperature_K",

    # Dielectric and surface loss
    "loss tangent":                 "loss_tangent_substrate",
    "tls density":                  "TLS_density",
    "two-level system density":     "TLS_density",
    "surface oxide":                "surface_oxide_nm",
    "oxide thickness":              "surface_oxide_nm",
    "native oxide":                 "surface_oxide_nm",
    "taox thickness":               "surface_oxide_nm",
    "surface participation":        "json:surface_participation_ratio",
    "participation ratio":          "json:surface_participation_ratio",
    "pms":                          "json:surface_participation_ratio",

    # Microwave performance
    "qi_internal":                  "Qi_internal",
    "qi ":                          "Qi_internal",
    "internal quality factor":      "Qi_internal",
    "qtls":                         "Qi_internal",
    "qc":                           "json:Qc_coupling_quality_factor",
    "coupling quality factor":      "json:Qc_coupling_quality_factor",
    "microwave loss":               "Qi_internal",

    # Qubit performance
    "t1 ":                          "T1_us",
    "t1_us":                        "T1_us",
    "relaxation time":              "T1_us",
    "energy relaxation":            "T1_us",
    "spin relaxation time t1":      "T1_us",
    "t2_echo":                      "T2_echo_us",
    "t2e":                          "T2_echo_us",
    "t2 echo":                      "T2_echo_us",
    "t2,cpmg":                      "T2_echo_us",
    "t2,ramsey":                    "json:T2_ramsey_us",
    "t2 ramsey":                    "json:T2_ramsey_us",
    "gate fidelity":                "gate_2q_fidelity_pct",
    "two-qubit gate fidelity":      "gate_2q_fidelity_pct",
    "2q fidelity":                  "gate_2q_fidelity_pct",
    "single-qubit gate fidelity":   "gate_1q_fidelity_pct",
    "readout fidelity":             "json:readout_fidelity_pct",
    "qubit frequency":              "json:qubit_frequency_GHz",
    "anharmonicity":                "json:anharmonicity_MHz",

    # Fabrication parameters
    "film thickness":               "film_thickness_nm",
    "thickness":                    "film_thickness_nm",
    "annealing temperature":        "annealing_temperature_C",
    "anneal temperature":           "annealing_temperature_C",
    "annealing duration":           "annealing_duration_s",
    "deposition temperature":       "deposition_temperature_C",
    "substrate temperature":        "deposition_temperature_C",
    "oxidation time":               "json:oxidation_time_min",
    "au encapsulation thickness":   "film_thickness_nm",
    "encapsulation thickness":      "film_thickness_nm",
    "crystal orientation":          "json:film_crystal_phase",
    "ale surface treatment":        "json:surface_treatment",
    "surface treatment":            "json:surface_treatment",
    "junction deposition vacuum":   "json:junction_vacuum_condition",

    # Derived quantities
    "resistivity":                  "derived_resistivity_uOhm_cm",
    "normal state resistivity":     "derived_resistivity_uOhm_cm",
    "bcs gap":                      "Tc_K",  # deterministic transform of Tc — map directly
    "energy gap":                   "Tc_K",  # deterministic transform of Tc — map directly
    "superconducting gap":          "Tc_K",  # deterministic transform of Tc — map directly

    # Noise
    "flux noise":                   "json:flux_noise_amplitude_uPhi0_per_sqrtHz",
    "charge noise":                 "json:charge_noise_amplitude_e_per_sqrtHz",
    "quasiparticle density":        "json:quasiparticle_density_per_um3",
    "quasiparticle":                "json:quasiparticle_density_per_um3",

    # Transport / condensed matter
    "transport regime":             "json:transport_regime",
    "dirty limit":                  "json:transport_regime",
    "clean limit":                  "json:transport_regime",
    "kerr nonlinearity":            "json:kerr_coefficient",
    "self-kerr":                    "json:kerr_coefficient",
    "kerr coefficient":             "json:kerr_coefficient",
    "critical current":             "json:critical_current_density",
    "modulation depth":             "json:modulation_depth_pct",
    "squid modulation":             "json:modulation_depth_pct",
}

# Terms that are genuinely ambiguous — flag in output
AMBIGUOUS_TERMS = {
    "quality factor":   "Could be Qi or Qc — defaulted to Qi_internal",
    "coherence":        "Could be T1, T2, or coherence_length — check context",
    "loss":             "Could be loss_tangent, Qi, or T1 — check context",
    "annealing":        "Mapped to annealing_temperature_C — duration also possible",
    "thickness":        "Could be film_thickness or oxide_thickness — check context",
}

# Terms that indicate device/circuit physics rather than materials science.
# If 2+ of these appear in a correlation → out of scope.
DEVICE_PHYSICS_TERMS = {
    "dispersive coupling", "dispersive shift", "chi/kappa",
    "logical gate infidelity", "gate infidelity",
    "readout-induced leakage", "readout leakage",
    "bell fidelity", "bell pair fidelity", "fractional bell",
    "parity lifetime", "charge-parity", "pair-breaking transition",
    "burst detection rate", "gap difference delta",
    "jj asymmetry", "josephson junction asymmetry",
    "subharmonic rabi", "rabi rate", "ac-stark shift",
    "drive amplitude", "floquet simulation",
    "iip3", "p1db compression",
    "piezoelectric", "sio2 cladding",
    "siv spin", "magnetic field misalignment",
    "photon number vs", "readout duration",
    "cat size", "fsd active cooling", "kerr-cat",
    "cpmg pi-pulses", "number of cpmg",
}

# Named SQLite columns (for is_in_field_map check)
NAMED_COLUMNS = {
    "Tc_K", "RRR", "sheet_resistance_Ohm_sq",
    "loss_tangent_substrate", "loss_tangent_interface",
    "TLS_density", "Qi_internal", "Qi_single_photon",
    "surface_oxide_nm", "T1_us", "T2_echo_us",
    "gate_1q_fidelity_pct", "gate_2q_fidelity_pct",
    "annealing_temperature_C", "annealing_duration_s",
    "film_thickness_nm", "deposition_temperature_C",
    "normal_state_resistance_Ohm", "room_temperature_resistance_Ohm",
    "derived_resistivity_uOhm_cm", "derived_BCS_gap_meV",
    "derived_coherence_length_nm", "derived_kinetic_inductance_pH_sq",
    "derived_RRR_from_RvT", "derived_sheet_resistance_Ohm_sq",
    "mean_free_path_nm",
    "vortex_activation_temperature_K",
    "kinetic_inductance_sheet_pH_sq",
}


# ── Parser ─────────────────────────────────────────────────────────────────────

def parse_vs_pair(value: str) -> Optional[Tuple[str, str]]:
    """
    Parse "A vs B" from a correlation value string.

    Handles the bug where "vs" appears inside parentheses:
      "Oxidation time (10 vs 30 min) vs TaOx thickness"
      splits as: "Oxidation time (10 vs 30 min)" | "TaOx thickness"

    Strategy: find all " vs " occurrences, skip those inside parentheses,
    use the first one that's outside parentheses.
    """
    if not value:
        return None

    vs_positions = [m.start() for m in re.finditer(r' vs ', value)]
    if not vs_positions:
        return None

    for pos in vs_positions:
        left = value[:pos]
        open_parens = left.count('(') - left.count(')')
        if open_parens == 0:
            term_a = value[:pos].strip()
            term_b = value[pos + 4:].strip()
            if term_a and term_b:
                return term_a, term_b

    return None


def is_device_physics(term_a: str, term_b: str) -> bool:
    """
    Returns True if both terms are device/circuit physics with no
    materials characterization relevance.
    """
    combined = (term_a + " " + term_b).lower()
    matches = sum(1 for t in DEVICE_PHYSICS_TERMS if t in combined)
    return matches >= 2


def is_materials_sample(sample: dict) -> bool:
    """
    Returns True if this sample is a materials characterization record.
    Device-level papers with no materials provenance return False.
    """
    film = sample.get("film_material")
    substrate = sample.get("substrate_material")
    material_class = sample.get("sim_material_class")

    if film and film.lower() not in ("none", "null", "unknown"):
        return True
    if material_class and material_class.lower() not in (
            "none", "null", "unknown", "other"):
        return True
    if substrate and substrate.lower() not in ("none", "null", "unknown"):
        return True
    return False


# ── Field mapping ──────────────────────────────────────────────────────────────

def map_term_to_field(term: str) -> Tuple[Optional[str], str, bool]:
    """
    Map a descriptive term to a canonical field name.

    Returns:
        (field_name, match_type, is_ambiguous)
        field_name:  canonical field name, or None if no match
        match_type:  'exact', 'substring', or 'unmatched'
        is_ambiguous: True if any ambiguous term appears in the input
    """
    if not term:
        return None, 'unmatched', False

    term_lower = term.lower().strip()

    # 1. Exact match
    if term_lower in FIELD_MAP:
        field = FIELD_MAP[term_lower]
        ambiguous = any(a in term_lower for a in AMBIGUOUS_TERMS)
        return field, 'exact', ambiguous

    # 2. Substring: field map key appears in the term
    matches = [
        (key, FIELD_MAP[key])
        for key in FIELD_MAP
        if key in term_lower
    ]
    if matches:
        best_key, best_field = max(matches, key=lambda x: len(x[0]))
        ambiguous = any(a in term_lower for a in AMBIGUOUS_TERMS)
        return best_field, 'substring', ambiguous

    # 3. Reverse substring: term appears in a field map key
    matches2 = [
        (key, FIELD_MAP[key])
        for key in FIELD_MAP
        if term_lower in key
    ]
    if matches2:
        best_key, best_field = max(matches2, key=lambda x: len(x[0]))
        ambiguous = any(a in term_lower for a in AMBIGUOUS_TERMS)
        return best_field, 'substring', ambiguous

    return None, 'unmatched', False


def get_sample_value(sample: dict, field: str) -> Optional[float]:
    """
    Get a numeric field value from a sample record.
    Handles named columns and json:-prefixed sample_json keys.
    """
    if field.startswith("json:"):
        json_key = field[5:]
        raw = (sample.get("sample_json") or {})
        val = raw.get(json_key)
        if val is None:
            return None
        if isinstance(val, dict):
            val = val.get("value")
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    else:
        val = sample.get(field)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None


def _get_confidence(sample: dict, field: str) -> Optional[str]:
    """Extract confidence level for a field if available."""
    conf_map = {
        "Tc_K":        "Tc_confidence",
        "RRR":         "RRR_confidence",
        "Qi_internal": "Qi_confidence",
        "T1_us":       "T1_confidence",
    }
    col = conf_map.get(field)
    if col:
        return sample.get(col)
    if field.startswith("json:"):
        json_key = field[5:]
        raw = (sample.get("sample_json") or {})
        val = raw.get(json_key)
        if isinstance(val, dict):
            return val.get("confidence")
    return None


def build_compact_evidence_record(sample: dict, field_a: str, field_b: str,
                                   val_a: float, val_b: float) -> dict:
    """
    Build a compact evidence record for a sample relevant to a hypothesis.
    Includes structured fields plus catchall items mentioning either field.
    """
    field_a_base = field_a.replace("json:", "").lower()
    field_b_base = field_b.replace("json:", "").lower()

    relevant_catchall = []
    for item in (sample.get("catchall") or []):
        desc = (item.get("description") or "").lower()
        notes = (item.get("notes") or "").lower()
        text = desc + " " + notes
        if field_a_base in text or field_b_base in text:
            relevant_catchall.append({
                "item_type":   item.get("item_type"),
                "description": item.get("description"),
                "notes":       item.get("notes"),
            })

    return {
        "display_name":             sample.get("display_name"),
        "film_material":            sample.get("film_material"),
        "film_crystal_phase":       sample.get("film_crystal_phase"),
        "substrate_material":       sample.get("substrate_material"),
        "deposition_method":        sample.get("deposition_method"),
        "deposition_temperature_C": sample.get("deposition_temperature_C"),
        "annealing_temperature_C":  sample.get("annealing_temperature_C"),
        "authors":                  sample.get("authors"),
        "doi":                      sample.get("doi"),
        "sim_material_class":       sample.get("sim_material_class"),
        "sim_transport_regime":     sample.get("sim_transport_regime"),
        "sim_coherence_tier":       sample.get("sim_coherence_tier"),
        "value_a":                  val_a,
        "value_b":                  val_b,
        "confidence_a":             _get_confidence(sample, field_a),
        "confidence_b":             _get_confidence(sample, field_b),
        "relevant_catchall":        relevant_catchall,
    }


# ── Database loader ────────────────────────────────────────────────────────────

def load_corpus(db_path: Path) -> List[dict]:
    """Load full corpus from SQLite with catchall items merged in."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            s.display_name, s.sample_id, s.filename,
            s.film_material, s.film_crystal_phase,
            s.substrate_material, s.deposition_method,
            s.deposition_temperature_C, s.annealing_temperature_C,
            s.annealing_duration_s, s.film_thickness_nm,
            s.Tc_confidence, s.RRR_confidence,
            s.Qi_confidence, s.T1_confidence,
            s.sample_json,
            s.sim_material_class, s.sim_transport_regime,
            s.sim_coherence_tier, s.sim_device_type,
            s.sim_profile_version,
            s.derived_material,
            s.Tc_K, s.RRR, s.sheet_resistance_Ohm_sq,
            s.loss_tangent_substrate, s.loss_tangent_interface,
            s.TLS_density, s.Qi_internal, s.Qi_single_photon,
            s.surface_oxide_nm, s.T1_us, s.T2_echo_us,
            s.gate_1q_fidelity_pct, s.gate_2q_fidelity_pct,
            s.normal_state_resistance_Ohm,
            s.room_temperature_resistance_Ohm,
            s.derived_resistivity_uOhm_cm, s.derived_BCS_gap_meV,
            s.derived_coherence_length_nm,
            s.derived_kinetic_inductance_pH_sq,
            s.derived_RRR_from_RvT,
            s.derived_sheet_resistance_Ohm_sq,
            s.mean_free_path_nm,
            s.vortex_activation_temperature_K,
            s.kinetic_inductance_sheet_pH_sq,
            p.authors, p.doi, p.title, p.journal
        FROM samples s
        JOIN papers p ON s.paper_id = p.id
        WHERE p.outcome = 'ingested'
        ORDER BY s.film_material, s.display_name
    """)
    rows = cur.fetchall()

    cur.execute("""
        SELECT c.display_name, c.item_type,
               c.description, c.value, c.source, c.notes
        FROM catchall_items c
        JOIN papers p ON c.paper_id = p.id
        WHERE p.outcome = 'ingested'
        ORDER BY c.display_name
    """)
    catchall_rows = cur.fetchall()
    conn.close()

    NUMERIC_FIELDS = [
        "Tc_K", "RRR", "sheet_resistance_Ohm_sq",
        "loss_tangent_substrate", "loss_tangent_interface",
        "TLS_density", "Qi_internal", "Qi_single_photon",
        "surface_oxide_nm", "T1_us", "T2_echo_us",
        "gate_1q_fidelity_pct", "gate_2q_fidelity_pct",
        "annealing_temperature_C", "annealing_duration_s",
        "film_thickness_nm", "deposition_temperature_C",
        "normal_state_resistance_Ohm", "room_temperature_resistance_Ohm",
        "derived_resistivity_uOhm_cm", "derived_BCS_gap_meV",
        "derived_coherence_length_nm", "derived_kinetic_inductance_pH_sq",
        "derived_RRR_from_RvT", "derived_sheet_resistance_Ohm_sq",
    "mean_free_path_nm",
    "vortex_activation_temperature_K",
    "kinetic_inductance_sheet_pH_sq",
    ]

    samples_by_name = {}
    for row in rows:
        d = dict(row)
        for field in NUMERIC_FIELDS:
            val = d.get(field)
            if val is not None:
                try:
                    d[field] = float(val)
                except (TypeError, ValueError):
                    d[field] = None
        raw = d.get("sample_json")
        if raw:
            try:
                d["sample_json"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d["sample_json"] = None
        d["catchall"] = []
        samples_by_name[d["display_name"]] = d

    for crow in catchall_rows:
        c = dict(crow)
        name = c.pop("display_name")
        if name in samples_by_name:
            samples_by_name[name]["catchall"].append(c)

    return list(samples_by_name.values())


# ── Measurement frequency report ───────────────────────────────────────────────

def build_measurement_frequency_report(corpus: List[dict]) -> List[dict]:
    """
    Count how often each term appears in additional_measurement descriptions
    across materials characterization samples only.

    Returns a ranked list — fields the community keeps measuring regardless
    of explicit correlations. Candidates for new hypotheses and schema promotion.
    """
    mat_samples = [s for s in corpus if is_materials_sample(s)]

    term_counter = Counter()
    term_examples = defaultdict(list)

    for sample in mat_samples:
        for item in sample.get("catchall", []):
            if item.get("item_type") != "additional_measurement":
                continue
            desc = (item.get("description") or "").strip()
            if not desc:
                continue

            field, match_type, _ = map_term_to_field(desc)
            term = field if field else desc[:60]
            term_counter[term] += 1
            if len(term_examples[term]) < 3:
                term_examples[term].append({
                    "sample":      sample.get("display_name"),
                    "film":        sample.get("film_material"),
                    "description": desc[:100],
                })

    report = []
    for term, count in term_counter.most_common(40):
        in_schema = term in NAMED_COLUMNS or term.startswith("json:")
        report.append({
            "term":      term,
            "count":     count,
            "in_schema": in_schema,
            "examples":  term_examples[term],
        })

    return report


# ── Phase A ────────────────────────────────────────────────────────────────────

def run_phase_a(db_path: Path, out_path: Path,
                verbose: bool = False) -> dict:
    """
    Phase A: Evidence Extraction.
    Produces four output files:
      mining_evidence.jsonl            — evidence tables for Phase B
      mining_corpus_gaps.jsonl         — stated but unmeasurable
      mining_out_of_scope.jsonl        — device physics / exotic domain
      mining_measurement_frequency.json — community measurement patterns

    Evidence tables are produced at two levels of stratification:
      - "global"            : all materials combined (cross-corpus view)
      - "<material_class>"  : within a single sim_material_class only

    Both levels use the same stated correlations as seeds. The global
    table is the original cross-corpus scan; per-class tables hold
    material identity constant, which is the correct unit for most
    materials-to-device connection hypotheses.

    Phase B consumes all tables regardless of stratification level.
    The `stratification` field in each table distinguishes them.
    Tables with data_sufficient=False (< 3 co-occurring samples) are
    written to the JSONL but skipped by Phase B — they will become
    sufficient as the corpus grows.
    """
    print("=" * 60)
    print("Phase A — Evidence Extraction")
    print("=" * 60)
    print(f"\nLoading corpus from {db_path}...")
    corpus = load_corpus(db_path)
    mat_corpus = [s for s in corpus if is_materials_sample(s)]
    print(f"Loaded {len(corpus)} samples total")
    print(f"  Materials characterization : {len(mat_corpus)}")
    print(f"  Device/circuit (excluded)  : {len(corpus) - len(mat_corpus)}")

    # ── Group mat_corpus by material class for stratified scan ─────────────
    from collections import defaultdict
    mat_corpus_by_class = defaultdict(list)
    for s in mat_corpus:
        cls = (s.get("derived_material") or "unknown").strip().lower()
        if not cls:
            cls = "unknown"
        mat_corpus_by_class[cls].append(s)

    print(f"\nMaterial classes in corpus:")
    for cls, samples in sorted(mat_corpus_by_class.items(),
                                key=lambda x: -len(x[1])):
        print(f"  {cls:<30} : {len(samples)} samples")

    # Collect all correlation items from all samples
    all_correlations = []
    for sample in corpus:
        for item in sample.get("catchall", []):
            if item.get("item_type") == "correlation":
                all_correlations.append({
                    "source_sample":  sample.get("display_name"),
                    "source_film":    sample.get("film_material"),
                    "source_authors": sample.get("authors"),
                    "is_materials":   is_materials_sample(sample),
                    "description":    item.get("description"),
                    "value":          item.get("value"),
                    "notes":          item.get("notes"),
                })
    print(f"\nFound {len(all_correlations)} correlation items total")

    # ── Parse and classify ─────────────────────────────────────────────────
    print("\nParsing and classifying correlations...")
    matched_hypotheses = {}
    corpus_gaps = []
    out_of_scope = []

    for corr in all_correlations:
        value = corr.get("value") or ""

        parsed = parse_vs_pair(value)
        if parsed is None:
            if corr["is_materials"]:
                corpus_gaps.append({
                    **corr,
                    "gap_reason": f"Could not parse 'A vs B' from: '{value}'",
                    "gap_type":   "parse_failure",
                })
            else:
                out_of_scope.append({
                    **corr,
                    "oos_reason": "Non-materials sample, unparseable value",
                })
            continue

        term_a, term_b = parsed

        if is_device_physics(term_a, term_b):
            out_of_scope.append({
                **corr,
                "term_a":     term_a,
                "term_b":     term_b,
                "oos_reason": "Device/circuit physics — not materials-to-device",
            })
            continue

        if not corr["is_materials"]:
            corpus_gaps.append({
                **corr,
                "term_a":    term_a,
                "term_b":    term_b,
                "gap_reason": "Non-materials sample, not clearly device physics — review",
                "gap_type":  "non_materials_sample",
            })
            continue

        field_a, match_type_a, ambig_a = map_term_to_field(term_a)
        field_b, match_type_b, ambig_b = map_term_to_field(term_b)

        if field_a is None and field_b is None:
            corpus_gaps.append({
                **corr,
                "term_a":    term_a,
                "term_b":    term_b,
                "gap_reason": (f"Neither term maps to a known field: "
                               f"'{term_a}' and '{term_b}'"),
                "gap_type":  "unmappable_both",
            })
            continue

        if field_a is None or field_b is None:
            corpus_gaps.append({
                **corr,
                "term_a":       term_a,
                "field_a":      field_a,
                "match_type_a": match_type_a,
                "term_b":       term_b,
                "field_b":      field_b,
                "match_type_b": match_type_b,
                "gap_reason": (
                    f"Partial mapping: "
                    f"'{term_a}' → {field_a or 'UNMATCHED'}, "
                    f"'{term_b}' → {field_b or 'UNMATCHED'}"
                ),
                "gap_type":  "unmappable_one_side",
            })
            continue

        key = tuple(sorted([field_a, field_b]))
        if key not in matched_hypotheses:
            matched_hypotheses[key] = {
                "field_a":             key[0],
                "field_b":             key[1],
                "stated_correlations": [],
                "mapping_notes":       [],
            }
        matched_hypotheses[key]["stated_correlations"].append({
            **corr,
            "term_a":       term_a,
            "field_a":      field_a,
            "match_type_a": match_type_a,
            "ambiguous_a":  ambig_a,
            "term_b":       term_b,
            "field_b":      field_b,
            "match_type_b": match_type_b,
            "ambiguous_b":  ambig_b,
        })
        for ambig, term, field in [
            (ambig_a, term_a, field_a),
            (ambig_b, term_b, field_b),
        ]:
            if ambig:
                note = (f"'{term}' → {field}: "
                        f"{AMBIGUOUS_TERMS.get(term.lower(), 'ambiguous')}")
                if note not in matched_hypotheses[key]["mapping_notes"]:
                    matched_hypotheses[key]["mapping_notes"].append(note)

    print(f"  Matched hypotheses : {len(matched_hypotheses)}")
    print(f"  Corpus gaps        : {len(corpus_gaps)}")
    print(f"  Out of scope       : {len(out_of_scope)}")

    # ── Cross-sample evidence scan — global + per-class ────────────────────
    #
    # For each matched hypothesis we produce:
    #   1. One global evidence table  (stratification="global")
    #   2. One table per material class that has any evidence
    #      (stratification="<material_class>")
    #
    # Stated correlations are the same for all tables of a given hypothesis —
    # they are corpus-wide author claims, not per-class.
    #
    # hypothesis_key format:
    #   global    : "field_a_vs_field_b"
    #   per-class : "field_a_vs_field_b__tantalum"

    print(f"\nScanning corpus for co-occurrence evidence "
          f"(global + {len(mat_corpus_by_class)} material classes)...")

    evidence_tables = []

    def _scan_samples(samples, field_a, field_b):
        """Scan a list of samples for co-occurrence of two fields."""
        records = []
        for sample in samples:
            val_a = get_sample_value(sample, field_a)
            val_b = get_sample_value(sample, field_b)
            if val_a is not None and val_b is not None:
                records.append(
                    build_compact_evidence_record(
                        sample, field_a, field_b, val_a, val_b
                    )
                )
        return records

    def _build_stats(records, field_a, field_b):
        """Build summary stats for an evidence record set."""
        if not records:
            return {}
        vals_a = [r["value_a"] for r in records]
        vals_b = [r["value_b"] for r in records]
        return {
            "n_samples":     len(records),
            "field_a_range": [min(vals_a), max(vals_a)],
            "field_b_range": [min(vals_b), max(vals_b)],
            "materials":     list({r["film_material"]
                                   for r in records
                                   if r["film_material"]}),
        }

    def _make_evidence_table(hyp, field_a, field_b, records,
                              stratification, hypothesis_key):
        """Assemble a complete evidence table record."""
        stats = _build_stats(records, field_a, field_b)
        return {
            "type":                     "evidence_table",
            "hypothesis_key":           hypothesis_key,
            "stratification":           stratification,
            "field_a":                  field_a,
            "field_b":                  field_b,
            "stated_correlation_count": len(hyp["stated_correlations"]),
            "evidence_record_count":    len(records),
            "data_sufficient":          len(records) >= 3,
            "mapping_notes":            hyp["mapping_notes"],
            "stated_correlations":      hyp["stated_correlations"],
            "evidence_records":         records,
            "stats":                    stats,
            "phase_a_generated_at":     datetime.now().isoformat(),
            "corpus_size":              len(corpus),
            "materials_corpus_size":    len(mat_corpus),
        }

    for key, hyp in matched_hypotheses.items():
        field_a = hyp["field_a"]
        field_b = hyp["field_b"]
        base_key = f"{field_a}_vs_{field_b}"

        # ── 1. Global scan (all materials) ─────────────────────────────────
        global_records = _scan_samples(mat_corpus, field_a, field_b)
        global_table = _make_evidence_table(
            hyp, field_a, field_b, global_records,
            stratification="global",
            hypothesis_key=base_key,
        )
        evidence_tables.append(global_table)

        status = (f"{len(global_records)} samples"
                  if global_records else "NO EVIDENCE")
        thin = " ← thin" if 0 < len(global_records) < 3 else ""
        print(f"  [global] {base_key}: "
              f"{len(hyp['stated_correlations'])} stated, {status}{thin}")

        # ── 2. Per-class scan ──────────────────────────────────────────────
        for cls, cls_samples in sorted(mat_corpus_by_class.items()):
            cls_records = _scan_samples(cls_samples, field_a, field_b)

            # Always write the table — data_sufficient=False tables are
            # skipped by Phase B but preserved for corpus growth over time
            cls_key = f"{base_key}__{cls}"
            cls_table = _make_evidence_table(
                hyp, field_a, field_b, cls_records,
                stratification=cls,
                hypothesis_key=cls_key,
            )
            

            if cls != "other":
                evidence_tables.append(cls_table)
            if cls_records:
                thin_cls = " ← thin" if len(cls_records) < 3 else ""
                excluded = " — EXCLUDED from Phase B" if cls == "other" else ""
                print(f"  [{cls}] {base_key}: "
                      f"{len(cls_records)} samples{thin_cls}{excluded}")

    # Sort: sufficient first, then by stated correlation count descending
    evidence_tables.sort(
        key=lambda t: (
            not t["data_sufficient"],           # sufficient tables first
            t["stratification"] != "global",    # global before per-class
            -t["stated_correlation_count"],
            -t["evidence_record_count"],
        )
    )

    # ── Measurement frequency report ───────────────────────────────────────
    print(f"\nBuilding measurement frequency report...")
    freq_report = build_measurement_frequency_report(corpus)
    print(f"  Top measurement terms: {len(freq_report)}")

    # ── Write output files ─────────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        for table in evidence_tables:
            f.write(json.dumps(table, ensure_ascii=False, default=str) + "\n")

    gaps_path = out_path.parent / "mining_corpus_gaps.jsonl"
    oos_path  = out_path.parent / "mining_out_of_scope.jsonl"
    freq_path = out_path.parent / "mining_measurement_frequency.json"

    with open(gaps_path, "w", encoding="utf-8") as f:
        for item in corpus_gaps:
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    with open(oos_path, "w", encoding="utf-8") as f:
        for item in out_of_scope:
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    with open(freq_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at":              datetime.now().isoformat(),
            "materials_samples_scanned": len(mat_corpus),
            "top_measurements":          freq_report,
        }, f, indent=2, ensure_ascii=False)

    # ── Summary counts ─────────────────────────────────────────────────────
    global_tables  = [t for t in evidence_tables
                      if t["stratification"] == "global"]
    class_tables   = [t for t in evidence_tables
                      if t["stratification"] != "global"]
    sufficient_all = [t for t in evidence_tables if t["data_sufficient"]]
    no_evidence    = [t for t in evidence_tables
                      if t["evidence_record_count"] == 0]
    insufficient   = [t for t in evidence_tables
                      if 0 < t["evidence_record_count"] < 3]

    # ── Print corpus gaps ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"CORPUS GAPS ({len(corpus_gaps)}) — stated but not yet measurable")
    print(f"{'='*60}")
    gap_types = Counter(g.get("gap_type", "unknown") for g in corpus_gaps)
    for gtype, count in gap_types.most_common():
        print(f"  {gtype}: {count}")
    print()
    for i, gap in enumerate(corpus_gaps, 1):
        print(f"  [{i}] {gap.get('source_sample', '?')}")
        print(f"       Value  : {(gap.get('value') or '')[:80]}")
        print(f"       Reason : {gap.get('gap_reason', '')}")
        if gap.get("gap_type") == "unmappable_one_side":
            print(f"       Mapped : '{gap.get('term_a')}'"
                  f" → {gap.get('field_a') or 'UNMATCHED'}")
            print(f"              : '{gap.get('term_b')}'"
                  f" → {gap.get('field_b') or 'UNMATCHED'}")

    # ── Print out of scope ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"OUT OF SCOPE ({len(out_of_scope)}) — device/circuit physics")
    print(f"{'='*60}")
    for i, oos in enumerate(out_of_scope, 1):
        print(f"  [{i}] {oos.get('source_sample', '?')}")
        print(f"       Value  : {(oos.get('value') or '')[:80]}")
        print(f"       Reason : {oos.get('oos_reason', '')}")

    # ── Print measurement frequency highlights ─────────────────────────────
    print(f"\n{'='*60}")
    print(f"TOP MEASUREMENT TERMS (additional_measurements, materials only)")
    print(f"{'='*60}")
    for item in freq_report[:20]:
        schema = "in schema" if item["in_schema"] else "NOT in schema"
        print(f"  {item['count']:>3}×  {item['term'][:55]:<55} [{schema}]")

    # ── Hypotheses with no/thin evidence ──────────────────────────────────
    if no_evidence:
        print(f"\n{'='*60}")
        print(f"NO EVIDENCE ({len(no_evidence)} tables)")
        print(f"  Both fields mapped, but no samples have both measured.")
        print(f"{'='*60}")
        for t in no_evidence:
            print(f"  [{t['stratification']}] {t['field_a']} × {t['field_b']}: "
                  f"{t['stated_correlation_count']} stated")

    if insufficient:
        print(f"\n{'='*60}")
        print(f"THIN EVIDENCE — <3 samples ({len(insufficient)} tables)")
        print(f"  Phase B will skip these. Will become sufficient as corpus grows.")
        print(f"{'='*60}")
        for t in insufficient:
            print(f"  [{t['stratification']}] {t['field_a']} × {t['field_b']}: "
                  f"{t['evidence_record_count']} sample(s)")

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Phase A Summary")
    print(f"{'='*60}")
    print(f"  Corpus (total)                 : {len(corpus)}")
    print(f"  Materials characterization     : {len(mat_corpus)}")
    print(f"  Material classes               : {len(mat_corpus_by_class)}")
    print(f"  Correlations found             : {len(all_correlations)}")
    print(f"  Out of scope                   : {len(out_of_scope)}")
    print(f"  Corpus gaps                    : {len(corpus_gaps)}")
    print(f"  Hypotheses matched             : {len(matched_hypotheses)}")
    print(f"")
    print(f"  Evidence tables written        : {len(evidence_tables)}")
    print(f"    Global (cross-corpus)        : {len(global_tables)}")
    print(f"    Per-material-class           : {len(class_tables)}")
    print(f"    Sufficient for Phase B (>=3) : {len(sufficient_all)}")
    print(f"    Thin (<3, preserved)         : {len(insufficient)}")
    print(f"    No evidence (preserved)      : {len(no_evidence)}")
    print(f"")
    print(f"  Output files:")
    print(f"    {out_path}")
    print(f"    {gaps_path}")
    print(f"    {oos_path}")
    print(f"    {freq_path}")

    if verbose:
        print(f"\n{'='*60}")
        print("FULL EVIDENCE TABLES (verbose)")
        print(f"{'='*60}")
        for t in evidence_tables:
            print(f"\n── {t['hypothesis_key']} ──")
            print(json.dumps(t, indent=2, ensure_ascii=False, default=str))

    return {
        "corpus_size":           len(corpus),
        "materials_corpus":      len(mat_corpus),
        "material_classes":      len(mat_corpus_by_class),
        "correlations_found":    len(all_correlations),
        "out_of_scope_count":    len(out_of_scope),
        "corpus_gap_count":      len(corpus_gaps),
        "hypotheses_matched":    len(matched_hypotheses),
        "evidence_tables_total": len(evidence_tables),
        "global_tables":         len(global_tables),
        "class_tables":          len(class_tables),
        "sufficient_count":      len(sufficient_all),
        "insufficient_count":    len(insufficient),
        "no_evidence_count":     len(no_evidence),
        "evidence_tables":       evidence_tables,
        "corpus_gaps":           corpus_gaps,
        "out_of_scope":          out_of_scope,
        "measurement_frequency": freq_report,
    }


# ── Phase B: AI Reasoning ──────────────────────────────────────────────────────

# Maximum evidence records per API call.
# Large hypotheses are chunked to avoid context window issues.
# Results are merged conservatively (lowest confidence wins).
_PHASE_B_CHUNK_SIZE = 30

# Fields that are derived from other fields — Claude should know this
# so it doesn't overclaim independence between correlated quantities.
DERIVED_FIELD_NOTES = {
    "derived_BCS_gap_meV": (
        "NOTE: derived_BCS_gap_meV is computed deterministically from Tc_K "
        "via the BCS formula (Delta = 1.764 * kB * Tc). It is NOT an independent "
        "measurement. Any hypothesis involving derived_BCS_gap_meV is therefore "
        "essentially the same hypothesis as one involving Tc_K directly. "
        "Please reason about this carefully and note the dependency explicitly."
    ),
    "derived_coherence_length_nm": (
        "NOTE: derived_coherence_length_nm is computed from upper_critical_field_T "
        "via the GL formula. It is a derived quantity, not a direct measurement."
    ),
    "derived_resistivity_uOhm_cm": (
        "NOTE: derived_resistivity_uOhm_cm is computed from sheet_resistance and "
        "film_thickness. It is a derived quantity, not a direct measurement."
    ),
    "derived_RRR_from_RvT": (
        "NOTE: derived_RRR_from_RvT is computed from R(300K)/R(Tc+) geometry "
        "measurements. It is a derived quantity approximating the true RRR."
    ),
    "derived_sheet_resistance_Ohm_sq": (
        "NOTE: derived_sheet_resistance_Ohm_sq is computed from resistance "
        "measurements and device geometry. It is a derived quantity."
    ),
}

_PHASE_B_SYSTEM_PROMPT = """You are an expert scientific research assistant 
specializing in superconducting materials for quantum computing. You reason 
carefully over experimental evidence, cite specific samples by name, and are 
honest about uncertainty and limitations. You never overclaim from sparse data."""


def _build_phase_b_prompt(evidence_table: dict,
                           prior_findings: List[dict]) -> str:
    """
    Build the Phase B reasoning prompt for a single hypothesis.

    Sends Claude:
    - The hypothesis (field pair)
    - Author-stated correlations that seeded it
    - Cross-sample evidence records
    - Prior approved findings as context
    - Any relevant derived-field warnings
    """
    field_a     = evidence_table["field_a"]
    field_b     = evidence_table["field_b"]
    hyp_key     = evidence_table["hypothesis_key"]
    stated      = evidence_table.get("stated_correlations", [])
    records     = evidence_table.get("evidence_records", [])
    stats       = evidence_table.get("stats", {})
    corpus_size = evidence_table.get("materials_corpus_size", "unknown")

    # ── Derived field warnings ─────────────────────────────────────────────
    derived_warnings = []
    for field in [field_a, field_b]:
        if field in DERIVED_FIELD_NOTES:
            derived_warnings.append(DERIVED_FIELD_NOTES[field])

    # ── Prior findings context ─────────────────────────────────────────────
    prior_context = ""
    if prior_findings:
        prior_lines = []
        for pf in prior_findings:
            writeup = pf.get("writeup") or {}
            prior_lines.append(
                f"- [{pf.get('hypothesis_key')}] "
                f"{writeup.get('hypothesis', 'no hypothesis stated')} "
                f"(confidence: {writeup.get('confidence', '?')}, "
                f"type: {writeup.get('finding_type', '?')})"
            )
        prior_context = (
            "\n\nPRIOR APPROVED FINDINGS FROM PREVIOUS MINING RUNS:\n"
            "These have already been established. Factor them in but focus "
            "on what is new or complementary:\n"
            + "\n".join(prior_lines)
        )

    # ── Author-stated correlations ─────────────────────────────────────────
    stated_lines = []
    for i, s in enumerate(stated, 1):
        direction = (s.get("notes") or "direction not specified")[:120]
        stated_lines.append(
            f"  [{i}] {s.get('source_sample', '?')} "
            f"({s.get('source_film', '?')})\n"
            f"      Claim: {(s.get('description') or '')[:120]}\n"
            f"      Direction/nature: {direction}"
        )
    stated_text = "\n".join(stated_lines) if stated_lines else "  None"

    # ── Evidence records ───────────────────────────────────────────────────
    record_lines = []
    for i, r in enumerate(records, 1):
        conf_a = f" [{r.get('confidence_a')}]" if r.get('confidence_a') else ""
        conf_b = f" [{r.get('confidence_b')}]" if r.get('confidence_b') else ""

        catchall_notes = ""
        if r.get("relevant_catchall"):
            catchall_items = r["relevant_catchall"][:2]
            catchall_notes = " | Catchall: " + "; ".join(
                f"{c.get('item_type')}: {(c.get('description') or '')[:60]}"
                for c in catchall_items
            )

        record_lines.append(
            f"  [{i}] {r.get('display_name', '?')}\n"
            f"      Film: {r.get('film_material', '?')} | "
            f"Substrate: {r.get('substrate_material', '?')} | "
            f"Deposition: {r.get('deposition_method', '?')}\n"
            f"      {field_a}: {r.get('value_a')}{conf_a} | "
            f"{field_b}: {r.get('value_b')}{conf_b}\n"
            f"      Anneal: {r.get('annealing_temperature_C', '?')}°C | "
            f"Transport regime: {r.get('sim_transport_regime', '?')} | "
            f"Coherence tier: {r.get('sim_coherence_tier', '?')}"
            + (f"\n      {catchall_notes}" if catchall_notes else "")
        )
    records_text = "\n".join(record_lines) if record_lines else "  None"

    # ── Stats summary ──────────────────────────────────────────────────────
    stats_text = ""
    if stats:
        stats_text = (
            f"\nEvidence statistics:\n"
            f"  Samples with both fields: {stats.get('n_samples', 0)} "
            f"of {corpus_size} materials samples\n"
            f"  {field_a} range: {stats.get('field_a_range', '?')}\n"
            f"  {field_b} range: {stats.get('field_b_range', '?')}\n"
            f"  Materials represented: {', '.join(stats.get('materials', []))}"
        )

    # ── Response schema ────────────────────────────────────────────────────
    schema = json.dumps({
        "hypothesis_key":        hyp_key,
        "hypothesis":            "one sentence statement of the proposed connection",
        "pattern_observed":      "what pattern if any do you see in the data",
        "supporting_records":    [{"display_name": "...", "reason": "..."}],
        "complicating_records":  [{"display_name": "...", "reason": "..."}],
        "alternative_explanations": ["..."],
        "missing_evidence":      ["what additional data would help"],
        "confidence":            0.0,
        "confidence_rationale":  "explicit reasoning about confidence level",
        "assessment_conclusion": "supported | partially_supported | unsupported | inconclusive",
        "derived_field_concern": "if applicable, note any derived field dependency issues",
        "negative_result":       False,
        "negative_result_note":  "if negative, what does absence of pattern tell us",
    }, indent=2)

    # ── Assemble prompt ────────────────────────────────────────────────────
    derived_text = ("\n\n⚠ IMPORTANT WARNINGS ABOUT DERIVED FIELDS:\n" +
                    "\n".join(derived_warnings)) if derived_warnings else ""

    return f"""I have a set of superconducting materials characterization records and a 
hypothesis about a connection between two measured properties. Please reason carefully 
over the evidence and produce a structured assessment.

HYPOTHESIS: Is there a meaningful connection between {field_a} and {field_b}?

This hypothesis was seeded by {len(stated)} author-stated correlation(s) in the literature:
{stated_text}
{stats_text}{derived_text}{prior_context}

Here are all {len(records)} corpus samples that have both fields measured:
{records_text}

Please reason over this evidence carefully. Cite specific sample names when making 
claims. Consider:
- Is there a visible pattern? What direction and strength?
- Which samples support the hypothesis most strongly?
- Which samples complicate or contradict it?
- Are there confounding variables (different materials, deposition methods)?
- What alternative explanations exist for any pattern?
- How confident are you given the sample count and data quality?
- If no clear pattern exists, is that itself informative?

Confidence guidance:
  0.7-0.75: clear pattern with specific citations, supporting AND complicating cases identified
  0.5-0.6:  visible pattern but incomplete or thin evidence
  0.3-0.4:  suggestive but weak — few samples or mixed signals
  0.1-0.2:  no pattern or contradictory evidence

Respond with a JSON object matching this structure exactly:
{schema}

Respond with JSON only. No preamble or explanation outside the JSON."""


def _parse_json_response(raw: str, label: str) -> dict:
    """Parse JSON from Claude response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        text = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [WARN] Could not parse JSON for {label}: {e}")
        print(f"  [WARN] Raw response (first 200 chars): {raw[:200]}")
        return {}


def _merge_chunk_reasonings(hyp_key: str, chunks: List[dict]) -> dict:
    """
    Merge reasoning outputs from multiple chunks of the same hypothesis.
    Conservative strategy: lowest confidence wins, all records combined.
    """
    all_supporting   = []
    all_complicating = []
    all_missing      = []
    all_alternatives = []
    confidences      = []
    negatives        = []
    assessments      = []

    for r in chunks:
        all_supporting.extend(r.get("supporting_records") or [])
        all_complicating.extend(r.get("complicating_records") or [])
        all_missing.extend(r.get("missing_evidence") or [])
        all_alternatives.extend(r.get("alternative_explanations") or [])
        if r.get("confidence") is not None:
            confidences.append(float(r["confidence"]))
        negatives.append(r.get("negative_result", False))
        if r.get("assessment_conclusion"):
            assessments.append(r["assessment_conclusion"])

    # Pick best chunk (most supporting records) for hypothesis statement
    best = max(chunks, key=lambda r: len(r.get("supporting_records") or []))

    # Deduplicate missing evidence
    seen = set()
    deduped_missing = []
    for m in all_missing:
        if m not in seen:
            seen.add(m)
            deduped_missing.append(m)

    return {
        "hypothesis_key":        hyp_key,
        "hypothesis":            best.get("hypothesis", ""),
        "pattern_observed":      best.get("pattern_observed", ""),
        "supporting_records":    all_supporting,
        "complicating_records":  all_complicating,
        "alternative_explanations": list(set(all_alternatives)),
        "missing_evidence":      deduped_missing,
        "confidence":            min(confidences) if confidences else 0.2,
        "confidence_rationale":  (
            f"Conservative merge of {len(chunks)} chunks — "
            f"minimum confidence used. Individual confidences: {confidences}"
        ),
        "assessment_conclusion": assessments[0] if assessments else "inconclusive",
        "derived_field_concern": best.get("derived_field_concern", ""),
        "negative_result":       all(negatives) if negatives else False,
        "negative_result_note":  best.get("negative_result_note", ""),
        "chunked":               True,
        "chunk_count":           len(chunks),
    }


def _import_ai_client():
    """Import the AI client using the same pattern as the ingester."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from openai_client import make_client
        from config import get_deployment_name
        client     = make_client(timeout=180.0)
        deployment = get_deployment_name()
        return client, deployment
    except ImportError as e:
        print(f"[ERROR] Could not import AI client: {e}")
        print("Make sure openai_client.py and config.py are in the ingester directory.")
        raise


def run_phase_b(evidence_path: Path,
                out_path: Path,
                prior_findings_path: Optional[Path] = None) -> List[dict]:
    """
    Phase B: AI Reasoning over evidence tables.

    For each evidence table from Phase A:
    - Sends Claude the hypothesis, stated correlations, and cross-sample evidence
    - Claude identifies patterns, supporting/complicating records, confidence
    - Large evidence sets are chunked at _PHASE_B_CHUNK_SIZE records per call
    - Chunks are merged conservatively (lowest confidence wins)
    - Prior approved findings are passed as context if available

    Only processes hypotheses with data_sufficient=True (>=3 evidence records).
    Hypotheses with no evidence are logged and skipped.

    Input:  mining_evidence.jsonl  (from Phase A)
    Output: mining_reasoned.jsonl
    """
    import time

    print("=" * 60)
    print("Phase B — AI Reasoning")
    print("=" * 60)

    # Load evidence tables
    evidence_tables = []
    with open(evidence_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evidence_tables.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] Skipping malformed line: {e}")

    print(f"\nLoaded {len(evidence_tables)} evidence tables from Phase A")

    # Separate sufficient from insufficient
    sufficient   = [t for t in evidence_tables if t.get("data_sufficient")]
    insufficient = [t for t in evidence_tables if not t.get("data_sufficient")]

    print(f"  Sufficient for Phase B (>=3 samples) : {len(sufficient)}")
    print(f"  Skipped (insufficient evidence)       : {len(insufficient)}")

    if insufficient:
        print(f"\n  Skipped hypotheses:")
        for t in insufficient:
            print(f"    {t['hypothesis_key']} "
                  f"({t['evidence_record_count']} samples)")

    if not sufficient:
        print("\n[ERROR] No hypotheses have sufficient evidence for Phase B.")
        print("Run schema promotion to add more fields, then re-run Phase A.")
        return []

    # Load prior findings if available
    prior_findings = []
    if prior_findings_path and prior_findings_path.exists():
        with open(prior_findings_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("review_status") == "approved":
                        prior_findings.append(rec)
                except json.JSONDecodeError:
                    pass
        print(f"\nLoaded {len(prior_findings)} prior approved findings as context")
    else:
        print("\nNo prior findings — running fresh")

    # Import AI client
    print("\nInitialising AI client...")
    try:
        client, deployment = _import_ai_client()
    except Exception as e:
        print(f"[ERROR] Could not initialise AI client: {e}")
        raise

    print(f"Chunk size: {_PHASE_B_CHUNK_SIZE} records per API call")

    # ── Process each hypothesis ────────────────────────────────────────────
    reasoned = []

    for i, table in enumerate(sufficient, 1):
        hyp_key  = table["hypothesis_key"]
        field_a  = table["field_a"]
        field_b  = table["field_b"]
        records  = table.get("evidence_records", [])
        n        = len(records)

        print(f"\n[{i}/{len(sufficient)}] {hyp_key} ({n} evidence records)")
        print(f"  Fields: {field_a} × {field_b}")
        print(f"  Stated correlations: {table.get('stated_correlation_count', 0)}")

        # Warn about mapping notes / ambiguities
        for note in (table.get("mapping_notes") or []):
            print(f"  ⚠ {note}")

        # Split into chunks if needed
        chunks_data = [
            records[j:j + _PHASE_B_CHUNK_SIZE]
            for j in range(0, max(n, 1), _PHASE_B_CHUNK_SIZE)
        ]
        n_chunks = len(chunks_data)
        if n_chunks > 1:
            print(f"  Splitting into {n_chunks} chunks of "
                  f"~{_PHASE_B_CHUNK_SIZE} records each")

        chunk_reasonings = []

        for chunk_idx, chunk_records in enumerate(chunks_data, 1):
            if n_chunks > 1:
                print(f"  Chunk {chunk_idx}/{n_chunks} "
                      f"({len(chunk_records)} records)...",
                      end=" ", flush=True)
            else:
                print(f"  Calling Claude...", end=" ", flush=True)

            # Build a table view for just this chunk
            chunk_table = {**table, "evidence_records": chunk_records}
            prompt = _build_phase_b_prompt(chunk_table, prior_findings)

            try:
                response = client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": "system", "content": _PHASE_B_SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    max_completion_tokens=4000,
                )
                raw      = response.choices[0].message.content or ""
                finish   = response.choices[0].finish_reason
                print(f"{len(raw)} chars, finish={finish}")

                reasoning = _parse_json_response(
                    raw, f"{hyp_key}-chunk{chunk_idx}"
                )
                if reasoning:
                    chunk_reasonings.append(reasoning)
                else:
                    print(f"  [WARN] Empty reasoning for chunk {chunk_idx}")

            except Exception as e:
                print(f"\n  [ERROR] API call failed on chunk {chunk_idx}: {e}")

            # Small delay between calls
            time.sleep(1.0)

        # ── Merge chunks ───────────────────────────────────────────────────
        if not chunk_reasonings:
            reasoning = {"api_error": "All chunks failed"}
        elif len(chunk_reasonings) == 1:
            reasoning = chunk_reasonings[0]
        else:
            print(f"  Merging {len(chunk_reasonings)} chunk results...")
            reasoning = _merge_chunk_reasonings(hyp_key, chunk_reasonings)

        # ── Print summary ──────────────────────────────────────────────────
        if reasoning and not reasoning.get("api_error"):
            conf     = reasoning.get("confidence", "?")
            assess   = reasoning.get("assessment_conclusion", "?")
            n_sup    = len(reasoning.get("supporting_records") or [])
            n_comp   = len(reasoning.get("complicating_records") or [])
            neg      = reasoning.get("negative_result", False)
            derived  = reasoning.get("derived_field_concern", "")
            print(f"  Confidence: {conf} | Assessment: {assess} | "
                  f"Supporting: {n_sup} | Complicating: {n_comp}"
                  + (" | NEGATIVE RESULT" if neg else "")
                  + (f"\n  ⚠ Derived field: {derived[:80]}" if derived else ""))

        # ── Build reasoned record ──────────────────────────────────────────
        reasoned_record = {
            **table,
            "type":                 "reasoned_table",
            "reasoning":            reasoning,
            "phase_b_generated_at": datetime.now().isoformat(),
        }
        reasoned.append(reasoned_record)

    # ── Write output ───────────────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in reasoned:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    # ── Summary ────────────────────────────────────────────────────────────
    errors = sum(1 for r in reasoned
                 if (r.get("reasoning") or {}).get("api_error"))
    success = len(reasoned) - errors

    print(f"\n{'='*60}")
    print(f"Phase B Summary")
    print(f"{'='*60}")
    print(f"  Hypotheses processed : {len(sufficient)}")
    print(f"  Successful           : {success}")
    print(f"  Errors               : {errors}")
    print(f"  Output               : {out_path}")
    print(f"\nNext step: python3 pipeline_mining.py phase-c "
          f"--reasoned {out_path}")

    return reasoned


# ── Phase C: Write-up ──────────────────────────────────────────────────────────

_PHASE_C_SYSTEM_PROMPT = """You are an expert scientific research assistant 
specializing in superconducting materials for quantum computing. You write clear, 
honest, scientifically rigorous finding summaries for expert human review. You 
never overclaim, always acknowledge uncertainty, and write negative results with 
the same care as positive ones."""


def _build_phase_c_prompt(reasoned_table: dict) -> str:
    """
    Build the Phase C write-up prompt.
    Sends Claude the Phase B reasoning output and asks for a structured
    human-readable finding.
    """
    reasoning  = reasoned_table.get("reasoning") or {}
    field_a    = reasoned_table["field_a"]
    field_b    = reasoned_table["field_b"]
    hyp_key    = reasoned_table["hypothesis_key"]
    stats      = reasoned_table.get("stats") or {}
    n_samples  = stats.get("n_samples", 0)
    n_stated   = reasoned_table.get("stated_correlation_count", 0)
    materials  = stats.get("materials", [])

    reasoning_json = json.dumps(reasoning, indent=2, default=str)

    schema = json.dumps({
        "hypothesis_key":   hyp_key,
        "finding_type":     "positive | negative | inconclusive | derived_field_artifact",
        "title":            "Short descriptive title for this finding (1 sentence)",
        "hypothesis":       "The proposed connection, stated clearly",
        "summary":          "2-3 sentence plain-language summary of what was found",
        "evidence_summary": {
            "n_samples":          n_samples,
            "n_stated_by_authors": n_stated,
            "materials_covered":  materials,
            "key_supporting":     "1-2 sentence description of strongest supporting evidence",
            "key_complicating":   "1-2 sentence description of strongest complicating evidence",
            "missing_evidence":   "Most important missing data that would resolve uncertainty",
        },
        "finding_detail":   "3-5 sentences of detailed scientific reasoning, citing specific samples",
        "alternative_explanations": "1-2 sentence summary of the most plausible alternative",
        "confidence":       0.0,
        "confidence_rationale": "Why this confidence level — be explicit about sample count and data quality",
        "qrem_implications": "What does this finding mean for the QREM materials-to-device mapping layer? Be specific about whether a mapping function is supported, and what form it might take.",
        "per_material_recommendation": "Should this hypothesis be re-run per material class? Which materials have enough samples?",
        "questions_for_reviewer": [
            "Specific question where domain expert judgment is needed",
            "Another specific question",
        ],
        "suggested_followup": "Most valuable next experiment or analysis to resolve this finding",
        "review_status":    "pending",
        "review_notes":     None,
        "revision_history": [],
    }, indent=2)

    return f"""I have completed a Phase B reasoning assessment for a superconducting 
materials hypothesis. Please write this up as a clear, human-reviewable scientific 
finding for expert review.

HYPOTHESIS: Connection between {field_a} and {field_b}
CORPUS: {n_samples} samples with both fields measured, across materials: {', '.join(materials) if materials else 'various'}
AUTHOR-STATED CORRELATIONS SEEDING THIS: {n_stated}

Here is the detailed Phase B reasoning assessment:
{reasoning_json}

Please write a clear scientific finding summary. Requirements:
- Be honest about limitations — sparse data, confounds, derived fields
- Negative results are valuable findings — write them carefully, not dismissively  
- The QREM implications field is critical — always address whether a mapping 
  function is supported and what form it might take, even if the answer is 
  "not yet supportable"
- The per_material_recommendation field should say specifically which materials 
  have enough samples to warrant a focused re-analysis
- Questions for reviewer should be specific and actionable, not generic
- finding_type "derived_field_artifact" should be used when the hypothesis 
  is confounded by a derived field dependency (e.g. BCS gap derived from Tc)

Respond with a JSON object matching this structure exactly:
{schema}

Respond with JSON only. No preamble or explanation outside the JSON."""


def run_phase_c(reasoned_path: Path,
                out_path: Path,
                report_path: Optional[Path] = None) -> List[dict]:
    """
    Phase C: Write-up.

    Takes Phase B reasoned tables and produces structured, human-reviewable
    finding cards. Each finding includes:
    - Plain-language summary
    - Evidence summary with key supporting/complicating samples
    - QREM mapping layer implications
    - Per-material-class re-analysis recommendation
    - Questions for expert reviewer
    - Suggested follow-up

    Skips tables with Phase B errors.

    Input:  mining_reasoned.jsonl  (from Phase B)
    Output: mining_findings.jsonl  + optional markdown report
    """
    import time

    print("=" * 60)
    print("Phase C — Write-up")
    print("=" * 60)

    # Load reasoned tables
    reasoned_tables = []
    with open(reasoned_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                reasoned_tables.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] Skipping malformed line: {e}")

    print(f"\nLoaded {len(reasoned_tables)} reasoned tables from Phase B")

    # Import AI client
    print("Initialising AI client...")
    try:
        client, deployment = _import_ai_client()
    except Exception as e:
        print(f"[ERROR] Could not initialise AI client: {e}")
        raise

    findings = []

    for i, table in enumerate(reasoned_tables, 1):
        hyp_key  = table.get("hypothesis_key", "unknown")
        field_a  = table.get("field_a", "?")
        field_b  = table.get("field_b", "?")
        reasoning = table.get("reasoning") or {}

        print(f"\n[{i}/{len(reasoned_tables)}] {hyp_key}")

        # Skip Phase B errors
        if reasoning.get("api_error") or reasoning.get("parse_error"):
            print(f"  SKIPPED — Phase B error: "
                  f"{reasoning.get('api_error') or reasoning.get('parse_error')}")
            continue

        prompt = _build_phase_c_prompt(table)

        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": _PHASE_C_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_completion_tokens=4000,
                temperature=0.3,
            )
            raw    = response.choices[0].message.content or ""
            finish = response.choices[0].finish_reason
            print(f"  Response: {len(raw)} chars, finish={finish}")

            writeup = _parse_json_response(raw, hyp_key)
            if not writeup:
                print(f"  [WARN] Could not parse write-up")
                writeup = {"parse_error": True, "raw": raw[:500]}

        except Exception as e:
            print(f"  [ERROR] API call failed: {e}")
            writeup = {"api_error": str(e)}

        # Print summary
        if writeup and not writeup.get("parse_error") and not writeup.get("api_error"):
            ftype   = writeup.get("finding_type", "?")
            conf    = writeup.get("confidence", "?")
            title   = writeup.get("title", "")
            qrem    = (writeup.get("qrem_implications") or "")[:100]
            print(f"  Type: {ftype} | Confidence: {conf}")
            print(f"  Title: {title}")
            print(f"  QREM: {qrem}...")

        # Build finding record
        finding = {
            "type":             "mining_finding",
            "hypothesis_key":   hyp_key,
            "field_a":          field_a,
            "field_b":          field_b,
            "run_id":           datetime.now().strftime("%Y%m%d"),
            # Key Phase B fields for reference
            "evidence_record_count":    table.get("evidence_record_count", 0),
            "stated_correlation_count": table.get("stated_correlation_count", 0),
            "phase_b_confidence":       reasoning.get("confidence"),
            "phase_b_assessment":       reasoning.get("assessment_conclusion"),
            "phase_b_negative":         reasoning.get("negative_result", False),
            "supporting_records":       reasoning.get("supporting_records") or [],
            "complicating_records":     reasoning.get("complicating_records") or [],
            # Phase C write-up
            "writeup":                  writeup,
            # Human review fields
            "review_status":            "pending",
            "review_notes":             None,
            "reviewer":                 None,
            "reviewed_at":              None,
            "revision_history":         [],
            "send_back_requested":      False,
            "send_back_notes":          None,
            # Provenance
            "phase_c_generated_at":     datetime.now().isoformat(),
        }

        findings.append(finding)
        time.sleep(1.0)

    # ── Write findings JSONL ───────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for finding in findings:
            f.write(json.dumps(finding, ensure_ascii=False, default=str) + "\n")

    print(f"\nFindings written to {out_path}")

    # ── Write markdown report ──────────────────────────────────────────────
    if report_path is None:
        report_path = out_path.parent / "mining_findings_report.md"

    _write_findings_report(findings, report_path)

    # ── Summary ────────────────────────────────────────────────────────────
    pos  = sum(1 for f in findings
               if (f.get("writeup") or {}).get("finding_type") == "positive")
    neg  = sum(1 for f in findings
               if (f.get("writeup") or {}).get("finding_type") == "negative")
    inc  = sum(1 for f in findings
               if (f.get("writeup") or {}).get("finding_type") == "inconclusive")
    art  = sum(1 for f in findings
               if (f.get("writeup") or {}).get("finding_type") == "derived_field_artifact")
    err  = sum(1 for f in findings
               if (f.get("writeup") or {}).get("parse_error")
               or (f.get("writeup") or {}).get("api_error"))

    print(f"\n{'='*60}")
    print(f"Phase C Summary")
    print(f"{'='*60}")
    print(f"  Findings written     : {len(findings)}")
    print(f"    Positive           : {pos}")
    print(f"    Negative           : {neg}")
    print(f"    Inconclusive       : {inc}")
    print(f"    Derived artifact   : {art}")
    print(f"    Errors             : {err}")
    print(f"  Output JSONL         : {out_path}")
    print(f"  Markdown report      : {report_path}")
    print(f"\nNext step: review findings in the Mining UI (Stage 4)")
    print(f"  Approve findings → written to findings.jsonl → git push → Explorer")

    return findings


def _write_findings_report(findings: List[dict], report_path: Path):
    """Write a human-readable markdown report of all findings."""
    report_path.parent.mkdir(parents=True, exist_ok=True)

    type_icon = {
        "positive":              "✓",
        "negative":              "✗",
        "inconclusive":          "~",
        "derived_field_artifact": "⚠",
    }

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Corpus Mining Findings Report\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write(f"Total findings: {len(findings)}\n\n")
        f.write("---\n\n")

        for finding in findings:
            writeup  = finding.get("writeup") or {}
            hyp_key  = finding.get("hypothesis_key", "?")
            ftype    = writeup.get("finding_type", "unknown")
            conf     = writeup.get("confidence", "?")
            title    = writeup.get("title", hyp_key)
            icon     = type_icon.get(ftype, "?")

            f.write(f"## {icon} {title}\n")
            f.write(f"**Hypothesis key:** `{hyp_key}`  \n")
            f.write(f"**Finding type:** {ftype} | "
                    f"**Confidence:** {conf} | "
                    f"**Phase B assessment:** "
                    f"{finding.get('phase_b_assessment', '?')}\n\n")

            summary = writeup.get("summary")
            if summary:
                f.write(f"{summary}\n\n")

            detail = writeup.get("finding_detail")
            if detail:
                f.write(f"**Detail:** {detail}\n\n")

            ev = writeup.get("evidence_summary") or {}
            f.write(f"**Evidence:** {ev.get('n_samples', '?')} samples | "
                    f"{ev.get('n_stated_by_authors', '?')} author-stated | "
                    f"Materials: {', '.join(ev.get('materials_covered') or [])}\n\n")

            if ev.get("key_supporting"):
                f.write(f"**Supporting:** {ev['key_supporting']}\n\n")
            if ev.get("key_complicating"):
                f.write(f"**Complicating:** {ev['key_complicating']}\n\n")

            alt = writeup.get("alternative_explanations")
            if alt:
                f.write(f"**Alternative explanations:** {alt}\n\n")

            qrem = writeup.get("qrem_implications")
            if qrem:
                f.write(f"**QREM implications:** {qrem}\n\n")

            per_mat = writeup.get("per_material_recommendation")
            if per_mat:
                f.write(f"**Per-material recommendation:** {per_mat}\n\n")

            questions = writeup.get("questions_for_reviewer") or []
            if questions:
                f.write("**Questions for reviewer:**\n")
                for q in questions:
                    f.write(f"- {q}\n")
                f.write("\n")

            followup = writeup.get("suggested_followup")
            if followup:
                f.write(f"**Suggested follow-up:** {followup}\n\n")

            f.write(f"*Review status: {finding.get('review_status', 'pending')}*\n\n")
            f.write("---\n\n")

    print(f"  Markdown report written to {report_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Stage 04 — Corpus Mining Pipeline"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Phase A
    p_a = sub.add_parser("phase-a",
                          help="Evidence extraction (mechanical, no AI)")
    p_a.add_argument(
        "--db",
        type=Path,
        default=Path("../data/ingested/records.db"),
        help="SQLite database path",
    )
    p_a.add_argument(
        "--out",
        type=Path,
        default=Path("../data/ingested/mining_evidence.jsonl"),
        help="Output evidence tables JSONL",
    )
    p_a.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print full evidence tables",
    )

    # Phase B
    p_b = sub.add_parser("phase-b",
                          help="AI reasoning over evidence tables")
    p_b.add_argument(
        "--evidence",
        type=Path,
        default=Path("../data/ingested/mining_evidence.jsonl"),
        help="Evidence tables JSONL from Phase A",
    )
    p_b.add_argument(
        "--out",
        type=Path,
        default=Path("../data/ingested/mining_reasoned.jsonl"),
        help="Output reasoned tables JSONL",
    )
    p_b.add_argument(
        "--prior",
        type=Path,
        default=None,
        help="Prior approved findings JSONL (optional)",
    )

    # Phase C
    p_c = sub.add_parser("phase-c",
                          help="AI write-up of reasoned findings")
    p_c.add_argument(
        "--reasoned",
        type=Path,
        default=Path("../data/ingested/mining_reasoned.jsonl"),
        help="Reasoned tables JSONL from Phase B",
    )
    p_c.add_argument(
        "--out",
        type=Path,
        default=Path("../data/ingested/mining_findings.jsonl"),
        help="Output findings JSONL",
    )
    p_c.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Markdown report path (default: mining_findings_report.md)",
    )

    args = parser.parse_args()

    if args.command == "phase-a":
        if not args.db.exists():
            print(f"ERROR: database not found at {args.db}")
            print("Run build_sqlite.py first.")
            exit(1)
        run_phase_a(args.db, args.out, verbose=args.verbose)

    elif args.command == "phase-b":
        if not args.evidence.exists():
            print(f"ERROR: evidence file not found at {args.evidence}")
            print("Run phase-a first.")
            exit(1)
        run_phase_b(
            evidence_path=args.evidence,
            out_path=args.out,
            prior_findings_path=args.prior,
        )

    elif args.command == "phase-c":
        if not args.reasoned.exists():
            print(f"ERROR: reasoned file not found at {args.reasoned}")
            print("Run phase-b first.")
            exit(1)
        run_phase_c(
            reasoned_path=args.reasoned,
            out_path=args.out,
            report_path=args.report,
        )


if __name__ == "__main__":
    main()
