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
# Junction identity fields wired (August 2026 — schema v0.18 / prompts.py v5-fields
# Pass B): junction_material, junction_fabrication_method, junction_area_um2,
# junction_resistance_normal_Ohm, each with a confidence column. Confirmed genuinely
# absent from both this file and prompts.py before this change — not a rarity, a
# real missing slot (the other five junction process-chemistry fields, added July
# 2026, were already wired; these four core identity fields were apparently never
# carried through to either side). Column/placeholder/gf() alignment verified by
# direct positional cross-check and a live SQL execution smoke test before shipping,
# given how easy an off-by-one is to introduce silently in an INSERT this wide (118
# columns) — an early edit did in fact introduce one (the confidence-column section
# had new fields in a different order in the column list than in the values tuple,
# silently shifting resonator_gap_width_confidence and beyond by one), caught by
# that check before it reached real data.
#
#   derived_resist_strip_family field: normalized resist_strip_chemistry to canonical short list.
#     - AZ 300T / AZ300T          → "AZ300T-family"
#     - MP 1165 / Remover PG      → "NMP-family"
#     - acetone-only sequences    → "acetone-only"
#     - not reported              → "unknown"
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
        return "unknown"
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


def normalize_bool_field(value) -> int:
    """
    Normalize a boolean-shaped extraction value to a clean integer: 1 (yes),
    0 (no), or None (not reported / unrecognized value).

    Handles the same raw-value inconsistency regardless of which field it's
    called on: raw extraction values show up as Python booleans (True/False)
    and as strings ("true"/"false"), which str()-ify to four distinct text
    values (True, False, true, false) if stored unnormalized — meaning a
    query like WHERE field = 'true' silently misses rows stored as 'True'.

    Uses 0/1 (not "true"/"false" text) to match the existing convention for
    boolean-like columns in this schema (human_reviewed, human_approved in
    the papers table are both INTEGER).
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ('true', '1', 'yes'):
        return 1
    if s in ('false', '0', 'no'):
        return 0
    return None


def normalize_junction_present(junction_present) -> int:
    """
    Normalize junction_present to a clean integer: 1 (yes), 0 (no), or None
    (not reported / unrecognized value).

    Fixes a real inconsistency: raw extraction values have shown up as
    Python booleans (True/False) and as strings ("true"/"false"), which
    str()-ify to four distinct text values (True, False, true, false) in
    the raw column — meaning a query like WHERE junction_present = 'true'
    silently misses rows stored as 'True'. Normalized here the same way
    junction_present's own bug (column declared but never populated) was
    fixed in build_sqlite.py on July 10 — this closes the follow-on
    consistency gap in the same field.

    Thin wrapper around normalize_bool_field() (added Aug 12, 2026, when
    individual_assignment_disclosed needed the identical normalization) —
    kept as a separate name since existing call sites and docs reference it.
    """
    return normalize_bool_field(junction_present)


def derive_arxiv_id_from_doi(doi: str) -> str:
    """
    Extract the arXiv identifier from an arXiv DOI, e.g.
    '10.48550/arXiv.2306.12345' -> '2306.12345'.

    Deterministic string transform, not a physical derivation — no
    provenance/confidence needed, just a fallback when extraction left
    arxiv_id null but the DOI itself is an arXiv DOI. Added July 2026:
    found 26 ingested papers with a 10.48550/arXiv.* DOI and a null
    arxiv_id, which should never depend on AI extraction to fill in.

    Only matches the DOI path deliberately — does not scan other free-text
    fields (e.g. notes) for arXiv-ID-shaped strings, to avoid picking up
    a cited reference's arXiv number instead of the paper's own.
    """
    if not doi:
        return None
    m = re.match(r'10\.48550/arxiv\.(.+)$', doi.strip(), re.IGNORECASE)
    return m.group(1) if m else None


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


def _parse_clean_numeric(value) -> float:
    """
    Try to parse a clean float out of a catchall item's value field.
    Returns None if it doesn't parse unambiguously — absence over
    guessing, matching the project's sparse-extraction principle.

    Handles, in order:
      - a trailing explanatory parenthetical, e.g.
        "133 +/- 53.3 nm (calculated from Wiedemann-Franz law)"
      - a leading short variable-name prefix, e.g. "le = 0.5 nm",
        "lambda_N = 133 +/- 53.3 nm"
      - "value +/- uncertainty unit" — keeps the central value, drops the
        uncertainty (there's no dedicated uncertainty column for these
        fields)
      - a plain number with optional leading '~' and trailing unit text

    Deliberately rejects ranges ("0.03 - 0.5 nm") and inequalities
    ("< 1 nm", "> 5 nm") rather than picking a midpoint or bound — these
    are not single point measurements, and inventing a central value would
    fabricate precision the source didn't report.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()

    # Drop a trailing explanatory parenthetical.
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s).strip()

    # Strip a leading "variable = " prefix — only a short identifier
    # directly followed by '=', so a bare number is never touched.
    s = re.sub(r'^[\w\u0370-\u03FF]{1,6}\s*=\s*', '', s).strip()

    # Reject ranges and inequalities outright.
    if re.search(r'[<>]', s) or re.search(r'\d\s*-\s*\d', s):
        return None

    # value ± uncertainty unit
    m = re.match(r'^~?\s*(-?\d+\.?\d*)\s*\u00b1\s*\d+\.?\d*\s*[a-zA-Z\u00b5/\u00b2\-]*\s*$', s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None

    # plain number, optional leading '~', optional trailing unit text
    m = re.match(r'^~?\s*(-?\d+\.?\d*)\s*[a-zA-Z\u00b5/\u00b2\-]*\s*$', s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def promote_from_catchall(catchall: dict, keywords: list, require_any: list = None,
                           field_name: str = None, sample_label: str = None,
                           ambiguous_log: list = None) -> float:
    """
    Fallback promotion path for fields whose values live in the free-text
    additional_measurements catchall rather than a named extraction field.

    Added July 2026 after mean_free_path_nm, vortex_activation_temperature_K,
    and kinetic_inductance_sheet_pH_sq were found (via
    report_zero_populated_columns()) to always read None: gf() only checks
    the sample object directly, but these three were never added to
    prompts.py's AVAILABLE_FIELDS, so the real values were sitting in the
    catchall the whole time. This is a stopgap promotion, not a substitute
    for fixing AVAILABLE_FIELDS (see Phase 4 / prompts.py v5 in the
    continuity doc) — it can only find what happens to be phrased in a
    matchable way, so a real zero here after re-ingestion still means
    "check AVAILABLE_FIELDS," not "the measurement is absent."

    `keywords`: all must appear (case-insensitive substring) in the item's
    description for a match.
    `require_any`: if given, at least one must also appear in the
    description or units — used for kinetic_inductance_sheet_pH_sq, where
    a bare "kinetic inductance" match would also catch non-promotable total
    Lk values. Per schema domain rule, only the sheet (per-square) value is
    geometry-independent and promotable; total Lk is not.

    If MORE THAN ONE catchall item matches for the same sample and they
    disagree (e.g. a device with separate mean-free-path entries for its
    Au encapsulation layer and its Ta film), this returns None rather than
    silently taking whichever happened to be inserted first — first-match
    would have no principled reason to be scientifically correct, and a
    Ta sample carrying an Au mean-free-path value would poison Phase A
    per-material stratification. Pass `ambiguous_log` (a list) with
    `field_name`/`sample_label` to record the conflict for human review
    instead of just dropping it silently.

    Returns the single distinct parsed value if all matches agree, or None
    if there are zero matches, no matches parse cleanly, or matches
    disagree.
    """
    matches = []
    for item in (catchall.get("additional_measurements") or []):
        desc = (item.get("description") or "").lower()
        units = (item.get("units") or "").lower()
        if not all(k in desc for k in keywords):
            continue
        if require_any and not any(r in desc or r in units for r in require_any):
            continue
        val = _parse_clean_numeric(item.get("value"))
        if val is not None:
            matches.append((val, item.get("description")))

    if not matches:
        return None

    distinct_values = {v for v, _ in matches}
    if len(distinct_values) == 1:
        return matches[0][0]

    # Ambiguous — more than one matching item, disagreeing values.
    if ambiguous_log is not None:
        ambiguous_log.append({
            "sample": sample_label,
            "field": field_name,
            "matches": matches,
        })
    return None


def report_review_candidates(records: list) -> list:
    """
    Scan the raw JSONL records (before any filtering) for papers that were
    skipped by the relevance gate (Phase 1 skip logic in pipeline_ingest.py)
    but flagged by the classifier as reporting real device performance data
    with no material/fabrication context — e.g. Dai 2026 (T1/T2 on a real
    transmon, paper focused on drive-induced state transitions, no
    fabrication reported) and Siddhu 2025 (T1/T2 on IBM public cloud
    backend qubits, no fabrication documentation exists to report).

    Added July 2026. Motivation: an over-eager relevance gate is easy to
    notice (a wrongly-included paper shows up as a visible outlier in the
    Explorer); an over-strict one is not (a wrongly-excluded paper simply
    never appears anywhere, and nothing prompts a human to go looking for
    it). This surfaces that class of loss automatically on every rebuild,
    the same way report_zero_populated_columns() surfaces silently-broken
    columns, rather than relying on someone remembering to check.

    These are not necessarily mistakes — many are correctly excluded from
    materials-correlation evidence (that's the point of the relevance
    gate). This is a review list, not an error list: worth a human glance
    to decide case by case whether any belong in a manual "include anyway"
    allowlist (the mirror image of exclusions.json).

    Returns the list of matching records for the caller to print/report.
    """
    candidates = []
    for rec in records:
        if rec.get("outcome") != "skipped":
            continue
        relevance_json = rec.get("relevance_json") or {}
        if relevance_json.get("device_performance_without_material_context"):
            candidates.append(rec)
    return candidates


def report_zero_populated_columns(cur, table: str, exclude: set = None) -> list:
    """
    For every column declared in `table`, count how many rows have a
    non-null value. Returns the list of columns where that count is zero —
    i.e. columns that exist in the schema but are not actually receiving
    data anywhere in the current build.

    Added July 2026 after three separate instances of the same failure
    shape, each found independently and well after the column had shipped:
    junction_present (column existed, insert never populated it),
    fabrication_detail catchall items (extracted correctly, no insert
    block to store them), and mean_free_path_nm / vortex_activation_
    temperature_K / kinetic_inductance_sheet_pH_sq (columns read directly
    off the sample object via gf(), but the values actually live in the
    additional_measurements catchall — so gf() always found nothing).

    This is a detector, not a fix — a zero-populated column here means
    "check why," not "the measurement is simply rare." A rare-but-real
    field will show a small nonzero count; only a genuinely disconnected
    column shows zero across the whole corpus.
    """
    cur.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cur.fetchall()]
    zero_populated = []
    for col in columns:
        if exclude and col in exclude:
            continue
        cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NOT NULL')
        if cur.fetchone()[0] == 0:
            zero_populated.append(col)
    return zero_populated


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
        DROP TABLE IF EXISTS fabrication_groups;

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
            extraction_json     TEXT,

            -- Version lineage stamps (Phase 4 item #5, Aug 2026). NULL for
            -- any record ingested before this feature existed.
            schema_version            TEXT,
            extraction_prompt_version TEXT,
            model_identifier          TEXT,
            ingestion_batch_id        TEXT,
            source_pdf_sha256         TEXT
        );

        CREATE TABLE samples (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id                INTEGER REFERENCES papers(id),
            filename                TEXT,
            sample_id               TEXT,
            display_name            TEXT,

            -- Fabrication linkage (Aug 12 2026) — plain reference, no
            -- confidence/source wrapper. References group_id in the
            -- fabrication_groups table for the same paper_id. Absent means
            -- no fabrication-origin evidence exists for this sample; mining
            -- treats an absent group as a singleton (independent).
            fabrication_group_id    TEXT,

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
            junction_present        INTEGER,
            junction_material               TEXT,
            junction_fabrication_method     TEXT,
            junction_area_um2               TEXT,
            junction_resistance_normal_Ohm  TEXT,

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
            T2_unspecified_us       TEXT,
            gate_1q_fidelity_pct    TEXT,
            gate_2q_fidelity_pct    TEXT,

            -- Measurement context (added July 2026) — these already exist
            -- correctly in sample_json per schema Blocks 3.2-3.4, but had
            -- no named column, so a SQL-only query couldn't tell qubit-state
            -- T1 from resonator-photon-lifetime T1, or see what frequency/
            -- temperature/power a Qi or loss tangent value was measured at.
            T1_measurement_context             TEXT,
            Qi_measurement_frequency_GHz        TEXT,
            Qi_measurement_temperature_mK       TEXT,
            Qi_measurement_power_dBm            TEXT,
            loss_tangent_substrate_frequency_GHz    TEXT,
            loss_tangent_substrate_temperature_mK   TEXT,
            loss_tangent_interface_type             TEXT,

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

            -- Qi_single_photon had no confidence column at all until now,
            -- despite Qi_confidence existing since the original four (that
            -- one tracks Qi_internal, not Qi_single_photon) — added Aug 12 2026.
            Qi_single_photon_confidence TEXT,

            -- Confidence flags (added May 2026)
            tan_delta_confidence        TEXT,
            T2_echo_confidence          TEXT,
            T2_ramsey_confidence        TEXT,
            T2_unspecified_confidence   TEXT,
            surface_oxide_confidence    TEXT,
            film_thickness_confidence   TEXT,
            junction_present_confidence TEXT,
            junction_material_confidence              TEXT,
            junction_fabrication_method_confidence     TEXT,
            junction_area_um2_confidence               TEXT,
            junction_resistance_normal_Ohm_confidence  TEXT,
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
            -- derived_T2_us: best available T2. Echo preferred; falls back to
            -- Ramsey, then unspecified (per explicit user preference — these
            -- values stay visible in the Explorer visualizer rather than
            -- silently dropping out of "best available T2", added Aug 12 2026).
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

        CREATE TABLE fabrication_groups (
            id                               INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id                         INTEGER REFERENCES papers(id),
            filename                         TEXT,
            group_id                         TEXT,   -- paper-local id, e.g. "fab1"
            raw_label                        TEXT,
            member_sample_ids                TEXT,   -- JSON array of sample_id strings
            excluded_candidates              TEXT,   -- JSON array of {sample_id, reason}
            individual_assignment_disclosed  INTEGER, -- 0/1/NULL, normalize_bool_field()
            basis                            TEXT,   -- explicit | implicit_inferred
            evidence                         TEXT,
            confidence                       TEXT,   -- high | medium | low
            source                           TEXT
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
    fabrication_groups_inserted = 0
    ambiguous_catchall_promotions = []
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
                human_reviewed, human_approved, num_samples, error, extraction_json,
                schema_version, extraction_prompt_version, model_identifier,
                ingestion_batch_id, source_pdf_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.get("filename"),
            rec.get("processed_at"),
            outcome,
            rec.get("relevance") or ext.get("relevance"),
            rec.get("relevance_reason"),
            rec.get("paper_type") or ext.get("paper_type"),
            rec.get("doi") or ext.get("doi"),
            rec.get("arxiv_id") or ext.get("arxiv_id")
                or derive_arxiv_id_from_doi(rec.get("doi") or ext.get("doi")),
            rec.get("title") or ext.get("title"),
            authors,
            rec.get("journal") or ext.get("journal_or_preprint"),
            1 if rec.get("human_reviewed") else 0,
            1 if rec.get("human_approved") else 0,
            num_samples,
            error_str,
            json.dumps(ext) if ext else None,
            rec.get("schema_version"),
            rec.get("extraction_prompt_version"),
            rec.get("model_identifier"),
            rec.get("ingestion_batch_id"),
            rec.get("source_pdf_sha256"),
        ))
        paper_id = cur.lastrowid
        papers_inserted += 1

        # Fabrication groups — paper-level, inserted once per paper (Aug 12 2026)
        for grp in ext.get("fabrication_groups", []) or []:
            cur.execute("""
                INSERT INTO fabrication_groups (
                    paper_id, filename, group_id, raw_label,
                    member_sample_ids, excluded_candidates,
                    individual_assignment_disclosed, basis, evidence,
                    confidence, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                paper_id,
                rec.get("filename"),
                grp.get("group_id"),
                grp.get("raw_label"),
                json.dumps(grp.get("member_sample_ids") or []),
                json.dumps(grp.get("excluded_candidates") or []),
                normalize_bool_field(grp.get("individual_assignment_disclosed")),
                grp.get("basis"),
                grp.get("evidence"),
                grp.get("confidence"),
                grp.get("source"),
            ))
            fabrication_groups_inserted += 1

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

            # derived_T2_us — echo preferred; falls back to Ramsey, then unspecified
            derived_T2_us = gf("T2_echo_us")[0] or gf("T2_ramsey_us")[0] or gf("T2_unspecified_us")[0]

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

            # Catchall-promoted fields (added July 2026 — see promote_from_catchall
            # docstring). Extraction-first: if these ever become real named
            # AVAILABLE_FIELDS in prompts.py, that value wins automatically;
            # until then, fall back to a keyword match against the catchall.
            _catchall_for_promotion = sample.get("catchall", {}) or {}
            mean_free_path_promoted = gf("mean_free_path_nm")[0] or promote_from_catchall(
                _catchall_for_promotion, ["mean free path"],
                field_name="mean_free_path_nm", sample_label=display_name,
                ambiguous_log=ambiguous_catchall_promotions,
            )
            vortex_activation_promoted = gf("vortex_activation_temperature_K")[0] or promote_from_catchall(
                _catchall_for_promotion, ["vortex activation"],
                field_name="vortex_activation_temperature_K", sample_label=display_name,
                ambiguous_log=ambiguous_catchall_promotions,
            )
            kinetic_inductance_promoted = gf("kinetic_inductance_sheet_pH_sq")[0] or promote_from_catchall(
                _catchall_for_promotion, ["kinetic inductance"],
                require_any=["sheet", "per square", "per-square", "ph/sq"],
                field_name="kinetic_inductance_sheet_pH_sq", sample_label=display_name,
                ambiguous_log=ambiguous_catchall_promotions,
            )

            # Similarity profile
            profile = similarity_profiles.get(sid, {})
            if profile:
                profiles_found += 1

            cur.execute("""
                INSERT INTO samples (
                    paper_id, filename, sample_id, display_name,
                    fabrication_group_id,
                    substrate_material, substrate_orientation,
                    film_material, film_crystal_phase, film_thickness_nm,
                    deposition_method, deposition_temperature_C,
                    annealing_temperature_C, annealing_duration_s,
                    junction_present,
                    junction_material,
                    junction_fabrication_method,
                    junction_area_um2,
                    junction_resistance_normal_Ohm,
                    Tc_K, RRR, sheet_resistance_Ohm_sq,
                    loss_tangent_substrate, loss_tangent_interface,
                    tan_delta_effective_surface,
                    TLS_density, Qi_internal, Qi_single_photon,
                    surface_oxide_nm, T1_us, T2_echo_us, T2_ramsey_us, T2_unspecified_us,
                    gate_1q_fidelity_pct, gate_2q_fidelity_pct,
                    T1_measurement_context,
                    Qi_measurement_frequency_GHz,
                    Qi_measurement_temperature_mK,
                    Qi_measurement_power_dBm,
                    loss_tangent_substrate_frequency_GHz,
                    loss_tangent_substrate_temperature_mK,
                    loss_tangent_interface_type,
                    normal_state_resistance_Ohm,
                    room_temperature_resistance_Ohm,
                    measured_structure_width_um,
                    measured_structure_length_um,
                    Tc_confidence, RRR_confidence,
                    Qi_confidence, T1_confidence,
                    Qi_single_photon_confidence,
                    tan_delta_confidence, T2_echo_confidence,
                    T2_ramsey_confidence, T2_unspecified_confidence,
                    surface_oxide_confidence, film_thickness_confidence,
                    junction_present_confidence,
                    junction_material_confidence,
                    junction_fabrication_method_confidence,
                    junction_area_um2_confidence,
                    junction_resistance_normal_Ohm_confidence,
                    resonator_gap_width_confidence,
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
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?
                )
            """, (
                paper_id, rec.get("filename"), sid, display_name,
                gf("fabrication_group_id")[0],
                gf("substrate_material")[0],
                gf("substrate_orientation")[0],
                gf("film_material")[0],
                gf("film_crystal_phase")[0],
                gf("film_thickness_nm")[0],
                gf("deposition_method")[0],
                gf("deposition_temperature_C")[0],
                gf("annealing_temperature_C")[0],
                gf("annealing_duration_s")[0],
                normalize_junction_present(gf("junction_present")[0]),
                gf("junction_material")[0],
                gf("junction_fabrication_method")[0],
                gf("junction_area_um2")[0],
                gf("junction_resistance_normal_Ohm")[0],
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
                gf("T2_unspecified_us")[0],
                gf("single_qubit_gate_fidelity_pct")[0],
                gf("two_qubit_gate_fidelity_pct")[0],
                gf("T1_measurement_context")[0],
                gf("Qi_measurement_frequency_GHz")[0],
                gf("Qi_measurement_temperature_mK")[0],
                gf("Qi_measurement_power_dBm")[0],
                gf("loss_tangent_substrate_frequency_GHz")[0],
                gf("loss_tangent_substrate_temperature_mK")[0],
                gf("loss_tangent_interface_type")[0],
                gf("normal_state_resistance_Ohm")[0],
                gf("room_temperature_resistance_Ohm")[0],
                gf("measured_structure_width_um")[0],
                gf("measured_structure_length_um")[0],
                # Original four confidence columns
                gf("Tc_K")[1],
                gf("RRR")[1],
                gf("Qi_internal_quality_factor")[1],
                gf("T1_us")[1],
                gf("Qi_single_photon")[1],
                # Six confidence columns (May 2026) + T2_ramsey/T2_unspecified (Aug 12 2026)
                gf("tan_delta_effective_surface")[1],
                gf("T2_echo_us")[1],
                gf("T2_ramsey_us")[1],
                gf("T2_unspecified_us")[1],
                gf("surface_oxide_thickness_nm")[1],
                gf("film_thickness_nm")[1],
                gf("junction_present")[1],
                gf("junction_material")[1],
                gf("junction_fabrication_method")[1],
                gf("junction_area_um2")[1],
                gf("junction_resistance_normal_Ohm")[1],
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
                mean_free_path_promoted,
                vortex_activation_promoted,
                kinetic_inductance_promoted,
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

    # --- Zero-populated column report (catches "declared but never wired up" bugs) ---
    zero_populated_samples = report_zero_populated_columns(
        cur, "samples",
        exclude={"id", "sample_json"},  # always present by construction, not informative
    )
    zero_populated_papers = report_zero_populated_columns(
        cur, "papers",
        exclude={"id"},
    )

    conn.commit()
    conn.close()

    # --- Summary ---
    print(f"Done.")
    print(f"  Papers inserted  : {papers_inserted}")
    print(f"  Samples inserted : {samples_inserted}")
    print(f"  Catchall items   : {catchall_inserted}")
    print(f"  Fabrication groups: {fabrication_groups_inserted}")
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

    if zero_populated_samples or zero_populated_papers:
        print(f"\n  ⚠ Zero-populated columns (declared in schema, no data in any row):")
        print(f"    This usually means the column is reading from the wrong source")
        print(f"    or was never wired into an insert — not that the measurement")
        print(f"    is simply rare. Worth checking each one individually.")
        if zero_populated_samples:
            print(f"    samples table ({len(zero_populated_samples)}): {', '.join(zero_populated_samples)}")
        if zero_populated_papers:
            print(f"    papers table  ({len(zero_populated_papers)}): {', '.join(zero_populated_papers)}")
    else:
        print(f"\n  ✓ No zero-populated columns in samples or papers")

    if ambiguous_catchall_promotions:
        print(f"\n  ⚠ Ambiguous catchall promotions ({len(ambiguous_catchall_promotions)}) — left NULL, needs review:")
        print(f"    More than one matching catchall item with disagreeing values.")
        print(f"    Usually means the sample has this measurement for more than")
        print(f"    one material/component (e.g. an encapsulation layer and the")
        print(f"    film beneath it) — check which value is the physically")
        print(f"    relevant one for this sample before trusting either.")
        for case in ambiguous_catchall_promotions:
            print(f"    {case['sample']} — {case['field']}:")
            for val, desc in case["matches"]:
                print(f"      {val:<10} <- \"{desc}\"")
    else:
        print(f"\n  ✓ No ambiguous catchall promotions")

    review_candidates = report_review_candidates(records)
    if review_candidates:
        print(f"\n  ℹ Skipped papers flagged for review ({len(review_candidates)}) — "
              f"real device data, no material context, not automatically included:")
        print(f"    These were correctly excluded by the relevance gate (no material or")
        print(f"    fabrication story to attach the device data to) but may be worth a")
        print(f"    manual look — e.g. as candidates for an 'include anyway' allowlist.")
        for rec in review_candidates:
            title = (rec.get("title") or rec.get("relevance_json", {}).get("title") or "")
            reason = (rec.get("relevance_reason") or "")
            print(f"    {rec.get('filename')} — {title[:60]}")
            print(f"      {reason[:150]}")
    else:
        print(f"\n  ✓ No skipped papers flagged for review")

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
