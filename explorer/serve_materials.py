#!/usr/bin/env python3
# ingester/serve_materials.py
# Local development server for the C2QA Materials Pipeline UI.
# Serves static files and provides a JSON API over the SQLite database.
#
# Usage:
#   cd ingester
#   python3 serve_materials.py
#   # Materials Explorer:   http://localhost:8001/materials_explorer.html
#   # Ingestion Pipeline:   http://localhost:8001/ingest_pipeline.html
#
# API routes:
#   GET  /api/samples                  — all samples with key measurement fields
#   GET  /api/fields                   — available numeric fields (only those with data)
#   GET  /api/catchall                 — catchall items
#   GET  /api/corpus                   — all samples as self-contained records
#   GET  /api/coverage                 — coverage summary
#   GET  /api/sample/{display_name}    — full detail for one sample
#   GET  /api/similar                  — similarity search
#   GET  /api/generate_profile         — generate QREM qubit profile YAML
#   GET  /api/mining/findings          — load mining findings
#   GET  /api/mining/status            — poll mining pipeline progress
#   GET  /api/ingest/status            — poll ingestion progress
#   GET  /api/duplicates               — potential duplicate pairs
#   POST /api/ingest/start             — start ingestion run
#   POST /api/duplicates/decide        — record a duplicate decision
#   POST /api/build                    — run build_sqlite
#   POST /api/mining/run               — run full A->B->C mining pipeline
#   POST /api/mining/approve           — approve a finding
#   POST /api/mining/reject            — reject a finding
#   POST /api/mining/revise            — mark finding for revision with notes
#   POST /api/mining/reset             — reset finding to pending
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
from typing import Optional, List
from generate_qubit_profile import generate_profile, save_profile, fetch_sample_from_db
import os
PORT = int(os.environ.get('PORT', 8001))
REPO_ROOT              = Path(__file__).resolve().parent.parent
DB_PATH                = REPO_ROOT / "data" / "ingested" / "records.db"
JSONL_PATH             = REPO_ROOT / "data" / "ingested" / "records.jsonl"
DEDUP_PATH             = REPO_ROOT / "data" / "ingested" / "deduplication.json"
FINDINGS_PATH          = REPO_ROOT / "data" / "ingested" / "mining_findings.jsonl"
APPROVED_FINDINGS_PATH = REPO_ROOT / "data" / "ingested" / "findings.jsonl"
MINING_SCRIPT          = Path(__file__).resolve().parent / "pipeline_mining.py"
SERVE_DIR              = Path(__file__).resolve().parent
PROFILES_DIR           = REPO_ROOT / "qrem" / "hardware_profiles"
ALL_NUMERIC_FIELDS = [
    # ── Device performance ────────────────────────────────────────────────
    ('T1_us',                 'T1 (µs)'),
    ('T2_echo_us',            'T2 echo (µs)'),
    ('T2_ramsey_us',          'T2 Ramsey (µs)'),
    ('derived_T2_us',         'T2 (best available, µs)'),
    ('gate_1q_fidelity_pct',  '1Q fidelity (%)'),
    ('gate_2q_fidelity_pct',  '2Q fidelity (%)'),
    # ── Superconducting properties ────────────────────────────────────────
    ('Tc_K',                  'Tc (K)'),
    ('RRR',                   'RRR'),
    ('derived_RRR_from_RvT',             'RRR derived from R vs T'),
    ('sheet_resistance_Ohm_sq',          'Sheet resistance (Ω/□)'),
    ('derived_sheet_resistance_Ohm_sq',  'Sheet resistance derived (Ω/□)'),
    ('derived_kinetic_inductance_pH_sq', 'Kinetic inductance derived (pH/□)'),
    ('derived_coherence_length_nm',      'Coherence length derived (nm)'),
    # ── Microwave / loss ──────────────────────────────────────────────────
    ('derived_Qi',            'Qi (best available)'),
    ('Q_TLS_0',               'Q_TLS,0 (unsaturated TLS Q)'),
    ('derived_tan_delta',     'Loss tangent (best available)'),
    ('TLS_density',           'TLS density (GHz⁻¹·μm⁻²)'),
    # ── Fabrication ───────────────────────────────────────────────────────
    ('film_thickness_nm',     'Film thickness (nm)'),
    ('annealing_temperature_C','Anneal temp (°C)'),
    ('annealing_duration_s',  'Anneal duration (s)'),
    ('surface_oxide_nm',      'Surface oxide (nm)'),
]
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
# Derived fabrication categoricals — not plottable as numeric measurements,
# but needed as group-by / color-by axes in the Explore tab (Track B, July 2026).
# Added to fetch_samples()'s SELECT so the Explore tab can offer them as
# stripGroupBy / colorBy options alongside derived_material / derived_substrate /
# derived_deposition_method. Sparse until Priority 2 re-ingestion completes —
# samples without fabrication data simply carry None for these fields, which
# the existing frontend group-by logic already buckets as "unknown".
DERIVED_CATEGORICAL_FIELDS = [
    'derived_resist_strip_family',
    'derived_post_fab_treatment_family',
    'derived_junction_vacuum_class',
]
VALID_CATCHALL_TYPES = {
    "correlation",
    "additional_measurement",
    "anomalous_observation",
    "schema_candidate",
}
FIELD_LABEL_MAP   = {f: label for f, label in ALL_NUMERIC_FIELDS}
SIMILARITY_FIELDS = [f for f, _ in ALL_NUMERIC_FIELDS]
PROFILE_WEIGHT    = 0.75
NUMERIC_WEIGHT    = 0.25
# ── Similarity helpers ────────────────────────────────────────────────────────
def _jaccard(a: list, b: list) -> float:
    set_a, set_b = set(a or []), set(b or [])
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)
def _parse_json_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
def compute_profile_score(query: dict, candidate: dict):
    if not query.get('sim_profile_version') or not candidate.get('sim_profile_version'):
        return None, []
    matched_tags = []
    total_score  = 0.0
    num_dims     = len(PROFILE_SINGLE_FIELDS) + len(PROFILE_LIST_FIELDS)
    for field, label in PROFILE_SINGLE_FIELDS:
        q_val, c_val = query.get(field), candidate.get(field)
        if q_val and c_val:
            match = (q_val == c_val)
            total_score += 0.0 if match else 1.0
            matched_tags.append({'field': field, 'label': label,
                                  'query_value': q_val, 'candidate_value': c_val,
                                  'match': match, 'type': 'single'})
        else:
            total_score += 0.5
    for field, label in PROFILE_LIST_FIELDS:
        q_list = _parse_json_list(query.get(field))
        c_list = _parse_json_list(candidate.get(field))
        jsim   = _jaccard(q_list, c_list)
        total_score += 1.0 - jsim
        matched_tags.append({'field': field, 'label': label,
                              'query_value': q_list, 'candidate_value': c_list,
                              'shared': list(set(q_list) & set(c_list)),
                              'jaccard_similarity': round(jsim, 3), 'type': 'list'})
    return total_score / num_dims, matched_tags
def compute_numeric_score(query: dict, candidate: dict, field_stats: dict):
    overlap = [f for f in SIMILARITY_FIELDS
               if query.get(f) is not None and candidate.get(f) is not None
               and f in field_stats]
    if not overlap:
        return None, []
    total, matched = 0.0, []
    for field in overlap:
        stats  = field_stats[field]
        norm_q = (query[field]     - stats['mean']) / stats['std']
        norm_c = (candidate[field] - stats['mean']) / stats['std']
        dist   = abs(norm_q - norm_c)
        total += dist
        matched.append({'field': field, 'label': FIELD_LABEL_MAP.get(field, field),
                        'query_value': query[field], 'candidate_value': candidate[field],
                        'normalized_distance': round(dist, 3)})
    matched.sort(key=lambda x: x['normalized_distance'])
    return (total / len(overlap)) / math.sqrt(len(overlap)), matched
def compute_similarity(samples: list, query_name: str,
                        n: int = 10, same_pub: bool = False) -> list:
    query = next((s for s in samples if s.get('display_name') == query_name), None)
    if query is None:
        return []
    query_filename = query.get('filename', '')
    field_stats = {}
    for field in SIMILARITY_FIELDS:
        vals = [s[field] for s in samples if s.get(field) is not None]
        if len(vals) < 2:
            continue
        mean = sum(vals) / len(vals)
        std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
        if std > 0:
            field_stats[field] = {'mean': mean, 'std': std}
    results = []
    for candidate in samples:
        if candidate.get('display_name') == query_name:
            continue
        if not same_pub and candidate.get('filename') == query_filename:
            continue
        ps, pt = compute_profile_score(query, candidate)
        ns, nf = compute_numeric_score(query, candidate, field_stats)
        if ps is not None and ns is not None:
            score, mode = PROFILE_WEIGHT * ps + NUMERIC_WEIGHT * ns, 'hybrid'
        elif ps is not None:
            score, mode = ps, 'profile_only'
        elif ns is not None:
            score, mode = ns, 'numeric_only'
        else:
            continue
        results.append({
            'display_name':       candidate.get('display_name'),
            'film_material':      candidate.get('film_material'),
            'substrate_material': candidate.get('substrate_material'),
            'authors':            candidate.get('authors'),
            'doi':                candidate.get('doi'),
            'filename':           candidate.get('filename'),
            'score':              round(score, 4),
            'scoring_mode':       mode,
            'overlap_count':      len(nf),
            'profile_tags':       pt,
            'matched_fields':     nf,
        })
    results.sort(key=lambda x: x['score'])
    return results[:n]
# ── Ingestion state ───────────────────────────────────────────────────────────
_ingest_state = {
    "running": False, "done": False, "progress": [],
    "total": 0, "processed": 0, "success": 0,
    "failed": 0, "skipped": 0, "current": None,
}
_ingest_lock = threading.Lock()
def _run_ingestion(papers_dir: str):
    with _ingest_lock:
        _ingest_state.update({
            "running": True, "done": False, "progress": [],
            "success": 0, "failed": 0, "skipped": 0, "current": None,
        })
    script = SERVE_DIR / "pipeline_ingest.py"
    try:
        proc = subprocess.Popen(
            ["python3", str(script), "--papers-dir", papers_dir],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(SERVE_DIR),
        )
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            with _ingest_lock:
                _ingest_state["progress"].append(line)
                if line.startswith("[") and "/" in line[:10]:
                    _ingest_state["current"] = line
                if "Done [OK]"    in line: _ingest_state["success"] += 1
                elif "Done [FAIL" in line: _ingest_state["failed"]  += 1
                elif "Skipping"   in line: _ingest_state["skipped"] += 1
        proc.wait()
    except Exception as e:
        with _ingest_lock:
            _ingest_state["progress"].append(f"ERROR: {e}")
    with _ingest_lock:
        _ingest_state["running"] = False
        _ingest_state["done"]    = True
# ── Mining state ──────────────────────────────────────────────────────────────
_mining_state = {
    "running": False, "done": False,
    "progress": [], "error": None,
}
_mining_lock = threading.Lock()
def _run_mining():
    """Run pipeline_mining.py phase-a -> phase-b -> phase-c in sequence."""
    with _mining_lock:
        _mining_state.update({
            "running": True, "done": False,
            "progress": [], "error": None,
        })
    phases = [
        ("phase-a", ["python3", str(MINING_SCRIPT), "phase-a"]),
        ("phase-b", ["python3", str(MINING_SCRIPT), "phase-b"]),
        ("phase-c", ["python3", str(MINING_SCRIPT), "phase-c"]),
    ]
    try:
        for phase_name, cmd in phases:
            with _mining_lock:
                _mining_state["progress"].append(f"=== Starting {phase_name} ===")
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(SERVE_DIR),
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    with _mining_lock:
                        _mining_state["progress"].append(line)
            proc.wait()
            if proc.returncode != 0:
                with _mining_lock:
                    _mining_state["error"]   = f"{phase_name} failed (exit {proc.returncode})"
                    _mining_state["running"] = False
                    _mining_state["done"]    = True
                return
            with _mining_lock:
                _mining_state["progress"].append(f"=== {phase_name} complete ✓ ===")
    except Exception as e:
        with _mining_lock:
            _mining_state["error"] = str(e)
    with _mining_lock:
        _mining_state["running"] = False
        _mining_state["done"]    = True
# ── Mining findings helpers ───────────────────────────────────────────────────
def load_mining_findings() -> list:
    if not FINDINGS_PATH.exists():
        return []
    findings = []
    with open(FINDINGS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                findings.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    TYPE_ORDER = {
        "positive":              0,
        "negative":              1,
        "inconclusive":          2,
        "derived_field_artifact": 3,
    }
    findings.sort(key=lambda f: (
        TYPE_ORDER.get(
            (f.get("writeup") or {}).get("finding_type"), 99
        ),
        -(f.get("writeup") or {}).get("confidence", 0),
    ))
    return findings
def save_mining_findings(findings: list):
    FINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FINDINGS_PATH, "w", encoding="utf-8") as f:
        for finding in findings:
            f.write(json.dumps(finding, ensure_ascii=False, default=str) + "\n")
def append_approved_finding(finding: dict):
    """Append to the canonical append-only findings.jsonl ledger."""
    APPROVED_FINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(APPROVED_FINDINGS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(finding, ensure_ascii=False, default=str) + "\n")
def load_approved_findings() -> dict:
    """Read findings.jsonl and return latest approved entry per hypothesis_key."""
    if not APPROVED_FINDINGS_PATH.exists():
        return {}
    by_key = {}
    with open(APPROVED_FINDINGS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                key = entry.get("hypothesis_key")
                if key:
                    by_key[key] = entry  # last write wins
            except json.JSONDecodeError:
                pass
    return by_key
# ── Duplicate detection ───────────────────────────────────────────────────────
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
                decided_pairs.add(tuple(sorted([d["paper_a"], d["paper_b"]])))
        except Exception:
            pass
    pairs = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            a, b = records[i], records[j]
            key  = tuple(sorted([a["filename"], b["filename"]]))
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
# ── Database functions ────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
def fetch_available_fields():
    conn = get_db()
    cur  = conn.cursor()
    available = []
    for field, label in ALL_NUMERIC_FIELDS:
        try:
            cur.execute(
                f"SELECT COUNT(*) FROM samples s JOIN papers p ON s.paper_id = p.id "
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
    cur  = conn.cursor()
    numeric_cols        = ', '.join(f's.{f}' for f, _ in ALL_NUMERIC_FIELDS)
    profile_single_cols = ', '.join(f's.{f}' for f, _ in PROFILE_SINGLE_FIELDS)
    profile_list_cols   = ', '.join(f's.{f}' for f, _ in PROFILE_LIST_FIELDS)
    # Derived fabrication categoricals (Track B, July 2026) — group-by / color-by
    # axes for the Explore tab, alongside derived_material / derived_substrate /
    # derived_deposition_method which are already selected explicitly below.
    derived_cat_cols    = ', '.join(f's.{f}' for f in DERIVED_CATEGORICAL_FIELDS)
    # Raw variant fields needed for derived-field source tracking.
    # Not in ALL_NUMERIC_FIELDS (removed from dropdown) but needed to know
    # which variant populated derived_Qi / derived_T2_us / derived_tan_delta.
    RAW_SOURCE_COLS = (
        's.Qi_internal, s.Qi_single_photon, '
        's.T2_echo_us, s.T2_ramsey_us, '
        's.tan_delta_effective_surface, s.loss_tangent_interface, s.loss_tangent_substrate'
    )
    cur.execute(f"""
        SELECT s.display_name, s.sample_id, s.filename,
               s.film_material, s.film_crystal_phase,
               s.derived_material,
               s.derived_substrate, s.derived_deposition_method,
               s.substrate_material, s.deposition_method,
               s.Tc_confidence, s.RRR_confidence,
               s.Qi_confidence, s.T1_confidence,
               p.authors, p.title, p.doi, p.journal,
               s.sim_profile_version,
               {profile_single_cols}, {profile_list_cols}, {numeric_cols},
               {derived_cat_cols},
               {RAW_SOURCE_COLS}
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
                try:    d[field] = float(val)
                except: d[field] = None
        # ── Derived-field source tracking ─────────────────────────────────
        # For each "best available" derived field, record which raw variant
        # was used so the frontend can encode it as a symbol.
        # Priority mirrors build_sqlite.py — must stay in sync.
        def _src(d, *candidates):
            """Return the name of the first non-null candidate field."""
            for c in candidates:
                try:
                    if d.get(c) is not None and float(d[c]) == float(d[c]):
                        return c
                except (TypeError, ValueError):
                    pass
            return None
        d['derived_Qi_source']        = _src(d, 'Qi_single_photon', 'Qi_internal')
        d['derived_T2_us_source']     = _src(d, 'T2_echo_us', 'T2_ramsey_us')
        d['derived_tan_delta_source'] = _src(d, 'tan_delta_effective_surface',
                                               'loss_tangent_interface',
                                               'loss_tangent_substrate')
        samples.append(d)
    return samples
def fetch_catchall(item_type=None):
    conn = get_db()
    cur  = conn.cursor()
    if item_type:
        cur.execute("""
            SELECT c.display_name, c.item_type, c.description,
                   c.value, c.source, c.notes, p.authors, p.title
            FROM catchall_items c JOIN papers p ON c.paper_id = p.id
            WHERE c.item_type = ? ORDER BY c.display_name
        """, (item_type,))
    else:
        cur.execute("""
            SELECT c.display_name, c.item_type, c.description,
                   c.value, c.source, c.notes, p.authors, p.title
            FROM catchall_items c JOIN papers p ON c.paper_id = p.id
            ORDER BY c.item_type, c.display_name
        """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
def fetch_corpus(types: Optional[List[str]] = None) -> List[dict]:
    """All ingested samples as self-contained records with nested catchall."""
    if types:
        requested_types = [t for t in types if t in VALID_CATCHALL_TYPES]
    else:
        requested_types = list(VALID_CATCHALL_TYPES)
    conn = get_db()
    cur  = conn.cursor()
    numeric_cols        = ', '.join(f's.{f}' for f, _ in ALL_NUMERIC_FIELDS)
    profile_single_cols = ', '.join(f's.{f}' for f, _ in PROFILE_SINGLE_FIELDS)
    profile_list_cols   = ', '.join(f's.{f}' for f, _ in PROFILE_LIST_FIELDS)
    cur.execute(f"""
        SELECT s.display_name, s.sample_id, s.filename,
               s.film_material, s.film_crystal_phase,
               s.substrate_material, s.substrate_orientation,
               s.deposition_method, s.deposition_temperature_C,
               s.annealing_temperature_C, s.annealing_duration_s,
               s.junction_present, s.film_thickness_nm,
               s.Tc_confidence, s.RRR_confidence,
               s.Qi_confidence, s.T1_confidence,
               s.sample_json, s.derived_json,
               s.sim_profile_version,
               p.authors, p.title, p.doi, p.journal,
               p.human_reviewed, p.human_approved,
               {profile_single_cols}, {profile_list_cols}, {numeric_cols}
        FROM samples s JOIN papers p ON s.paper_id = p.id
        WHERE p.outcome = 'ingested'
        ORDER BY s.film_material, s.display_name
    """)
    rows = cur.fetchall()
    numeric_field_names = [f for f, _ in ALL_NUMERIC_FIELDS]
    samples_by_name = {}
    for row in rows:
        d = dict(row)
        for field in numeric_field_names:
            val = d.get(field)
            if val is not None:
                try:    d[field] = float(val)
                except: d[field] = None
        for blob in ('sample_json', 'derived_json'):
            raw = d.get(blob)
            if raw:
                try:    d[blob] = json.loads(raw)
                except: d[blob] = None
        for field, _ in PROFILE_LIST_FIELDS:
            d[field] = _parse_json_list(d.get(field))
        d['catchall'] = []
        samples_by_name[d['display_name']] = d
    placeholders = ','.join('?' * len(requested_types))
    cur.execute(f"""
        SELECT c.display_name, c.item_type, c.description,
               c.value, c.source, c.notes, c.sample_id
        FROM catchall_items c JOIN papers p ON c.paper_id = p.id
        WHERE p.outcome = 'ingested' AND c.item_type IN ({placeholders})
        ORDER BY c.display_name, c.item_type
    """, requested_types)
    catchall_rows = cur.fetchall()
    conn.close()
    orphaned = 0
    for crow in catchall_rows:
        c    = dict(crow)
        name = c.pop('display_name')
        if name in samples_by_name:
            samples_by_name[name]['catchall'].append(c)
        else:
            orphaned += 1
    if orphaned:
        print(f"  fetch_corpus: {orphaned} orphaned catchall item(s)")
    return list(samples_by_name.values())
def fetch_coverage():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) as total_samples,
               SUM(CASE WHEN Tc_K IS NOT NULL THEN 1 ELSE 0 END) as has_Tc,
               SUM(CASE WHEN RRR IS NOT NULL THEN 1 ELSE 0 END) as has_RRR,
               SUM(CASE WHEN Qi_internal IS NOT NULL THEN 1 ELSE 0 END) as has_Qi,
               SUM(CASE WHEN T1_us IS NOT NULL THEN 1 ELSE 0 END) as has_T1,
               SUM(CASE WHEN T2_echo_us IS NOT NULL THEN 1 ELSE 0 END) as has_T2,
               SUM(CASE WHEN gate_2q_fidelity_pct IS NOT NULL THEN 1 ELSE 0 END) as has_2q_fidelity
        FROM samples s JOIN papers p ON s.paper_id = p.id
        WHERE p.outcome = 'ingested'
    """)
    row = cur.fetchone()
    conn.close()
    return dict(row)
def fetch_papers():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT p.authors, p.title, p.journal, p.doi,
               COUNT(s.id) as sample_count
        FROM papers p
        LEFT JOIN samples s ON s.paper_id = p.id
        WHERE p.outcome = 'ingested'
        GROUP BY p.id
        ORDER BY p.authors
    """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
    
def fetch_sample_detail(display_name: str) -> dict:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT s.*, p.title, p.authors, p.doi, p.journal
        FROM samples s JOIN papers p ON s.paper_id = p.id
        WHERE s.display_name = ? LIMIT 1
    """, (display_name,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    sample = dict(row)
    for k in ('sample_json', 'derived_json', 'extraction_json'):
        sample.pop(k, None)
    cur.execute("""
        SELECT item_type, description, value, source, notes
        FROM catchall_items WHERE display_name = ?
        ORDER BY item_type, description
    """, (display_name,))
    catchall = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"sample": sample, "catchall": catchall}
# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    _samples_cache      = None
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
            Handler._samples_cache = samples
            self._json(200, {"ok": True, "samples": samples})
        elif path == "/api/fields":
            self._json(200, {"ok": True, "fields": fetch_available_fields()})
        elif path == "/api/catchall":
            self._json(200, {"ok": True,
                             "items": fetch_catchall(params.get("type"))})
        elif path == "/api/corpus":
            raw_types = params.get("types", "")
            types  = [t.strip() for t in raw_types.split(",") if t.strip()] or None
            corpus = fetch_corpus(types=types)
            counts = {t: sum(1 for s in corpus for i in s['catchall']
                             if i['item_type'] == t)
                      for t in VALID_CATCHALL_TYPES}
            self._json(200, {
                "ok":               True,
                "sample_count":     len(corpus),
                "catchall_total":   sum(counts.values()),
                "catchall_by_type": counts,
                "types_included":   list(VALID_CATCHALL_TYPES) if not types else types,
                "samples":          corpus,
            })
        elif path == "/api/coverage":
            self._json(200, {"ok": True, "coverage": fetch_coverage()})
        elif path == "/api/papers":
            self._json(200, {"ok": True, "papers": fetch_papers()})
    
        elif path == "/api/ingest/status":
            with _ingest_lock:
                state = dict(_ingest_state)
            self._json(200, {"ok": True, "state": state})
        elif path == "/api/mining/findings":
            findings = load_mining_findings()
            self._json(200, {"ok": True, "count": len(findings), "findings": findings})
        elif path == "/api/approved_findings":
            by_key = load_approved_findings()
            # sort: positive first, then negative, inconclusive, derived; highest conf first
            order = {"positive": 0, "negative": 1, "inconclusive": 2, "derived_field_artifact": 3}
            findings = sorted(
                by_key.values(),
                key=lambda f: (
                    order.get((f.get("writeup") or {}).get("finding_type", ""), 99),
                    -(f.get("phase_b_confidence") or (f.get("writeup") or {}).get("confidence") or 0)
                )
            )
            self._json(200, {"ok": True, "count": len(findings), "findings": findings})
        
        elif path == "/api/schema/candidates":
            freq_path = REPO_ROOT / "data" / "ingested" / "mining_measurement_frequency.json"
            if not freq_path.exists():
                self._json(200, {"ok": True, "candidates": []})
                return
            try:
                # get fields promote_fields.py knows about
                list_result = subprocess.run(
                    ["python3", str(SERVE_DIR / "promote_fields.py"), "--list"],
                    capture_output=True, text=True, cwd=str(SERVE_DIR)
                )
                promotable = set()
                for line in list_result.stdout.splitlines():
                    line = line.strip()
                    if line and not line.startswith("Defined") and not line.startswith("Pattern") and not line.startswith("Units"):
                        promotable.add(line)
                data = json.loads(freq_path.read_text())
                candidates = [
                    m for m in data.get("top_measurements", [])
                    if not m.get("in_schema") and m.get("term") in promotable
                ]
                candidates.sort(key=lambda x: -x["count"])
                self._json(200, {"ok": True, "candidates": candidates})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
                
        elif path == "/api/mining/status":
            with _mining_lock:
                state = dict(_mining_state)
            self._json(200, {"ok": True, "state": state})
        elif path == "/api/duplicates":
            pairs = find_duplicate_pairs()
            self._json(200, {"ok": True, "pairs": pairs, "count": len(pairs)})
        elif path.startswith("/api/sample/"):
            display_name = urllib.parse.unquote(
                path[len("/api/sample/"):], encoding='utf-8')
            detail = fetch_sample_detail(display_name)
            if detail:
                self._json(200, {"ok": True, **detail})
            else:
                self._json(404, {"ok": False, "error": f"Not found: {display_name}"})
        elif path == "/api/similar":
            display_name = urllib.parse.unquote(
                params.get("display_name", "")).strip()
            n        = int(params.get("n", 10))
            same_pub = params.get("same_pub", "false").lower() == "true"
            if not display_name:
                self._json(400, {"ok": False, "error": "display_name required"})
                return
            try:
                samples = self.get_cached_samples()
                results = compute_similarity(samples, display_name,
                                             n=n, same_pub=same_pub)
                self._json(200, {"ok": True, "query": display_name,
                                 "same_pub": same_pub,
                                 "n_returned": len(results), "results": results})
            except Exception as e:
                import traceback; traceback.print_exc()
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
                self._json(200, {"ok": True,
                                 "filename":        result["filename"],
                                 "measured_fields": result["measured_fields"],
                                 "assumed_fields":  result["assumed_fields"],
                                 "yaml_preview":    result["yaml_str"],
                                 "saved":           do_save})
            except Exception as e:
                import traceback; traceback.print_exc()
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
            threading.Thread(target=_run_ingestion,
                             args=(papers_dir,), daemon=True).start()
            self._json(200, {"ok": True, "message": "Ingestion started"})
        elif self.path == "/api/duplicates/decide":
            try:
                dedup = load_dedup()
                dedup["decisions"].append({
                    "paper_a":    body.get("paper_a"),
                    "paper_b":    body.get("paper_b"),
                    "decision":   body.get("decision"),
                    "keep":       body.get("keep"),
                    "decided_at": time.strftime("%Y-%m-%d"),
                })
                save_dedup(dedup)
                self._json(200, {"ok": True})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
        elif self.path == "/api/build":
            try:
                result = subprocess.run(
                    ["python3", str(SERVE_DIR / "build_sqlite.py")],
                    capture_output=True, text=True, cwd=str(SERVE_DIR)
                )
                Handler.invalidate_cache()
                self._json(200, {"ok": result.returncode == 0,
                                 "output": result.stdout + result.stderr})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
        elif self.path == "/api/mining/run":
            with _mining_lock:
                if _mining_state["running"]:
                    self._json(400, {"ok": False, "error": "Mining already running"})
                    return
            threading.Thread(target=_run_mining, daemon=True).start()
            self._json(200, {"ok": True, "message": "Mining pipeline started"})
        elif self.path == "/api/mining/approve":
            hyp_key = body.get("hypothesis_key")
            force   = body.get("force", False)
            if not hyp_key:
                self._json(400, {"ok": False, "error": "hypothesis_key required"})
                return
            try:
                approved = load_approved_findings()
                if hyp_key in approved and not force:
                    prev = approved[hyp_key]
                    self._json(200, {
                        "ok":              True,
                        "already_approved": True,
                        "previous_date":   prev.get("reviewed_at", "unknown"),
                    })
                    return
                findings = load_mining_findings()
                updated  = False
                for f in findings:
                    if f.get("hypothesis_key") == hyp_key:
                        f["review_status"] = "approved"
                        f["reviewed_at"]   = time.strftime("%Y-%m-%d")
                        append_approved_finding(f)
                        updated = True
                        break
                if updated:
                    save_mining_findings(findings)
                    self._json(200, {"ok": True, "already_approved": False})
                else:
                    self._json(404, {"ok": False,
                                     "error": f"Finding not found: {hyp_key}"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
        elif self.path == "/api/schema/promote":
            field = body.get("field")
            if not field:
                self._json(400, {"ok": False, "error": "field required"})
                return
            try:
                promote_result = subprocess.run(
                    ["python3", str(SERVE_DIR / "promote_fields.py"), "--field", field],
                    capture_output=True, text=True, cwd=str(SERVE_DIR)
                )
                if promote_result.returncode != 0:
                    self._json(200, {
                        "ok": False,
                        "output": promote_result.stdout + promote_result.stderr
                    })
                    return
                build_result = subprocess.run(
                    ["python3", str(SERVE_DIR / "build_sqlite.py")],
                    capture_output=True, text=True, cwd=str(SERVE_DIR)
                )
                Handler.invalidate_cache()
                self._json(200, {
                    "ok": build_result.returncode == 0,
                    "output": promote_result.stdout + build_result.stdout + build_result.stderr
                })
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
        
        elif self.path == "/api/mining/reject":
            hyp_key = body.get("hypothesis_key")
            if not hyp_key:
                self._json(400, {"ok": False, "error": "hypothesis_key required"})
                return
            try:
                findings = load_mining_findings()
                updated  = False
                for f in findings:
                    if f.get("hypothesis_key") == hyp_key:
                        f["review_status"] = "rejected"
                        f["reviewed_at"]   = time.strftime("%Y-%m-%d")
                        updated = True
                        break
                if updated:
                    save_mining_findings(findings)
                    self._json(200, {"ok": True})
                else:
                    self._json(404, {"ok": False,
                                     "error": f"Finding not found: {hyp_key}"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
        elif self.path == "/api/mining/revise":
            hyp_key = body.get("hypothesis_key")
            notes   = body.get("notes", "")
            if not hyp_key:
                self._json(400, {"ok": False, "error": "hypothesis_key required"})
                return
            try:
                findings = load_mining_findings()
                updated  = False
                for f in findings:
                    if f.get("hypothesis_key") == hyp_key:
                        f["review_status"] = "revising"
                        f["review_notes"]  = notes
                        f["reviewed_at"]   = time.strftime("%Y-%m-%d")
                        f.setdefault("revision_history", []).append({
                            "date": time.strftime("%Y-%m-%d"), "notes": notes,
                        })
                        updated = True
                        break
                if updated:
                    save_mining_findings(findings)
                    self._json(200, {"ok": True})
                else:
                    self._json(404, {"ok": False,
                                     "error": f"Finding not found: {hyp_key}"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
        elif self.path == "/api/mining/reset":
            hyp_key = body.get("hypothesis_key")
            if not hyp_key:
                self._json(400, {"ok": False, "error": "hypothesis_key required"})
                return
            try:
                findings = load_mining_findings()
                updated  = False
                for f in findings:
                    if f.get("hypothesis_key") == hyp_key:
                        f["review_status"] = "pending"
                        f["reviewed_at"]   = None
                        updated = True
                        break
                if updated:
                    save_mining_findings(findings)
                    self._json(200, {"ok": True})
                else:
                    self._json(404, {"ok": False,
                                     "error": f"Finding not found: {hyp_key}"})
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
        self.send_header("Content-Type",   "application/json")
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
