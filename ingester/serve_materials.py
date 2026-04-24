#!/usr/bin/env python3
# ingester/serve_materials.py
# Local development server for the Materials Explorer UI.
# Serves static files and provides a JSON API over the SQLite database.
#
# Usage:
#   cd ingester
#   python3 serve_materials.py
#   # Open http://localhost:8001/materials_explorer.html
#
# API routes:
#   GET  /api/samples     — all samples with key measurement fields
#   GET  /api/fields      — available numeric fields (only those with data)
#   GET  /api/catchall    — catchall items (correlations, schema candidates, etc.)
#   GET  /api/coverage    — coverage summary

import http.server
import json
import sqlite3
from pathlib import Path

PORT = 8001
REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH   = REPO_ROOT / "data" / "ingested" / "records.db"
SERVE_DIR = Path(__file__).resolve().parent


# All numeric fields the Explorer knows about — in display order.
# Add new schema fields here as they are added to the SQLite schema.
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

    # Derived quantities
    ('derived_resistivity_uOhm_cm',      'Resistivity derived (µΩ·cm)'),
    ('derived_BCS_gap_meV',              'BCS gap derived (meV)'),
    ('derived_coherence_length_nm',      'Coherence length derived (nm)'),
    ('derived_kinetic_inductance_pH_sq', 'Kinetic inductance derived (pH/□)'),
]


def get_db():
    """Open a read-only connection to the SQLite database."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_available_fields():
    """
    Return only the numeric fields that have at least one non-null value
    in the current corpus. Fields with no data are excluded from dropdowns.
    Also returns the count of samples that have each field, for context.
    """
    conn = get_db()
    cur = conn.cursor()
    available = []
    for field, label in ALL_NUMERIC_FIELDS:
        try:
            cur.execute(
                f"SELECT COUNT(*) FROM samples s "
                f"JOIN papers p ON s.paper_id = p.id "
                f"WHERE p.outcome = 'ingested' AND s.{field} IS NOT NULL"
            )
            count = cur.fetchone()[0]
            if count > 0:
                available.append({
                    'field': field,
                    'label': label,
                    'count': count,
                })
        except Exception:
            pass  # field may not exist in older schema versions
    conn.close()
    return available


def fetch_samples():
    """
    Return all samples with all known numeric fields for plotting.
    Converts TEXT fields to floats where possible.
    """
    conn = get_db()
    cur = conn.cursor()

    # Build the SELECT list dynamically from ALL_NUMERIC_FIELDS
    numeric_cols = ', '.join(f's.{f}' for f, _ in ALL_NUMERIC_FIELDS)

    cur.execute(f"""
        SELECT
            s.display_name,
            s.sample_id,
            s.filename,
            s.film_material,
            s.film_crystal_phase,
            s.substrate_material,
            s.deposition_method,
            s.Tc_confidence,
            s.RRR_confidence,
            s.Qi_confidence,
            s.T1_confidence,
            p.authors,
            p.title,
            p.doi,
            p.journal,
            {numeric_cols}
        FROM samples s
        JOIN papers p ON s.paper_id = p.id
        WHERE p.outcome = 'ingested'
        ORDER BY s.film_material, s.display_name
    """)
    rows = cur.fetchall()
    conn.close()

    numeric_field_names = [f for f, _ in ALL_NUMERIC_FIELDS]
    samples = []
    for row in rows:
        d = dict(row)
        for field in numeric_field_names:
            val = d.get(field)
            if val is not None:
                try:
                    d[field] = float(val)
                except (ValueError, TypeError):
                    d[field] = None
        samples.append(d)

    return samples


def fetch_catchall(item_type=None):
    """Return catchall items, optionally filtered by type."""
    conn = get_db()
    cur = conn.cursor()
    if item_type:
        cur.execute("""
            SELECT c.display_name, c.item_type, c.description,
                   c.value, c.source, c.notes,
                   p.authors, p.title
            FROM catchall_items c
            JOIN papers p ON c.paper_id = p.id
            WHERE c.item_type = ?
            ORDER BY c.display_name
        """, (item_type,))
    else:
        cur.execute("""
            SELECT c.display_name, c.item_type, c.description,
                   c.value, c.source, c.notes,
                   p.authors, p.title
            FROM catchall_items c
            JOIN papers p ON c.paper_id = p.id
            ORDER BY c.item_type, c.display_name
        """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_coverage():
    """Return coverage summary — how many samples have each key field."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) as total_samples,
            SUM(CASE WHEN Tc_K IS NOT NULL THEN 1 ELSE 0 END) as has_Tc,
            SUM(CASE WHEN RRR IS NOT NULL THEN 1 ELSE 0 END) as has_RRR,
            SUM(CASE WHEN Qi_internal IS NOT NULL THEN 1 ELSE 0 END) as has_Qi,
            SUM(CASE WHEN T1_us IS NOT NULL THEN 1 ELSE 0 END) as has_T1,
            SUM(CASE WHEN T2_echo_us IS NOT NULL THEN 1 ELSE 0 END) as has_T2,
            SUM(CASE WHEN gate_2q_fidelity_pct IS NOT NULL THEN 1 ELSE 0 END) as has_2q_fidelity
        FROM samples s
        JOIN papers p ON s.paper_id = p.id
        WHERE p.outcome = 'ingested'
    """)
    row = cur.fetchone()
    conn.close()
    return dict(row)


class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/samples":
            self._handle_samples()
        elif self.path == "/api/fields":
            self._handle_fields()
        elif self.path == "/api/catchall" or self.path.startswith("/api/catchall?"):
            item_type = None
            if "?" in self.path:
                qs = self.path.split("?", 1)[1]
                for part in qs.split("&"):
                    if part.startswith("type="):
                        item_type = part[5:]
            self._handle_catchall(item_type)
        elif self.path == "/api/coverage":
            self._handle_coverage()
        else:
            super().do_GET()

    def _handle_samples(self):
        try:
            data = fetch_samples()
            self._send_json(200, {"ok": True, "samples": data, "count": len(data)})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})

    def _handle_fields(self):
        try:
            data = fetch_available_fields()
            self._send_json(200, {"ok": True, "fields": data, "count": len(data)})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})

    def _handle_catchall(self, item_type=None):
        try:
            data = fetch_catchall(item_type)
            self._send_json(200, {"ok": True, "items": data, "count": len(data)})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})

    def _handle_coverage(self):
        try:
            data = fetch_coverage()
            self._send_json(200, {"ok": True, "coverage": data})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})

    def _send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        if args and (str(args[0]).startswith("GET /api") or
                     str(args[1]) not in ("200", "304")):
            super().log_message(format, *args)


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print(f"Run 'python3 build_sqlite.py' first.")
        raise SystemExit(1)

    print(f"C2QA Materials Explorer — Local Server")
    print(f"Database: {DB_PATH}")
    print(f"")
    print(f"  Materials Explorer: http://localhost:{PORT}/materials_explorer.html")
    print(f"")
    print(f"  API endpoints:")
    print(f"    GET /api/samples    — all samples with measurements")
    print(f"    GET /api/fields     — available fields (only those with data)")
    print(f"    GET /api/catchall   — all catchall items")
    print(f"    GET /api/coverage   — coverage summary")
    print(f"")
    print(f"Press Ctrl+C to stop.")
    print(f"")

    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
