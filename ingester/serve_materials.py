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
#   GET  /api/samples                  — all samples with key measurement fields
#   GET  /api/fields                   — available numeric fields (only those with data)
#   GET  /api/catchall                 — catchall items
#   GET  /api/coverage                 — coverage summary
#   GET  /api/sample/{display_name}    — full detail for one sample
#   GET  /api/similar                  — similarity search (see below)
#   GET  /api/generate_profile         — generate QREM qubit profile YAML
#   POST /api/ingest/start             — start ingestion run
#   GET  /api/ingest/status            — poll ingestion progress
#   GET  /api/duplicates               — potential duplicate pairs
#   POST /api/duplicates/decide        — record a duplicate decision
#   POST /api/build                    — run build_sqlite
#
# /api/similar params:
#   display_name  — query sample (required)
#   n             — number of results to return (default 10)
#   same_pub      — include samples from the same publication (default false)
import http.server
import json
import math
import sqlite3
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from difflib import SequenceMatcher
from generate_qubit_profile import generate_profile, save_profile, fetch_sample_from_db
import os

PORT = int(os.environ.get('PORT', 8001))
REPO_ROOT    = Path(__file__).resolve().parent.parent
DB_PATH      = REPO_ROOT / "data" / "ingested" / "records.db"
JSONL_PATH   = REPO_ROOT / "data" / "ingested" / "records.jsonl"
DEDUP_PATH   = REPO_ROOT / "data" / "ingested" / "deduplication.json"
SERVE_DIR    = Path(__file__).resolve().parent
PROFILES_DIR = REPO_ROOT / "src" / "qrem" / "hardware_profiles"

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

# Profile dimension fields and their types (single = binary match, list = Jaccard)
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

# Field label lookup for similarity explanations
FIELD_LABEL_MAP = {f: label for f, label in ALL_NUMERIC_FIELDS}
SIMILARITY_FIELDS = [f for f, _ in ALL_NUMERIC_FIELDS]

# Scoring weights
PROFILE_WEIGHT = 0.75
NUMERIC_WEIGHT = 0.25


# ── Similarity search ─────────────────────────────────────────────────────

def _jaccard(a: list, b: list) -> float:
    """Jaccard similarity between two lists (treated as sets)."""
    set_a = set(a or [])
    set_b = set(b or [])
    if not set_a and not set_b:
        return 1.0   # both empty → identical
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _parse_json_list(val) -> list:
    """Safely parse a JSON array stored as a string in SQLite."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def compute_profile_score(query: dict, candidate: dict) -> tuple[float, list]:
    """
    Compute semantic profile similarity score (0.0 = identical, 1.0 = maximally different).
    Returns (score, matched_tags) where matched_tags is a list of dicts for the frontend.

    Falls back to (None, []) if either sample has no profile.
    """
    if not query.get('sim_profile_version') or not candidate.get('sim_profile_version'):
        return None, []

    matched_tags = []
    total_score = 0.0
    num_dimensions = len(PROFILE_SINGLE_FIELDS) + len(PROFILE_LIST_FIELDS)

    # Single-value fields: binary match (0 = same, 1 = different)
    for field, label in PROFILE_SINGLE_FIELDS:
        q_val = query.get(field)
        c_val = candidate.get(field)
        if q_val and c_val:
            match = (q_val == c_val)
            total_score += 0.0 if match else 1.0
            matched_tags.append({
                'field': field,
                'label': label,
                'query_value': q_val,
                'candidate_value': c_val,
                'match': match,
                'type': 'single',
            })
        else:
            # Missing on one side — treat as neutral (0.5)
            total_score += 0.5

    # List fields: Jaccard distance (0 = identical sets, 1 = disjoint)
    for field, label in PROFILE_LIST_FIELDS:
        q_list = _parse_json_list(query.get(field))
        c_list = _parse_json_list(candidate.get(field))
        jaccard_sim = _jaccard(q_list, c_list)
        jaccard_dist = 1.0 - jaccard_sim
        total_score += jaccard_dist
        shared = list(set(q_list) & set(c_list))
        matched_tags.append({
            'field': field,
            'label': label,
            'query_value': q_list,
            'candidate_value': c_list,
            'shared': shared,
            'jaccard_similarity': round(jaccard_sim, 3),
            'type': 'list',
        })

    # Normalize to [0, 1]
    profile_score = total_score / num_dimensions
    return profile_score, matched_tags


def compute_numeric_score(query: dict, candidate: dict, field_stats: dict) -> tuple[float, list]:
    """
    Compute numeric field similarity score (0.0 = identical, higher = more different).
    Returns (weighted_score, matched_fields).

    Returns (None, []) if there are no overlapping numeric fields.
    """
    overlap_fields = []
    for field in SIMILARITY_FIELDS:
        q_val = query.get(field)
        c_val = candidate.get(field)
        if q_val is not None and c_val is not None and field in field_stats:
            overlap_fields.append(field)

    if not overlap_fields:
        return None, []

    total_dist = 0.0
    matched = []
    for field in overlap_fields:
        q_val = query[field]
        c_val = candidate[field]
        stats = field_stats[field]
        norm_q = (q_val - stats['mean']) / stats['std']
        norm_c = (c_val - stats['mean']) / stats['std']
        dist = abs(norm_q - norm_c)
        total_dist += dist
        matched.append({
            'field': field,
            'label': FIELD_LABEL_MAP.get(field, field),
            'query_value': q_val,
            'candidate_value': c_val,
            'normalized_distance': round(dist, 3),
        })

    matched.sort(key=lambda x: x['normalized_distance'])
    mean_dist = total_dist / len(overlap_fields)
    weighted_score = mean_dist / math.sqrt(len(overlap_fields))
    return weighted_score, matched


def compute_similarity(samples: list, query_name: str, n: int = 10, same_pub: bool = False) -> list:
    """
    Find the N most similar samples to the query sample.

    Hybrid scoring (75% profile, 25% numeric):
    - Profile score: semantic similarity over 8 profile dimensions.
        Single fields (material_class, transport_regime, device_type,
        coherence_tier, growth_method): binary match.
        List fields (loss_mechanisms, science_focus, key_correlations): Jaccard similarity.
    - Numeric score: mean z-score normalized distance over overlapping numeric fields,
        weighted by sqrt(overlap_count) to reward more shared fields.

    Falls back gracefully:
    - If only one layer is available, uses that layer at 100%.
    - Samples with no profile and no numeric overlap are excluded.

    Returns results sorted best-first (lowest combined score = most similar).
    """
    # Find query sample
    query = next((s for s in samples if s.get('display_name') == query_name), None)
    if query is None:
        return []

    query_filename = query.get('filename', '')

    # Compute per-field mean and std across the full corpus for numeric scoring
    field_stats = {}
    for field in SIMILARITY_FIELDS:
        vals = [s[field] for s in samples if s.get(field) is not None]
        if len(vals) < 2:
            continue
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = math.sqrt(variance)
        if std > 0:
            field_stats[field] = {'mean': mean, 'std': std}

    results = []
    for candidate in samples:
        if candidate.get('display_name') == query_name:
            continue  # skip self

        # Same-publication filter
        if not same_pub and candidate.get('filename') == query_filename:
            continue

        # Compute both layers
        profile_score, profile_tags = compute_profile_score(query, candidate)
        numeric_score, numeric_fields = compute_numeric_score(query, candidate, field_stats)

        # Combine — fall back if one layer is unavailable
        if profile_score is not None and numeric_score is not None:
            combined_score = PROFILE_WEIGHT * profile_score + NUMERIC_WEIGHT * numeric_score
            scoring_mode = 'hybrid'
        elif profile_score is not None:
            combined_score = profile_score
            scoring_mode = 'profile_only'
        elif numeric_score is not None:
            combined_score = numeric_score
            scoring_mode = 'numeric_only'
        else:
            continue  # no basis for comparison

        results.append({
            'display_name':    candidate.get('display_name'),
            'film_material':   candidate.get('film_material'),
            'substrate_material': candidate.get('substrate_material'),
            'authors':         candidate.get('authors'),
            'doi':             candidate.get('doi'),
            'filename':        candidate.get('filename'),
            'score':           round(combined_score, 4),
            'scoring_mode':    scoring_mode,
            'overlap_count':   len(numeric_fields),
            'profile_tags':    profile_tags,    # for frontend tag display
            'matched_fields':  numeric_fields,  # for frontend numeric chips
        })

    results.sort(key=lambda x: x['score'])
    return results[:n]


# ── Ingestion state (shared between threads) ──────────────────────────────

_ingest_state = {
    "running":   False,
    "done":      False,
    "progress":  [],
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
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

def find_duplicate_pairs(threshold: float = 0.85) -> list:
    if not JSONL_PATH.exists():
        return []
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
                        "filename":    rec.get("filename"),
                        "title":       rec.get("title") or "",
                        "authors":     rec.get("authors") or "",
                        "journal":     rec.get("journal") or "",
                        "doi":         rec.get("doi"),
                        "num_samples": len((rec.get("extraction_json") or {}).get("samples", [])),
                    })
            except json.JSONDecodeError:
                pass

    decided_pairs = set()
    if DEDUP_PATH.exists():
        try:
            dedup = json.loads(DEDUP_PATH.read_text())
            for d in dedup.get("decisions", []):
                key = tuple(sorted([d["paper_a"], d["paper_b"]]))
                decided_pairs.add(key)
        except Exception:
            pass

    pairs = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            a, b = records[i], records[j]
            key = tuple(sorted([a["filename"], b["filename"]]))
            if key in decided_pairs or a["filename"] == b["filename"]:
                continue
            sim = title_similarity(a["title"], b["title"])
            if sim >= threshold:
                pairs.append({"paper_a": a, "paper_b": b, "similarity": round(sim, 3)})
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
    profile_single_cols = ', '.join(f's.{f}' for f, _ in PROFILE_SINGLE_FIELDS)
    profile_list_cols   = ', '.join(f's.{f}' for f, _ in PROFILE_LIST_FIELDS)
    cur.execute(f"""
        SELECT
            s.display_name, s.sample_id, s.filename,
            s.film_material, s.film_crystal_phase,
            s.substrate_material, s.deposition_method,
            s.Tc_confidence, s.RRR_confidence,
            s.Qi_confidence, s.T1_confidence,
            p.authors, p.title, p.doi, p.journal,
            s.sim_profile_version,
            {profile_single_cols},
            {profile_list_cols},
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

def fetch_sample_detail(display_name: str) -> dict:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.*, p.title, p.authors, p.doi, p.journal
        FROM samples s
        JOIN papers p ON s.paper_id = p.id
        WHERE s.display_name = ?
        LIMIT 1
    """, (display_name,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    sample = dict(row)
    sample.pop('sample_json', None)
    sample.pop('derived_json', None)
    sample.pop('extraction_json', None)
    cur.execute("""
        SELECT item_type, description, value, source, notes
        FROM catchall_items
        WHERE display_name = ?
        ORDER BY item_type, description
    """, (display_name,))
    catchall = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"sample": sample, "catchall": catchall}


# ── HTTP Handler ──────────────────────────────────────────────────────────

class Handler(http.server.SimpleHTTPRequestHandler):
    # Cache samples in memory to avoid re-querying DB on every similarity request
    _samples_cache = None
    _samples_cache_lock = threading.Lock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    @classmethod
    def get_cached_samples(cls):
        with cls._samples_cache_lock:
            if cls._samples_cache is None:
                cls._samples_cache = fetch_samples()
            return cls._samples_cache

    @classmethod
    def invalidate_cache(cls):
        with cls._samples_cache_lock:
            cls._samples_cache = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))

        if path == '/':
            self.send_response(302)
            self.send_header('Location', '/materials_explorer.html')
            self.end_headers()
            return

        if path == "/api/samples":
            samples = fetch_samples()
            Handler._samples_cache = samples   # warm the cache
            self._json(200, {"ok": True, "samples": samples})

        elif path == "/api/fields":
            self._json(200, {"ok": True, "fields": fetch_available_fields()})

        elif path == "/api/catchall":
            item_type = params.get("type")
            self._json(200, {"ok": True, "items": fetch_catchall(item_type)})

        elif path == "/api/coverage":
            self._json(200, {"ok": True, "coverage": fetch_coverage()})

        elif path == "/api/ingest/status":
            with _ingest_lock:
                state = dict(_ingest_state)
            self._json(200, {"ok": True, "state": state})

        elif path == "/api/duplicates":
            pairs = find_duplicate_pairs()
            self._json(200, {"ok": True, "pairs": pairs, "count": len(pairs)})

        elif path.startswith("/api/sample/"):
            raw          = path[len("/api/sample/"):]
            display_name = urllib.parse.unquote(raw, encoding='utf-8')
            detail       = fetch_sample_detail(display_name)
            if detail:
                self._json(200, {"ok": True, **detail})
            else:
                self._json(404, {"ok": False, "error": f"Sample not found: {display_name}"})

        elif path == "/api/similar":
            display_name = urllib.parse.unquote(params.get("display_name", "")).strip()
            n            = int(params.get("n", 10))
            same_pub     = params.get("same_pub", "false").lower() == "true"
            if not display_name:
                self._json(400, {"ok": False, "error": "display_name required"})
                return
            try:
                samples = self.get_cached_samples()
                results = compute_similarity(samples, display_name, n=n, same_pub=same_pub)
                self._json(200, {
                    "ok":          True,
                    "query":       display_name,
                    "same_pub":    same_pub,
                    "n_returned":  len(results),
                    "results":     results,
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json(500, {"ok": False, "error": str(e)})

        elif path == "/api/generate_profile":
            display_name = params.get("display_name", "")
            do_save      = params.get("save", "false").lower() == "true"
            if not display_name:
                self._json(400, {"ok": False, "error": "display_name required"})
                return
            try:
                sample = fetch_sample_from_db(display_name, str(DB_PATH))
                result = generate_profile(sample, str(PROFILES_DIR))
                if do_save:
                    save_profile(result, str(PROFILES_DIR))
                self._json(200, {
                    "ok":              True,
                    "filename":        result["filename"],
                    "measured_fields": result["measured_fields"],
                    "assumed_fields":  result["assumed_fields"],
                    "yaml_preview":    result["yaml_str"],
                    "saved":           do_save,
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json(500, {"ok": False, "error": str(e)})

        else:
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}

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
            decision = body.get("decision")
            keep     = body.get("keep")
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
                Handler.invalidate_cache()  # DB rebuilt — flush sample cache
                self._json(200, {
                    "ok":    result.returncode == 0,
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
