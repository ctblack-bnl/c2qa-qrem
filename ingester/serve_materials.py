#!/usr/bin/env python3
# ingester/serve_materials.py
# Local development server for the C2QA Materials Pipeline UI.
# Serves static files and provides a JSON API over the SQLite database.
#
# Usage:
#   cd ingester
#   python3 serve_materials.py
#   # Materials Explorer: http://localhost:8001/materials_explorer.html
#   # Ingestion Pipeline: http://localhost:8001/ingest_pipeline.html
#
# API routes:
#   GET  /api/samples          — all samples with key measurement fields
#   GET  /api/fields           — available numeric fields (only those with data)
#   GET  /api/catchall         — catchall items
#   GET  /api/coverage         — coverage summary
#   POST /api/ingest/start     — start ingestion run
#   GET  /api/ingest/status    — poll ingestion progress
#   GET  /api/duplicates       — potential duplicate pairs
#   POST /api/duplicates/decide — record a duplicate decision
#   POST /api/build            — run build_sqlite

import http.server
import json
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from difflib import SequenceMatcher

PORT      = 8001
REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH   = REPO_ROOT / "data" / "ingested" / "records.db"
JSONL_PATH = REPO_ROOT / "data" / "ingested" / "records.jsonl"
DEDUP_PATH = REPO_ROOT / "data" / "ingested" / "deduplication.json"
SERVE_DIR = Path(__file__).resolve().parent

# All numeric fields the Explorer knows about — in display order.
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
    # Derived quantities
    ('derived_resistivity_uOhm_cm',      'Resistivity derived (µΩ·cm)'),
    ('derived_RRR_from_RvT',             'RRR derived from R vs T'),
    ('derived_sheet_resistance_Ohm_sq',  'Sheet resistance derived (Ω/□)'),
    ('derived_BCS_gap_meV',              'BCS gap derived (meV)'),
    ('derived_coherence_length_nm',      'Coherence length derived (nm)'),
    ('derived_kinetic_inductance_pH_sq', 'Kinetic inductance derived (pH/□)'),
]

# ── Ingestion state (shared between threads) ──────────────────────────────
_ingest_state = {
    "running":   False,
    "done":      False,
    "progress":  [],       # list of status messages
    "total":     0,
    "processed": 0,
    "success":   0,
    "failed":    0,
    "skipped":   0,
    "current":   None,
}
_ingest_lock = threading.Lock()


def _run_ingestion(papers_dir: str):
    """Run pipeline_ingest.py in a subprocess, capturing output line by line."""
    global _ingest_state
    with _ingest_lock:
        _ingest_state["running"]   = True
        _ingest_state["done"]      = False
        _ingest_state["progress"]  = []
        _ingest_state["success"]   = 0
        _ingest_state["failed"]    = 0
        _ingest_state["skipped"]   = 0
        _ingest_state["current"]   = None

    script = SERVE_DIR / "pipeline_ingest.py"
    cmd = ["python3", str(script), "--papers-dir", papers_dir]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(SERVE_DIR),
        )
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            with _ingest_lock:
                _ingest_state["progress"].append(line)
                # Parse key lines for structured status
                if line.startswith("[") and "/" in line[:10]:
                    _ingest_state["current"] = line
                if "Done [OK]" in line:
                    _ingest_state["success"] += 1
                elif "Done [FAILED" in line:
                    _ingest_state["failed"] += 1
                elif "Skipping" in line:
                    _ingest_state["skipped"] += 1
        proc.wait()
    except Exception as e:
        with _ingest_lock:
            _ingest_state["progress"].append(f"ERROR: {e}")

    with _ingest_lock:
        _ingest_state["running"] = False
        _ingest_state["done"]    = True


# ── Duplicate detection ───────────────────────────────────────────────────

def title_similarity(a: str, b: str) -> float:
    """Return similarity ratio between two titles (0-1)."""
    if not a or not b:
        return 0.0
    a = a.lower().strip()
    b = b.lower().strip()
    return SequenceMatcher(None, a, b).ratio()


def find_duplicate_pairs(threshold: float = 0.85) -> list:
    """
    Find pairs of ingested papers with similar titles.
    Returns list of (paper_a, paper_b, similarity) dicts.
    Only returns pairs not yet decided in deduplication.json.
    """
    if not JSONL_PATH.exists():
        return []

    # Load all ingested records
    records = []
    with open(JSONL_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("outcome") == "ingested":
                    records.append({
                        "filename": rec.get("filename"),
                        "title":    rec.get("title") or "",
                        "authors":  rec.get("authors") or "",
                        "journal":  rec.get("journal") or "",
                        "doi":      rec.get("doi"),
                        "num_samples": len((rec.get("extraction_json") or {}).get("samples", [])),
                    })
            except json.JSONDecodeError:
                pass

    # Load existing decisions
    decided_pairs = set()
    if DEDUP_PATH.exists():
        try:
            dedup = json.loads(DEDUP_PATH.read_text())
            for d in dedup.get("decisions", []):
                key = tuple(sorted([d["paper_a"], d["paper_b"]]))
                decided_pairs.add(key)
        except Exception:
            pass

    # Find similar pairs
    pairs = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            a = records[i]
            b = records[j]
            key = tuple(sorted([a["filename"], b["filename"]]))
            if key in decided_pairs:
                continue
            sim = title_similarity(a["title"], b["title"])
            if sim >= threshold:
                pairs.append({
                    "paper_a":    a,
                    "paper_b":    b,
                    "similarity": round(sim, 3),
                })

    pairs.sort(key=lambda x: -x["similarity"])
    return pairs


def load_dedup() -> dict:
    if DEDUP_PATH.exists():
        try:
            return json.loads(DEDUP_PATH.read_text())
        except Exception:
            pass
    return {"decisions": []}


def save_dedup(dedup: dict):
    DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEDUP_PATH.write_text(json.dumps(dedup, indent=2))


# ── Database functions ────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_available_fields():
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
                available.append({'field': field, 'label': label, 'count': count})
        except Exception:
            pass
    conn.close()
    return available


def fetch_samples():
    conn = get_db()
    cur = conn.cursor()
    numeric_cols = ', '.join(f's.{f}' for f, _ in ALL_NUMERIC_FIELDS)
    cur.execute(f"""
        SELECT
            s.display_name, s.sample_id, s.filename,
            s.film_material, s.film_crystal_phase,
            s.substrate_material, s.deposition_method,
            s.Tc_confidence, s.RRR_confidence,
            s.Qi_confidence, s.T1_confidence,
            p.authors, p.title, p.doi, p.journal,
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
    conn = get_db()
    cur = conn.cursor()
    if item_type:
        cur.execute("""
            SELECT c.display_name, c.item_type, c.description,
                   c.value, c.source, c.notes, p.authors, p.title
            FROM catchall_items c
            JOIN papers p ON c.paper_id = p.id
            WHERE c.item_type = ?
            ORDER BY c.display_name
        """, (item_type,))
    else:
        cur.execute("""
            SELECT c.display_name, c.item_type, c.description,
                   c.value, c.source, c.notes, p.authors, p.title
            FROM catchall_items c
            JOIN papers p ON c.paper_id = p.id
            ORDER BY c.item_type, c.display_name
        """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_coverage():
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


# ── HTTP Handler ──────────────────────────────────────────────────────────

class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/samples":
            self._json(200, {"ok": True, "samples": fetch_samples()})
        elif self.path == "/api/fields":
            self._json(200, {"ok": True, "fields": fetch_available_fields()})
        elif self.path.startswith("/api/catchall"):
            item_type = None
            if "?" in self.path:
                for part in self.path.split("?", 1)[1].split("&"):
                    if part.startswith("type="):
                        item_type = part[5:]
            self._json(200, {"ok": True, "items": fetch_catchall(item_type)})
        elif self.path == "/api/coverage":
            self._json(200, {"ok": True, "coverage": fetch_coverage()})
        elif self.path == "/api/ingest/status":
            with _ingest_lock:
                state = dict(_ingest_state)
            self._json(200, {"ok": True, "state": state})
        elif self.path == "/api/duplicates":
            pairs = find_duplicate_pairs()
            self._json(200, {"ok": True, "pairs": pairs, "count": len(pairs)})
        else:
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/ingest/start":
            with _ingest_lock:
                if _ingest_state["running"]:
                    self._json(400, {"ok": False, "error": "Already running"})
                    return
            papers_dir = body.get("papers_dir", str(REPO_ROOT / "data" / "papers"))
            t = threading.Thread(target=_run_ingestion, args=(papers_dir,), daemon=True)
            t.start()
            self._json(200, {"ok": True, "message": "Ingestion started"})

        elif self.path == "/api/duplicates/decide":
            paper_a  = body.get("paper_a")
            paper_b  = body.get("paper_b")
            decision = body.get("decision")  # "duplicate" or "not_duplicate"
            keep     = body.get("keep")      # filename to keep (if duplicate)
            try:
                dedup = load_dedup()
                dedup["decisions"].append({
                    "paper_a":    paper_a,
                    "paper_b":    paper_b,
                    "decision":   decision,
                    "keep":       keep,
                    "decided_at": time.strftime("%Y-%m-%d"),
                })
                save_dedup(dedup)
                self._json(200, {"ok": True})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})

        elif self.path == "/api/build":
            try:
                script = SERVE_DIR / "build_sqlite.py"
                result = subprocess.run(
                    ["python3", str(script)],
                    capture_output=True, text=True,
                    cwd=str(SERVE_DIR)
                )
                success = result.returncode == 0
                self._json(200, {
                    "ok": success,
                    "output": result.stdout + result.stderr
                })
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})

        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if args and (str(args[0]).startswith(("POST", "GET /api")) or
                     str(args[1]) not in ("200", "304")):
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"C2QA Materials Pipeline — Local Server")
    print(f"")
    print(f"  Materials Explorer:  http://localhost:{PORT}/materials_explorer.html")
    print(f"  Ingestion Pipeline:  http://localhost:{PORT}/ingest_pipeline.html")
    print(f"")
    print(f"Press Ctrl+C to stop.")
    print(f"")

    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
