# ── fetch_corpus() — add to serve_materials.py ────────────────────────────
from typing import Optional, List
#
# Place this function alongside the other fetch_* functions (after fetch_catchall,
# before fetch_coverage). Then add the route in do_GET as shown at the bottom.
#
# This function returns all ingested samples as self-contained records, each with:
#   - All named column fields (same as fetch_samples())
#   - sample_json: full raw Pass 2 extraction (includes unpromoted fields)
#   - derived_json: all derived quantities
#   - catchall: nested list of catchall items for this sample
#
# Optional query param: types (comma-separated) filters catchall item_type.
#   e.g. /api/corpus?types=correlation,additional_measurement
#   Default: all four types included.
#
# Two SQL queries total (not N+1):
#   1. All samples joined to papers (structured fields + JSON blobs)
#   2. All catchall items for ingested samples
# Then merged in Python by display_name.

VALID_CATCHALL_TYPES = {
    "correlation",
    "additional_measurement",
    "anomalous_observation",
    "schema_candidate",
}

def fetch_corpus(types: Optional[List[str]] = None) -> List[dict]:
    """
    Return all ingested samples as self-contained corpus records.

    Each record contains:
      - All structured named columns (same as fetch_samples)
      - sample_json: full raw extracted JSON from Pass 2 (including unpromoted fields)
      - derived_json: all derived quantities as a dict
      - catchall: list of catchall items (filtered by types if specified)

    Args:
        types: list of catchall item_type values to include.
               Defaults to all four types if None or empty.
               Invalid types are silently ignored.

    Returns:
        List of sample dicts, ordered by film_material, display_name.
    """
    # Validate and normalise requested types
    if types:
        requested_types = [t for t in types if t in VALID_CATCHALL_TYPES]
    else:
        requested_types = list(VALID_CATCHALL_TYPES)

    conn = get_db()
    cur = conn.cursor()

    # ── Query 1: all samples with structured fields + JSON blobs ──────────
    numeric_cols      = ', '.join(f's.{f}' for f, _ in ALL_NUMERIC_FIELDS)
    profile_single_cols = ', '.join(f's.{f}' for f, _ in PROFILE_SINGLE_FIELDS)
    profile_list_cols   = ', '.join(f's.{f}' for f, _ in PROFILE_LIST_FIELDS)

    cur.execute(f"""
        SELECT
            s.display_name,
            s.sample_id,
            s.filename,
            s.film_material,
            s.film_crystal_phase,
            s.substrate_material,
            s.substrate_orientation,
            s.deposition_method,
            s.deposition_temperature_C,
            s.annealing_temperature_C,
            s.annealing_duration_s,
            s.junction_present,
            s.film_thickness_nm,
            s.Tc_confidence,
            s.RRR_confidence,
            s.Qi_confidence,
            s.T1_confidence,
            s.sample_json,
            s.derived_json,
            s.sim_profile_version,
            p.authors,
            p.title,
            p.doi,
            p.journal,
            p.human_reviewed,
            p.human_approved,
            {profile_single_cols},
            {profile_list_cols},
            {numeric_cols}
        FROM samples s
        JOIN papers p ON s.paper_id = p.id
        WHERE p.outcome = 'ingested'
        ORDER BY s.film_material, s.display_name
    """)

    rows = cur.fetchall()
    numeric_field_names = [f for f, _ in ALL_NUMERIC_FIELDS]

    # Build sample dicts, casting numeric columns to float where possible
    samples_by_name = {}
    for row in rows:
        d = dict(row)

        # Cast numeric fields
        for field in numeric_field_names:
            val = d.get(field)
            if val is not None:
                try:
                    d[field] = float(val)
                except (ValueError, TypeError):
                    d[field] = None

        # Parse JSON blobs into dicts (not raw strings)
        for blob_field in ('sample_json', 'derived_json'):
            raw = d.get(blob_field)
            if raw:
                try:
                    d[blob_field] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d[blob_field] = None

        # Parse similarity profile list fields
        for field, _ in PROFILE_LIST_FIELDS:
            d[field] = _parse_json_list(d.get(field))

        # Initialise empty catchall list — filled in Query 2
        d['catchall'] = []

        samples_by_name[d['display_name']] = d

    # ── Query 2: all catchall items for ingested samples ──────────────────
    # Filter by requested types using a parameterised IN clause
    placeholders = ','.join('?' * len(requested_types))
    cur.execute(f"""
        SELECT
            c.display_name,
            c.item_type,
            c.description,
            c.value,
            c.source,
            c.notes,
            c.sample_id
        FROM catchall_items c
        JOIN papers p ON c.paper_id = p.id
        WHERE p.outcome = 'ingested'
          AND c.item_type IN ({placeholders})
        ORDER BY c.display_name, c.item_type
    """, requested_types)

    catchall_rows = cur.fetchall()
    conn.close()

    # Merge catchall items into their parent sample records
    orphaned = 0
    for crow in catchall_rows:
        c = dict(crow)
        name = c.pop('display_name')
        if name in samples_by_name:
            samples_by_name[name]['catchall'].append(c)
        else:
            orphaned += 1

    if orphaned:
        # Log but don't fail — orphaned items indicate a display_name mismatch
        # between samples and catchall_items tables (shouldn't happen, but defensive)
        print(f"  fetch_corpus: {orphaned} catchall item(s) had no matching sample "
              f"(display_name mismatch) — excluded from output")

    return list(samples_by_name.values())


# ── Route to add in do_GET ─────────────────────────────────────────────────
#
# Add this block in the do_GET method, alongside the other /api/* routes:
#
#   elif path == "/api/corpus":
#       raw_types = params.get("types", "")
#       types = [t.strip() for t in raw_types.split(",") if t.strip()] or None
#       corpus = fetch_corpus(types=types)
#       self._json(200, {
#           "ok":           True,
#           "sample_count": len(corpus),
#           "types":        list(VALID_CATCHALL_TYPES) if not types else types,
#           "samples":      corpus,
#       })
