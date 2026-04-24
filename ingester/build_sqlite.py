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
# Usage:
#   cd ingester
#   python3 build_sqlite.py
#   # Then open data/ingested/records.db in any SQLite browser

import json
import re
import sqlite3
import argparse
from pathlib import Path


def make_display_name(authors: str, sample_id: str) -> str:
    """
    Build a human-readable display name for a sample.
    Format: {first_author_lastname}_{year}_{sample_id}
    Example: "Bahrami_2026_D1", "Yang_2026_Ta-Hf_1ks_750C"

    Authors string is typically "First Author et al., YYYY" or similar.
    We extract the first word (lastname) and the 4-digit year.
    """
    if not authors:
        first_author = "Unknown"
        year = "????"
    else:
        # Extract first word as lastname
        first_author = authors.strip().split()[0].rstrip(",")

        # Extract 4-digit year
        year_match = re.search(r'\b(20\d{2})\b', authors)
        year = year_match.group(1) if year_match else "????"

    # Clean sample_id for use in a display name
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
            title               TEXT,
            authors             TEXT,
            journal             TEXT,
            human_reviewed      INTEGER DEFAULT 0,
            human_approved      INTEGER DEFAULT 0,
            num_samples         INTEGER DEFAULT 0,
            error               TEXT,
            extraction_json     TEXT    -- full JSON for reference
        );

        CREATE TABLE samples (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id                INTEGER REFERENCES papers(id),
            filename                TEXT,
            sample_id               TEXT,
            display_name            TEXT,   -- e.g. Bahrami_2026_D1

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
            TLS_density             TEXT,
            Qi_internal             TEXT,
            Qi_single_photon        TEXT,
            surface_oxide_nm        TEXT,
            T1_us                   TEXT,
            T2_echo_us              TEXT,
            gate_1q_fidelity_pct    TEXT,
            gate_2q_fidelity_pct    TEXT,

            -- Confidence flags (high/medium/low for key fields)
            Tc_confidence           TEXT,
            RRR_confidence          TEXT,
            Qi_confidence           TEXT,
            T1_confidence           TEXT,

            -- Full sample JSON for reference
            sample_json             TEXT
        );

        CREATE TABLE catchall_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id        INTEGER REFERENCES papers(id),
            filename        TEXT,
            sample_id       TEXT,
            display_name    TEXT,   -- matches samples.display_name for easy joining
            item_type       TEXT,   -- additional_measurement, anomalous_observation, correlation, schema_candidate
            description     TEXT,
            value           TEXT,
            source          TEXT,
            notes           TEXT    -- suspected_relevance, hypothesis, nature, etc.
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

    for rec in records:
        ext = rec.get("extraction_json") or {}
        outcome = rec.get("outcome", "unknown")
        error = rec.get("error")
        error_str = json.dumps(error) if error else None

        samples = ext.get("samples", [])
        num_samples = len(samples)

        # Get authors for display_name construction
        authors = rec.get("authors") or ext.get("authors") or ""

        # Insert paper row
        cur.execute("""
            INSERT INTO papers (
                filename, processed_at, outcome, relevance, relevance_reason,
                paper_type, doi, title, authors, journal,
                human_reviewed, human_approved, num_samples, error, extraction_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.get("filename"),
            rec.get("processed_at"),
            outcome,
            rec.get("relevance") or ext.get("relevance"),
            rec.get("relevance_reason"),
            rec.get("paper_type") or ext.get("paper_type"),
            rec.get("doi") or ext.get("doi"),
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

        # Insert sample rows
        for sample in samples:
            sid = sample.get("sample_id", "unknown")
            display_name = make_display_name(authors, sid)

            def gf(field):
                return get_field(sample, field)

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
                    TLS_density, Qi_internal, Qi_single_photon,
                    surface_oxide_nm, T1_us, T2_echo_us,
                    gate_1q_fidelity_pct, gate_2q_fidelity_pct,
                    Tc_confidence, RRR_confidence,
                    Qi_confidence, T1_confidence,
                    sample_json
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
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
                gf("TLS_density_per_GHz_per_um2")[0],
                gf("Qi_internal_quality_factor")[0],
                gf("Qi_single_photon")[0],
                gf("surface_oxide_thickness_nm")[0],
                gf("T1_us")[0],
                gf("T2_echo_us")[0],
                gf("single_qubit_gate_fidelity_pct")[0],
                gf("two_qubit_gate_fidelity_pct")[0],
                gf("Tc_K")[1],
                gf("RRR")[1],
                gf("Qi_internal_quality_factor")[1],
                gf("T1_us")[1],
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

    conn.commit()
    conn.close()

    print(f"Done.")
    print(f"  Papers inserted  : {papers_inserted}")
    print(f"  Samples inserted : {samples_inserted}")
    print(f"  Catchall items   : {catchall_inserted}")
    print(f"  Database written : {db_path}")
    print()
    print("To browse: open records.db in DB Browser for SQLite (sqlitebrowser.org)")
    print()
    print("Useful queries:")
    print("  SELECT display_name, film_material, Tc_K, RRR, Qi_internal FROM samples;")
    print("  SELECT display_name, item_type, description FROM catchall_items LIMIT 20;")
    print("  SELECT outcome, COUNT(*) FROM papers GROUP BY outcome;")


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
