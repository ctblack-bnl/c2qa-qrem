#!/usr/bin/env python3
# ingester/build_sqlite.py
# Reads the ingested records JSONL and loads it into a SQLite database
# for easy browsing and inspection.
#
# Creates three tables:
#   papers  — one row per paper (metadata, relevance, outcome)
#   samples — one row per sample extracted from each paper
#   catchall_items — one row per catchall entry (additional measurements etc.)
#
# display_name field: a human-readable compound identifier for each sample,
# constructed as {first_author}_{year}_{sample_id} so samples are unambiguous
# across papers when browsing the database.
#
# derived_material field: normalized film_material for Phase A stratification.
#   - Strips parenthetical qualifiers: "Ta (with Al/AlOx junction)" → "Ta"
#   - Checks against KNOWN_MATERIALS whitelist
#   - Unknown materials → "other" (never sent to Phase B mining)
#   - Add new materials to KNOWN_MATERIALS as the corpus grows
#
# derived_substrate field: normalized substrate_material to canonical short list.
#   - "Si (high-resistivity, >20 kΩ cm)" → "Silicon"
#   - "Al2O3 (HEMEX sapphire)", "c-axis sapphire" → "Sapphire"
#   - "SiC" → "Silicon Carbide"
#   - "diamond" → "Diamond"
#   - Everything else → "Other"
#
# derived_deposition_method field: normalized deposition_method to canonical short list.
#   - "DC magnetron sputtering", "UHV dc magnetron sputtering" → "DC Sputtering"
#   - "RF magnetron sputtering" → "RF Sputtering"
#   - "e-beam evaporation", "ebeam evaporation" → "Ebeam Evaporation"
#   - "thermal evaporation" → "Thermal Evaporation"
#   - "MBE", "molecular beam epitaxy" → "MBE"
#   - "ALD", "atomic layer deposition" → "ALD"
#   - "CVD" → "CVD"
#   - "PLD", "pulsed laser deposition" → "PLD"
#   - Everything else (incl. patterning methods like EBL) → "Other"
#
# Stage 4 additions (May 2026):
#   qubit_frequency_GHz — qubit operating frequency, needed for pad TLS calculation
#   Q_TLS_0             — unsaturated TLS quality factor, preferred over Qi for loss model
#
# Confidence columns expanded (May 2026):
#   Added: tan_delta_confidence, T2_echo_confidence, surface_oxide_confidence,
#          film_thickness_confidence, junction_present_confidence,
#          resonator_gap_width_confidence
#
# Block 2.5 fabrication process chemistry additions (July 2026 — schema v0.15 / prompts.py v4):
#   12 new named fields (7 base-layer + 5 junction), each with a confidence column.
#   junction_present bug fix: column existed but was never populated in the insert — fixed.
#   New catchall item_type: fabrication_detail.
#
#   derived_resist_strip_family field: normalized resist_strip_chemistry to canonical short list.
#     - AZ 300T / AZ300T          → "AZ300T-family"
#     - MP 1165 / Remover PG      → "NMP-family"
#     - acetone-only sequences    → "acetone-only"
#     - not reported              → "none"
#     - anything else             → "other"
#
#   derived_post_fab_treatment_family field: normalized post_fabrication_surface_treatment.
#     Bin scheme designed July 10, 2026 against real extracted values from Hedrick 2026
#     and Olszewski 2026 — see materials_characterization_schema_v16.md for full rationale.
#     - explicit "none"                                   → "None"
#     - HF only                                           → "Acid-HF"
#     - BOE only                                          → "Acid-BOE"
#     - piranha only                                      → "Acid-Piranha"
#     - other single-acid chemistry                       → "Acid-other"
#     - solvent-only sequence (no acid/oxidizer)           → "Solvent"
#     - oxidizer only (H2O2, O2 plasma/ashing, ozone)       → "Oxidizer"
#     - two or more of {acid, oxidizer, solvent} chained,
#       or two or more distinct acid types chained          → "Combination"
#     - not reported                                       → "Unknown"
#     - unclassifiable                                     → "Other"
#
#   derived_junction_vacuum_class field: normalized junction_chamber_vacuum.
#     - "UHV" present       → "UHV"
#     - "HV" present         → "HV"
#     - not reported/unclear → "unknown"
#
# Usage:
#   cd ingester
#   python3 build_sqlite.py
#   # Then open data/ingested/records.db in any SQLite browser
import json
import re
import sqlite3
import argparse
import unicodedata
from pathlib import Path
from derive import derive_all, get_derived_value


def _norm(s):
    """
    Normalize a string to NFC (composed) Unicode form for reliable comparison.
    Filenames with accented characters (e.g. "García") can arrive encoded as
    either a single composed character or a base letter + combining accent
    mark — visually identical but byte-different, which silently breaks exact
    string/set matching (e.g. exclusions.json filename lookups). Normalizing
    both sides to NFC before comparing closes this class of bug for any
    future paper with accented author names.
    """
    if s is None:
        return None
    return unicodedata.normalize('NFC', s)

# ── Known superconducting materials for Phase A stratification ─────────────────
#
# Maps normalized film_material strings to themselves (identity).
# Anything not in this set → "other" in derived_material column.
#
# Rules:
#   - Use the standard abbreviation enforced by the extraction prompt
#   - Strip parentheticals before checking: "Ta (with Al/AlOx)" → "Ta"
#   - Add new materials here as the corpus grows (prompted by ⚠ warning in build output)
#   - Only intrinsic superconducting film materials — not junction or encapsulation materials
#
KNOWN_MATERIALS = {
    "Ta",       # tantalum
    "Nb",       # niobium
    "Al",       # aluminum
    "Re",       # rhenium
    "TiN",      # titanium nitride
    "NbN",      # niobium nitride
    "NbTiN",    # niobium titanium nitride
    "TaN",      # tantalum nitride
    "NbSe2",    # niobium diselenide
    "PtSi",     # platinum silicide
    "Ta-Hf",    # tantalum hafnium alloy (any stoichiometry)
    "Mo3Al2C",  # molybdenum aluminum carbide
}


def normalize_film_material(film_material: str) -> str:
    """
    Normalize film_material to a canonical material identity for Phase A
    stratification. Strips parenthetical qualifiers and checks against
    KNOWN_MATERIALS whitelist. Unknown materials → 'other'.
    """
    if not film_material:
        return "unknown"
    base = re.sub(r'\s*\(.*', '', film_material).strip()
    return base if base in KNOWN_MATERIALS else "other"


def normalize_substrate(substrate_material: str) -> str:
    """
    Normalize substrate_material to a canonical short list for Explorer filtering.
    Canonical values: Silicon, Sapphire, Silicon Carbide, Diamond, Other
    """
    if not substrate_material:
        return "Unknown"
    s = substrate_material.strip().lower()
    if any(x in s for x in ['al2o3', 'sapphire', 'c-al2o3']):
        return "Sapphire"
    if re.search(r'\bsic\b', s) or 'silicon carbide' in s:
        return "Silicon Carbide"
    if re.search(r'\bsi\b', s) or 'silicon' in s:
        return "Silicon"
    if 'diamond' in s:
        return "Diamond"
    return "Other"


def normalize_deposition_method(deposition_method: str) -> str:
    """
    Normalize deposition_method to a canonical short list for Explorer grouping.
    Canonical values: DC Sputtering, RF Sputtering, Ebeam Evaporation,
                      Thermal Evaporation, MBE, ALD, CVD, PLD, Other
    """
    if not deposition_method:
        return "Unknown"
    s = deposition_method.strip().lower()
    if 'mbe' in s or 'molecular beam' in s:
        return "MBE"
    if 'ald' in s or 'atomic layer' in s:
        return "ALD"
    if s == 'cvd' or 'chemical vapor' in s or re.search(r'\bcvd\b', s):
        return "CVD"
    if s == 'pld' or 'pulsed laser' in s or re.search(r'\bpld\b', s):
        return "PLD"
    if 'e-beam' in s or 'ebeam' in s or 'electron beam' in s:
        if 'lithograph' in s or 'ebl' in s:
            return "Other"
        return "Ebeam Evaporation"
    if 'thermal evap' in s or ('thermal' in s and 'evap' in s):
        return "Thermal Evaporation"
    if 'evap' in s:
        return "Thermal Evaporation"
    if 'rf' in s and ('sputter' in s or 'magnetron' in s):
        return "RF Sputtering"
    if ('dc' in s and ('sputter' in s or 'magnetron' in s)):
        return "DC Sputtering"
    if 'magnetron' in s and 'sputter' in s:
        return "DC Sputtering"
    if 'sputter' in s:
        return "DC Sputtering"
    return "Other"


def normalize_resist_strip(resist_strip_chemistry: str) -> str:
    """
    Normalize resist_strip_chemistry to a canonical short list for Explorer
    grouping. Canonical values: AZ300T-family, NMP-family, acetone-only, none, other

    Validated against real corpus values (Hedrick 2026, Olszewski 2026, July 2026):
      - Hedrick: "Remover PG at 80°C..." → NMP-family
      - Olszewski: "MP 1165..." → NMP-family; "IMM AZ 300T..." → AZ300T-family
    """
    if not resist_strip_chemistry:
        return "none"
    s = resist_strip_chemistry.strip().lower()
    if 'az 300t' in s or 'az300t' in s or 'az-300t' in s:
        return "AZ300T-family"
    if '1165' in s or 'remover pg' in s or 'nmp' in s:
        return "NMP-family"
    if 'acetone' in s and not any(x in s for x in ['1165', 'remover pg', 'az 300t', 'az300t', 'nmp']):
        return "acetone-only"
    return "other"


def normalize_post_fab_treatment(post_fabrication_surface_treatment: str) -> str:
    """
    Normalize post_fabrication_surface_treatment to a canonical short list
    for Explorer grouping.

    Canonical values: None, Acid-HF, Acid-BOE, Acid-Piranha, Acid-other,
                      Solvent, Oxidizer, Combination, Unknown, Other

    Bin scheme designed July 10, 2026 against real extracted values from
    Hedrick 2026 (arXiv) and Olszewski 2026 (APL) — see continuity doc and
    schema doc v0.16 for full rationale. Four scientific categories
    (Acid / Solvent / Oxidizer / Combination) plus None, with Acid further
    split by specific chemistry since acid type materially affects surface
    quality outcomes. Combination catches both cross-category sequences
    (e.g. oxidizer-then-acid) and multi-acid sequences (e.g. BOE-then-HF).
    """
    if not post_fabrication_surface_treatment:
        return "Unknown"
    s = post_fabrication_surface_treatment.strip().lower()

    if 'none' in s:
        return "None"

    has_hf = 'hf' in s or 'hydrofluoric' in s
    has_boe = 'boe' in s or 'buffered oxide etch' in s
    has_piranha = 'piranha' in s
    # peroxide/oxidizer markers — exclude "piranha" mentions of H2O2 (piranha is its own acid bin)
    has_oxidizer = (('h2o2' in s or 'peroxide' in s or 'ozone' in s
                     or 'o2 plasma' in s or 'o2 ashing' in s or 'ashing' in s)
                    and not has_piranha)
    has_solvent = any(x in s for x in [
        'solvent series', 'acetone', 'ipa', 'isopropanol', 'methanol',
        'pentane', 'toluene', 'di water'
    ]) and not (has_hf or has_boe or has_piranha or has_oxidizer)

    acid_types_present = sum([has_hf, has_boe, has_piranha])
    category_count = sum([
        acid_types_present > 0,
        has_oxidizer,
        has_solvent and acid_types_present == 0 and not has_oxidizer,
    ])

    # Multiple distinct acid types together (e.g. BOE then HF) → Combination
    if acid_types_present >= 2:
        return "Combination"

    # Cross-category combination (e.g. oxidizer then acid) → Combination
    if (acid_types_present > 0 and has_oxidizer):
        return "Combination"

    if acid_types_present == 1 and has_solvent:
        # Solvent cleaning alongside a single acid step is common prep context,
        # not a second treatment category — still classify by the acid.
        pass

    if has_hf:
        return "Acid-HF"
    if has_boe:
        return "Acid-BOE"
    if has_piranha:
        return "Acid-Piranha"
    if has_oxidizer:
        return "Oxidizer"
    if has_solvent:
        return "Solvent"
    if acid_types_present > 0:
        return "Acid-other"

    return "Other"


def normalize_junction_vacuum(junction_chamber_vacuum: str) -> str:
    """
    Normalize junction_chamber_vacuum to a canonical short list for Explorer
    grouping. Canonical values: UHV, HV, unknown

    Not yet validated against real corpus data — no ingested paper to date
    reports this field (Hedrick and Olszewski are both non-junction-focused
    for this measurement). Logic drawn from prompts.py v4 examples
    ("UHV, base 3e-10 Torr (Plassys MEB550S)", "HV, base <2e-8 Torr").
    Revisit once a junction-heavy paper (e.g. Joshi 2026) is rebuilt into the DB.
    """
    if not junction_chamber_vacuum:
        return "unknown"
    s = junction_chamber_vacuum.strip().lower()
    if 'uhv' in s:
        return "UHV"
    if re.search(r'\bhv\b', s):
        return "HV"
    return "unknown"


def make_display_name(authors: str, sample_id: str) -> str:
    """
    Build a human-readable display name for a sample.
    Format: {first_author_lastname}_{year}_{sample_id}
    """
    if not authors:
        first_author = "Unknown"
        year = "????"
    else:
        first_author = authors.strip().split()[0].rstrip(",")
        year_match = re.search(r'\b(20\d{2})\b', authors)
        year = year_match.group(1) if year_match else "????"
    clean_sid = str(sample_id).strip().replace(" ", "_").replace("/", "-")
    return f"{first_author}_{year}_{clean_sid}"


def build_sqlite(jsonl_path: Path, db_path: Path) -> None:
    print(f"Reading: {jsonl_path}")

    # --- Load all records ---
    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  Skipping malformed line: {e}")

    print(f"Loaded {len(records)} records")

    # --- Load deduplication decisions ---
    dedup_path = jsonl_path.parent / "deduplication.json"
    skip_filenames = set()
    if dedup_path.exists():
        try:
            dedup = json.loads(dedup_path.read_text())
            for decision in dedup.get("decisions", []):
                if decision.get("decision") == "duplicate":
                    keep = decision.get("keep")
                    paper_a = decision.get("paper_a")
                    paper_b = decision.get("paper_b")
                    if keep == paper_a:
                        skip_filenames.add(paper_b)
                    elif keep == paper_b:
                        skip_filenames.add(paper_a)
            if skip_filenames:
                print(f"Deduplication: skipping {len(skip_filenames)} duplicate(s): {skip_filenames}")
        except Exception as e:
            print(f"  Warning: could not load deduplication.json: {e}")

    before = len(records)
    records = [r for r in records if r.get("filename") not in skip_filenames]
    if before != len(records):
        print(f"  Filtered {before - len(records)} duplicate record(s)")

    # --- Load manual exclusions ---
    exclusions_path = jsonl_path.parent / "exclusions.json"
    excluded_dois      = set()
    excluded_arxiv_ids = set()
    excluded_filenames_excl = set()
    if exclusions_path.exists():
        try:
            excl_data = json.loads(exclusions_path.read_text())
            for entry in excl_data.get("exclusions", []):
                if entry.get("doi"):
                    excluded_dois.add(entry["doi"])
                if entry.get("arxiv_id"):
                    excluded_arxiv_ids.add(entry["arxiv_id"])
                if entry.get("filename"):
                    excluded_filenames_excl.add(_norm(entry["filename"]))
            n_excl = len(excl_data.get("exclusions", []))
            print(f"Exclusions: loaded {n_excl} manual exclusion(s) from exclusions.json")
        except Exception as e:
            print(f"  Warning: could not load exclusions.json: {e}")

    def _is_excluded(rec: dict) -> bool:
        if rec.get("doi") and rec["doi"] in excluded_dois:
            return True
        if rec.get("arxiv_id") and rec["arxiv_id"] in excluded_arxiv_ids:
            return True
        if rec.get("filename") and _norm(rec["filename"]) in excluded_filenames_excl:
            return True
        return False

    before = len(records)
    records = [r for r in records if not _is_excluded(r)]
    n_excluded = before - len(records)
    if n_excluded:
        print(f"  Excluded {n_excluded} manually excluded record(s)")

    seen = {}
    for r in records:
        seen[r.get("filename")] = r
    if len(seen) < len(records):
        print(f"  De-duplicated {len(records) - len(seen)} repeated filename(s) — keeping latest record")
    records = list(seen.values())

    # --- Connect to SQLite ---
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- Create tables ---
    cur.executescript("""
        DROP TABLE IF EXISTS papers;
        DROP TABLE IF EXISTS samples;
        DROP TABLE IF EXISTS catchall_items;

        CREATE TABLE papers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            filename            TEXT,
            processed_at        TEXT,
            outcome             TEXT,
            relevance           TEXT,
            relevance_reason    TEXT,
            paper_type          TEXT,
            doi                 TEXT,
            arxiv_id            TEXT,
            title               TEXT,
            authors             TEXT,
            journal             TEXT,
            human_reviewed      INTEGER DEFAULT 0,
            human_approved      INTEGER DEFAULT 0,
            num_samples         INTEGER DEFAULT 0,
            error               TEXT,
            extraction_json     TEXT
        );

        CREATE TABLE samples (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id                INTEGER REFERENCES papers(id),
            filename                TEXT,
            sample_id               TEXT,
            display_name            TEXT,

            -- Sample description
            substrate_material      TEXT,
            substrate_orientation   TEXT,
            film_material           TEXT,
            film_crystal_phase      TEXT,
            film_thickness_nm       TEXT,
            deposition_method       TEXT,
            deposition_temperature_C TEXT,
            annealing_temperature_C TEXT,
            annealing_duration_s    TEXT,
            junction_present        TEXT,

            -- Measurements
            Tc_K                    TEXT,
            RRR                     TEXT,
            sheet_resistance_Ohm_sq TEXT,
            loss_tangent_substrate  TEXT,
            loss_tangent_interface  TEXT,
            tan_delta_effective_surface TEXT,
            TLS_density             TEXT,
            Qi_internal             TEXT,
            Qi_single_photon        TEXT,
            surface_oxide_nm        TEXT,
            T1_us                   TEXT,
            T2_echo_us              TEXT,
            T2_ramsey_us            TEXT,
            gate_1q_fidelity_pct    TEXT,
            gate_2q_fidelity_pct    TEXT,

            -- R vs T derived fields
            normal_state_resistance_Ohm     TEXT,
            room_temperature_resistance_Ohm TEXT,
            measured_structure_width_um     TEXT,
            measured_structure_length_um    TEXT,

            -- Confidence flags (original four)
            Tc_confidence           TEXT,
            RRR_confidence          TEXT,
            Qi_confidence           TEXT,
            T1_confidence           TEXT,

            -- Confidence flags (added May 2026)
            tan_delta_confidence        TEXT,
            T2_echo_confidence          TEXT,
            surface_oxide_confidence    TEXT,
            film_thickness_confidence   TEXT,
            junction_present_confidence TEXT,
            resonator_gap_width_confidence TEXT,

            -- Fabrication process chemistry (Block 2.5, added July 2026 — schema v0.15 / prompts.py v4)
            substrate_prep_before_deposition TEXT,
            in_situ_substrate_bake_temperature_C TEXT,
            film_deposition_conditions TEXT,
            film_etch_chemistry TEXT,
            resist_strip_chemistry TEXT,
            post_fabrication_surface_treatment TEXT,
            dicing_protocol TEXT,
            junction_pre_deposition_surface_treatment TEXT,
            junction_developer TEXT,
            junction_chamber_vacuum TEXT,
            junction_oxidation_protocol TEXT,
            junction_liftoff_chemistry TEXT,

            -- Fabrication process chemistry confidence flags (added July 2026)
            substrate_prep_before_deposition_confidence TEXT,
            in_situ_substrate_bake_temperature_C_confidence TEXT,
            film_deposition_conditions_confidence TEXT,
            film_etch_chemistry_confidence TEXT,
            resist_strip_chemistry_confidence TEXT,
            post_fabrication_surface_treatment_confidence TEXT,
            dicing_protocol_confidence TEXT,
            junction_pre_deposition_surface_treatment_confidence TEXT,
            junction_developer_confidence TEXT,
            junction_chamber_vacuum_confidence TEXT,
            junction_oxidation_protocol_confidence TEXT,
            junction_liftoff_chemistry_confidence TEXT,

            -- Derived quantities (computed by build_sqlite.py)
            derived_resistivity_uOhm_cm      REAL,
            derived_BCS_gap_meV              REAL,
            derived_coherence_length_nm      REAL,
            derived_kinetic_inductance_pH_sq REAL,
            derived_RRR_from_RvT             REAL,
            derived_sheet_resistance_Ohm_sq  REAL,
            derived_json                     TEXT,

            -- derived_Qi: best available Qi for plotting. Single-photon preferred.
            derived_Qi                       REAL,
            -- derived_T2_us: best available T2. Echo preferred; falls back to Ramsey.
            derived_T2_us                    REAL,
            -- derived_tan_delta: best available surface loss tangent.
            -- Priority: tan_delta_effective_surface → loss_tangent_interface → loss_tangent_substrate
            derived_tan_delta                REAL,

            -- derived_material: normalized film_material for Phase A stratification.
            derived_material        TEXT,
            -- derived_substrate: normalized substrate_material for Explorer filtering.
            derived_substrate       TEXT,
            -- derived_deposition_method: normalized deposition_method for Explorer grouping.
            derived_deposition_method TEXT,

            -- derived_resist_strip_family: normalized resist_strip_chemistry for Explorer grouping.
            derived_resist_strip_family TEXT,
            -- derived_post_fab_treatment_family: normalized post_fabrication_surface_treatment.
            derived_post_fab_treatment_family TEXT,
            -- derived_junction_vacuum_class: normalized junction_chamber_vacuum.
            derived_junction_vacuum_class TEXT,

            -- Resonator geometry fields (Stage 4 — tan_delta extraction)
            resonator_type          TEXT,
            resonator_gap_width_um  TEXT,
            p_MS_resonator          TEXT,
            p_MS_pad                TEXT,

            -- Stage 4: device fields for T1 decomposition
            qubit_frequency_GHz     TEXT,
            Q_TLS_0                 TEXT,

            -- Promoted May 2026 from catchall (frequency-driven schema evolution)
            mean_free_path_nm               TEXT,
            vortex_activation_temperature_K TEXT,
            kinetic_inductance_sheet_pH_sq  TEXT,

            -- Similarity profile (Pass 3, AI-generated)
            sim_material_class      TEXT,
            sim_transport_regime    TEXT,
            sim_loss_mechanisms     TEXT,
            sim_device_type         TEXT,
            sim_coherence_tier      TEXT,
            sim_science_focus       TEXT,
            sim_growth_method       TEXT,
            sim_key_correlations    TEXT,
            sim_profile_notes       TEXT,
            sim_profile_version     TEXT,

            -- Full sample JSON
            sample_json             TEXT
        );

        CREATE TABLE catchall_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id        INTEGER REFERENCES papers(id),
            filename        TEXT,
            sample_id       TEXT,
            display_name    TEXT,
            item_type       TEXT,
            description     TEXT,
            value           TEXT,
            source          TEXT,
            notes           TEXT
        );
    """)

    # --- Helper to extract a field value and confidence ---
    def get_field(sample: dict, field: str) -> tuple:
        """Returns (value_str, confidence_str) for a field."""
        f = sample.get(field)
        if f is None:
            return None, None
        if isinstance(f, dict):
            val = f.get("value")
            conf = f.get("confidence")
            return (str(val) if val is not None else None), conf
        return str(f), None

    # --- Insert records ---
    papers_inserted = 0
    samples_inserted = 0
    catchall_inserted = 0
    profiles_found = 0

    for rec in records:
        ext = rec.get("extraction_json") or {}
        outcome = rec.get("outcome", "unknown")
        error = rec.get("error")
        error_str = json.dumps(error) if error else None

        samples = ext.get("samples", [])
        num_samples = len(samples)
        authors = rec.get("authors") or ext.get("authors") or ""

        cur.execute("""
            INSERT INTO papers (
                filename, processed_at, outcome, relevance, relevance_reason,
                paper_type, doi, arxiv_id, title, authors, journal,
                human_reviewed, human_approved, num_samples, error, extraction_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.get("filename"),
            rec.get("processed_at"),
            outcome,
            rec.get("relevance") or ext.get("relevance"),
            rec.get("relevance_reason"),
            rec.get("paper_type") or ext.get("paper_type"),
            rec.get("doi") or ext.get("doi"),
            rec.get("arxiv_id") or ext.get("arxiv_id"),
            rec.get("title") or ext.get("title"),
            authors,
            rec.get("journal") or ext.get("journal_or_preprint"),
            1 if rec.get("human_reviewed") else 0,
            1 if rec.get("human_approved") else 0,
            num_samples,
            error_str,
            json.dumps(ext) if ext else None,
        ))
        paper_id = cur.lastrowid
        papers_inserted += 1

        similarity_profiles = rec.get("similarity_profiles") or {}

        for sample in samples:
            sid = sample.get("sample_id", "unknown")
            display_name = make_display_name(authors, sid)

            def gf(field):
                return get_field(sample, field)

            # Compute derived quantities
            derived = derive_all(sample)

            # Normalization columns
            film_mat_raw = gf("film_material")[0]
            derived_material = normalize_film_material(film_mat_raw) if film_mat_raw else "unknown"

            substrate_raw = gf("substrate_material")[0]
            derived_substrate = normalize_substrate(substrate_raw) if substrate_raw else "Unknown"

            deposition_raw = gf("deposition_method")[0]
            derived_deposition_method = normalize_deposition_method(deposition_raw) if deposition_raw else "Unknown"

            # Fabrication process chemistry normalization (added July 2026)
            resist_strip_raw = gf("resist_strip_chemistry")[0]
            derived_resist_strip_family = normalize_resist_strip(resist_strip_raw)

            post_fab_raw = gf("post_fabrication_surface_treatment")[0]
            derived_post_fab_treatment_family = normalize_post_fab_treatment(post_fab_raw)

            junction_vacuum_raw = gf("junction_chamber_vacuum")[0]
            derived_junction_vacuum_class = normalize_junction_vacuum(junction_vacuum_raw)

            # derived_Qi — single-photon preferred; falls back to internal Qi
            derived_Qi = gf("Qi_single_photon")[0] or gf("Qi_internal_quality_factor")[0]

            # derived_T2_us — echo preferred; falls back to Ramsey
            derived_T2_us = gf("T2_echo_us")[0] or gf("T2_ramsey_us")[0]

            # derived_tan_delta — best available surface loss tangent
            # Priority: tan_delta_effective_surface → loss_tangent_interface → loss_tangent_substrate
            derived_tan_delta = (
                gf("tan_delta_effective_surface")[0] or
                gf("loss_tangent_interface")[0] or
                gf("loss_tangent_substrate")[0]
            )

            # derived_resistivity_uOhm_cm — geometry derivation first, then directly reported value
            _derived_resistivity = get_derived_value(derived, "derived_resistivity_uOhm_cm")
            if _derived_resistivity is None:
                _derived_resistivity = gf("normal_state_resistivity_uOhm_cm")[0]

            # Similarity profile
            profile = similarity_profiles.get(sid, {})
            if profile:
                profiles_found += 1

            cur.execute("""
                INSERT INTO samples (
                    paper_id, filename, sample_id, display_name,
                    substrate_material, substrate_orientation,
                    film_material, film_crystal_phase, film_thickness_nm,
                    deposition_method, deposition_temperature_C,
                    annealing_temperature_C, annealing_duration_s,
                    junction_present,
                    Tc_K, RRR, sheet_resistance_Ohm_sq,
                    loss_tangent_substrate, loss_tangent_interface,
                    tan_delta_effective_surface,
                    TLS_density, Qi_internal, Qi_single_photon,
                    surface_oxide_nm, T1_us, T2_echo_us, T2_ramsey_us,
                    gate_1q_fidelity_pct, gate_2q_fidelity_pct,
                    normal_state_resistance_Ohm,
                    room_temperature_resistance_Ohm,
                    measured_structure_width_um,
                    measured_structure_length_um,
                    Tc_confidence, RRR_confidence,
                    Qi_confidence, T1_confidence,
                    tan_delta_confidence, T2_echo_confidence,
                    surface_oxide_confidence, film_thickness_confidence,
                    junction_present_confidence, resonator_gap_width_confidence,
                    substrate_prep_before_deposition,
                    in_situ_substrate_bake_temperature_C,
                    film_deposition_conditions,
                    film_etch_chemistry,
                    resist_strip_chemistry,
                    post_fabrication_surface_treatment,
                    dicing_protocol,
                    junction_pre_deposition_surface_treatment,
                    junction_developer,
                    junction_chamber_vacuum,
                    junction_oxidation_protocol,
                    junction_liftoff_chemistry,
                    substrate_prep_before_deposition_confidence,
                    in_situ_substrate_bake_temperature_C_confidence,
                    film_deposition_conditions_confidence,
                    film_etch_chemistry_confidence,
                    resist_strip_chemistry_confidence,
                    post_fabrication_surface_treatment_confidence,
                    dicing_protocol_confidence,
                    junction_pre_deposition_surface_treatment_confidence,
                    junction_developer_confidence,
                    junction_chamber_vacuum_confidence,
                    junction_oxidation_protocol_confidence,
                    junction_liftoff_chemistry_confidence,
                    derived_resistivity_uOhm_cm,
                    derived_BCS_gap_meV,
                    derived_coherence_length_nm,
                    derived_kinetic_inductance_pH_sq,
                    derived_RRR_from_RvT,
                    derived_sheet_resistance_Ohm_sq,
                    derived_json,
                    derived_material,
                    derived_substrate,
                    derived_deposition_method,
                    derived_resist_strip_family,
                    derived_post_fab_treatment_family,
                    derived_junction_vacuum_class,
                    resonator_type,
                    resonator_gap_width_um,
                    p_MS_resonator,
                    p_MS_pad,
                    qubit_frequency_GHz,
                    Q_TLS_0,
                    mean_free_path_nm,
                    vortex_activation_temperature_K,
                    kinetic_inductance_sheet_pH_sq,
                    derived_Qi,
                    derived_T2_us,
                    derived_tan_delta,
                    sim_material_class, sim_transport_regime,
                    sim_loss_mechanisms, sim_device_type,
                    sim_coherence_tier, sim_science_focus,
                    sim_growth_method, sim_key_correlations,
                    sim_profile_notes, sim_profile_version,
                    sample_json
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?
                )
            """, (
                paper_id, rec.get("filename"), sid, display_name,
                gf("substrate_material")[0],
                gf("substrate_orientation")[0],
                gf("film_material")[0],
                gf("film_crystal_phase")[0],
                gf("film_thickness_nm")[0],
                gf("deposition_method")[0],
                gf("deposition_temperature_C")[0],
                gf("annealing_temperature_C")[0],
                gf("annealing_duration_s")[0],
                gf("junction_present")[0],
                gf("Tc_K")[0],
                gf("RRR")[0],
                gf("sheet_resistance_Ohm_sq")[0],
                gf("loss_tangent_substrate")[0],
                gf("loss_tangent_interface")[0],
                gf("tan_delta_effective_surface")[0],
                gf("TLS_density_per_GHz_per_um2")[0],
                gf("Qi_internal_quality_factor")[0],
                gf("Qi_single_photon")[0],
                gf("surface_oxide_thickness_nm")[0],
                gf("T1_us")[0],
                gf("T2_echo_us")[0],
                gf("T2_ramsey_us")[0],
                gf("single_qubit_gate_fidelity_pct")[0],
                gf("two_qubit_gate_fidelity_pct")[0],
                gf("normal_state_resistance_Ohm")[0],
                gf("room_temperature_resistance_Ohm")[0],
                gf("measured_structure_width_um")[0],
                gf("measured_structure_length_um")[0],
                # Original four confidence columns
                gf("Tc_K")[1],
                gf("RRR")[1],
                gf("Qi_internal_quality_factor")[1],
                gf("T1_us")[1],
                # Six confidence columns (May 2026)
                gf("tan_delta_effective_surface")[1],
                gf("T2_echo_us")[1],
                gf("surface_oxide_thickness_nm")[1],
                gf("film_thickness_nm")[1],
                gf("junction_present")[1],
                gf("resonator_gap_width_um")[1],
                # Block 2.5 fabrication fields (July 2026)
                gf("substrate_prep_before_deposition")[0],
                gf("in_situ_substrate_bake_temperature_C")[0],
                gf("film_deposition_conditions")[0],
                gf("film_etch_chemistry")[0],
                gf("resist_strip_chemistry")[0],
                gf("post_fabrication_surface_treatment")[0],
                gf("dicing_protocol")[0],
                gf("junction_pre_deposition_surface_treatment")[0],
                gf("junction_developer")[0],
                gf("junction_chamber_vacuum")[0],
                gf("junction_oxidation_protocol")[0],
                gf("junction_liftoff_chemistry")[0],
                # Block 2.5 fabrication field confidence columns (July 2026)
                gf("substrate_prep_before_deposition")[1],
                gf("in_situ_substrate_bake_temperature_C")[1],
                gf("film_deposition_conditions")[1],
                gf("film_etch_chemistry")[1],
                gf("resist_strip_chemistry")[1],
                gf("post_fabrication_surface_treatment")[1],
                gf("dicing_protocol")[1],
                gf("junction_pre_deposition_surface_treatment")[1],
                gf("junction_developer")[1],
                gf("junction_chamber_vacuum")[1],
                gf("junction_oxidation_protocol")[1],
                gf("junction_liftoff_chemistry")[1],
                # Derived quantities
                _derived_resistivity,
                get_derived_value(derived, "derived_BCS_gap_meV"),
                get_derived_value(derived, "derived_coherence_length_nm"),
                get_derived_value(derived, "derived_kinetic_inductance_pH_sq"),
                get_derived_value(derived, "derived_RRR_from_RvT"),
                get_derived_value(derived, "derived_sheet_resistance_Ohm_sq"),
                json.dumps(derived) if derived else None,
                derived_material,
                derived_substrate,
                derived_deposition_method,
                derived_resist_strip_family,
                derived_post_fab_treatment_family,
                derived_junction_vacuum_class,
                gf("resonator_type")[0],
                gf("resonator_gap_width_um")[0],
                gf("p_MS_resonator")[0],
                gf("p_MS_pad")[0],
                gf("qubit_frequency_GHz")[0],
                gf("Q_TLS_0")[0],
                gf("mean_free_path_nm")[0],
                gf("vortex_activation_temperature_K")[0],
                gf("kinetic_inductance_sheet_pH_sq")[0],
                derived_Qi,
                derived_T2_us,
                derived_tan_delta,
                profile.get("material_class"),
                profile.get("transport_regime"),
                json.dumps(profile.get("loss_mechanisms") or []),
                profile.get("device_type"),
                profile.get("coherence_tier"),
                json.dumps(profile.get("science_focus") or []),
                profile.get("growth_method"),
                json.dumps(profile.get("key_correlations") or []),
                profile.get("profile_notes"),
                profile.get("profile_version"),
                json.dumps(sample),
            ))
            samples_inserted += 1

            # Insert catchall items
            catchall = sample.get("catchall", {})

            for item in catchall.get("additional_measurements", []):
                cur.execute("""
                    INSERT INTO catchall_items
                    (paper_id, filename, sample_id, display_name, item_type,
                     description, value, source, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    paper_id, rec.get("filename"), sid, display_name,
                    "additional_measurement",
                    item.get("description"),
                    item.get("value"),
                    item.get("source"),
                    item.get("suspected_relevance"),
                ))
                catchall_inserted += 1

            for item in catchall.get("anomalous_observations", []):
                cur.execute("""
                    INSERT INTO catchall_items
                    (paper_id, filename, sample_id, display_name, item_type,
                     description, value, source, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    paper_id, rec.get("filename"), sid, display_name,
                    "anomalous_observation",
                    item.get("description"),
                    None,
                    None,
                    item.get("hypothesis"),
                ))
                catchall_inserted += 1

            for item in catchall.get("correlations_observed", []):
                cur.execute("""
                    INSERT INTO catchall_items
                    (paper_id, filename, sample_id, display_name, item_type,
                     description, value, source, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    paper_id, rec.get("filename"), sid, display_name,
                    "correlation",
                    item.get("description"),
                    f"{item.get('measurement_a')} vs {item.get('measurement_b')}",
                    None,
                    item.get("nature"),
                ))
                catchall_inserted += 1

            # fabrication_details — new catchall type (July 2026, schema v0.15 / prompts.py v4)
            # Previously silently dropped: prompts.py extracted this section but
            # build_sqlite.py had no insert block for it. Fixed here.
            for item in catchall.get("fabrication_details", []):
                cur.execute("""
                    INSERT INTO catchall_items
                    (paper_id, filename, sample_id, display_name, item_type,
                     description, value, source, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    paper_id, rec.get("filename"), sid, display_name,
                    "fabrication_detail",
                    item.get("description"),
                    None,
                    item.get("source"),
                    None,  # no suspected_relevance for this type — assessed during mining
                ))
                catchall_inserted += 1

            for item in catchall.get("schema_promotion_candidates", []):
                cur.execute("""
                    INSERT INTO catchall_items
                    (paper_id, filename, sample_id, display_name, item_type,
                     description, value, source, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    paper_id, rec.get("filename"), sid, display_name,
                    "schema_candidate",
                    item.get("parameter"),
                    item.get("description"),
                    item.get("source"),
                    item.get("why_important"),
                ))
                catchall_inserted += 1

    # --- Unrecognized materials report ---
    cur.execute("""
        SELECT film_material, COUNT(*) as n
        FROM samples
        WHERE derived_material = 'other'
        AND film_material IS NOT NULL
        AND film_material != ''
        GROUP BY film_material
        ORDER BY n DESC
    """)
    unrecognized = cur.fetchall()

    # --- Unrecognized substrates report ---
    cur.execute("""
        SELECT substrate_material, COUNT(*) as n
        FROM samples
        WHERE derived_substrate = 'Other'
        AND substrate_material IS NOT NULL
        AND substrate_material != ''
        GROUP BY substrate_material
        ORDER BY n DESC
    """)
    unrecognized_substrates = cur.fetchall()

    # --- Fabrication family breakdown report (July 2026) ---
    cur.execute("""
        SELECT derived_resist_strip_family, COUNT(*) as n
        FROM samples
        WHERE resist_strip_chemistry IS NOT NULL
        GROUP BY derived_resist_strip_family
        ORDER BY n DESC
    """)
    resist_strip_breakdown = cur.fetchall()

    cur.execute("""
        SELECT derived_post_fab_treatment_family, COUNT(*) as n
        FROM samples
        WHERE post_fabrication_surface_treatment IS NOT NULL
        GROUP BY derived_post_fab_treatment_family
        ORDER BY n DESC
    """)
    post_fab_breakdown = cur.fetchall()

    conn.commit()
    conn.close()

    # --- Summary ---
    print(f"Done.")
    print(f"  Papers inserted  : {papers_inserted}")
    print(f"  Samples inserted : {samples_inserted}")
    print(f"  Catchall items   : {catchall_inserted}")
    print(f"  Profiles found   : {profiles_found} of {samples_inserted} samples")
    print(f"  Database written : {db_path}")

    if unrecognized:
        print(f"\n  ⚠ Unrecognized film materials ({len(unrecognized)} types assigned to 'other'):")
        print(f"    These will NOT be stratified in Phase A mining.")
        print(f"    If any are superconducting materials worth tracking,")
        print(f"    add them to KNOWN_MATERIALS in build_sqlite.py and rebuild.")
        for row in unrecognized:
            print(f"    {str(row[0]):<50} : {row[1]} sample(s)")
    else:
        print(f"\n  ✓ All film materials recognized — no 'other' stratification bin")

    if unrecognized_substrates:
        print(f"\n  ℹ Substrates mapped to 'Other' ({len(unrecognized_substrates)} types):")
        print(f"    These appear in Explorer as 'Other'. Add to normalize_substrate()")
        print(f"    if any should be broken out as a distinct canonical category.")
        for row in unrecognized_substrates:
            print(f"    {str(row[0]):<60} : {row[1]} sample(s)")

    if resist_strip_breakdown:
        print(f"\n  ℹ derived_resist_strip_family breakdown ({sum(r[1] for r in resist_strip_breakdown)} samples with data):")
        for row in resist_strip_breakdown:
            print(f"    {str(row[0]):<20} : {row[1]} sample(s)")

    if post_fab_breakdown:
        print(f"\n  ℹ derived_post_fab_treatment_family breakdown ({sum(r[1] for r in post_fab_breakdown)} samples with data):")
        for row in post_fab_breakdown:
            print(f"    {str(row[0]):<20} : {row[1]} sample(s)")

    print()
    print("To browse: open records.db in DB Browser for SQLite (sqlitebrowser.org)")
    print()
    print("Useful queries:")
    print("  SELECT display_name, film_material, derived_material, Tc_K, RRR, Qi_internal FROM samples;")
    print("  SELECT derived_material, COUNT(*) as n FROM samples GROUP BY derived_material ORDER BY n DESC;")
    print("  SELECT derived_substrate, COUNT(*) as n FROM samples GROUP BY derived_substrate ORDER BY n DESC;")
    print("  SELECT derived_deposition_method, COUNT(*) as n FROM samples GROUP BY derived_deposition_method ORDER BY n DESC;")
    print("  SELECT display_name, qubit_frequency_GHz, Q_TLS_0, p_MS_pad, p_MS_resonator FROM samples WHERE qubit_frequency_GHz IS NOT NULL;")
    print("  SELECT display_name, derived_material, derived_tan_delta, tan_delta_effective_surface FROM samples WHERE derived_tan_delta IS NOT NULL ORDER BY derived_tan_delta;")
    print("  SELECT display_name, sim_material_class, sim_device_type, sim_coherence_tier FROM samples WHERE sim_profile_version IS NOT NULL;")
    print("  SELECT display_name, item_type, description FROM catchall_items LIMIT 20;")
    print("  SELECT outcome, COUNT(*) FROM papers GROUP BY outcome;")
    print("  SELECT display_name, resist_strip_chemistry, derived_resist_strip_family FROM samples WHERE resist_strip_chemistry IS NOT NULL;")
    print("  SELECT display_name, post_fabrication_surface_treatment, derived_post_fab_treatment_family FROM samples WHERE post_fabrication_surface_treatment IS NOT NULL;")
    print("  SELECT display_name, junction_chamber_vacuum, derived_junction_vacuum_class FROM samples WHERE junction_chamber_vacuum IS NOT NULL;")
    print("  SELECT item_type, COUNT(*) FROM catchall_items GROUP BY item_type;")
    print("  SELECT display_name, Tc_confidence, RRR_confidence, Qi_confidence, T1_confidence,")
    print("         tan_delta_confidence, T2_echo_confidence, surface_oxide_confidence,")
    print("         film_thickness_confidence, junction_present_confidence, resonator_gap_width_confidence")
    print("  FROM samples WHERE Tc_confidence IS NOT NULL ORDER BY display_name;")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build SQLite database from ingested records JSONL."
    )
    parser.add_argument(
        "--in",
        dest="jsonl_path",
        type=Path,
        default=Path("../data/ingested/records.jsonl"),
        help="Input JSONL file (default: ../data/ingested/records.jsonl)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("../data/ingested/records.db"),
        help="Output SQLite database (default: ../data/ingested/records.db)"
    )
    args = parser.parse_args()
    build_sqlite(args.jsonl_path, args.out)
