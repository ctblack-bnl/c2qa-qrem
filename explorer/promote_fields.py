#!/usr/bin/env python3
# ingester/promote_fields.py  —  Schema Promotion Pipeline
#
# Promotes catchall measurements into named columns in the SQLite database,
# then automatically patches pipeline_mining.py so Phase A immediately
# recognises the new columns without any manual edits.
#
# For each promotion candidate:
#   1. Finds matching catchall_items rows by description pattern
#   2. Calls Claude to extract a clean float in canonical units
#   3. ALTERs the samples table to add the column if it doesn't exist
#   4. UPDATEs samples rows with the extracted value
#   5. Patches pipeline_mining.py:
#        a. FIELD_MAP  — strips json: prefix from any entry pointing to the column
#        b. NAMED_COLUMNS  — adds column name to the set
#        c. SELECT query in load_corpus  — adds column to the SQL SELECT
#        d. NUMERIC_FIELDS list  — adds column so it is cast to float on load
#
# The JSONL ledger is never touched. Promoted columns are SQLite-only
# derived projections. Running build_sqlite.py again will DROP promoted columns
# (since it drops and recreates tables) — always re-run promote_fields.py
# after a rebuild.
#
# Usage:
#   cd ingester
#   python3 promote_fields.py                             # promote all defined fields
#   python3 promote_fields.py --field mean_free_path_nm   # promote one field
#   python3 promote_fields.py --dry-run                   # preview, no writes
#   python3 promote_fields.py --skip-patch                # skip pipeline_mining.py patch
#   python3 promote_fields.py --db ../data/ingested/records.db
#
# Adding a new promotion candidate:
#   Add one entry to PROMOTION_FIELDS below. No other code changes needed.

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

# ── Promotion field definitions ───────────────────────────────────────────────
#
# To promote a new field: add one dict here. That's it.
# Claude handles all unit conversion and format parsing.
# pipeline_mining.py is patched automatically after each promotion.
#
PROMOTION_FIELDS = [
    {
        "column":              "kinetic_inductance_sheet_pH_sq",
        "description_pattern": "%Sheet kinetic inductance%",
        "canonical_units":     "pH/sq (picohenries per square)",
        "notes": (
            "Sheet kinetic inductance (geometry-independent). "
            "Values may be reported in nH/sq — convert to pH/sq (1 nH/sq = 1000 pH/sq). "
            "Return only the sheet (per-square) value, never total Lk."
        ),
    },
    {
        "column":              "mean_free_path_nm",
        "description_pattern": "%mean free path%",
        "canonical_units":     "nm (nanometres)",
        "notes": (
            "Electron mean free path in the superconducting film. "
            "Values reported as ranges (e.g. '0.03 - 0.5 nm') are not clean single "
            "measurements — return null for ranges. "
            "Values with uncertainty (e.g. '142.3 ± 0.2 nm') — return the central value only."
        ),
    },
    {
        "column":              "vortex_activation_temperature_K",
        "description_pattern": "%vortex activation%",
        "canonical_units":     "K (kelvin)",
        "notes": (
            "Vortex activation temperature (Tact), characterising the vortex motion "
            "loss channel. Values with uncertainty (e.g. '0.54 ± 0.04 K') — "
            "return the central value only."
        ),
    },
]

# ── Claude extraction prompt ──────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a precise scientific data extraction assistant.
You extract single numeric values from free-text measurement strings reported
in materials science papers. You always respond with valid JSON only."""

def build_extraction_prompt(raw_value: str, canonical_units: str,
                             field_notes: str) -> str:
    return f"""Extract a single numeric value from this materials measurement string.

Raw value string: "{raw_value}"

Target units: {canonical_units}

Field-specific notes: {field_notes}

Rules:
- Return the numeric value converted to the target units as a float
- If the value has uncertainty (e.g. "142.3 ± 0.2 nm"), return only the central value (142.3)
- If the value is a range (e.g. "0.03 - 0.5 nm"), return null — not a single measurement
- If the string is descriptive text with no extractable number, return null
- If units differ from target, convert (e.g. nH/sq → pH/sq: multiply by 1000)
- If the string contains multiple values for different conditions, return null

Respond with JSON only, exactly this structure:
{{"value": <float or null>, "reasoning": "<one sentence explaining your extraction>"}}"""


# ── AI client ─────────────────────────────────────────────────────────────────

def _import_ai_client():
    """Import the AI client using the same pattern as the rest of the ingester."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from openai_client import make_client
        from config import get_deployment_name
        client     = make_client(timeout=60.0)
        deployment = get_deployment_name()
        return client, deployment
    except ImportError as e:
        print(f"[ERROR] Could not import AI client: {e}")
        print("Make sure openai_client.py and config.py are in the ingester directory.")
        raise


def extract_value(client, deployment: str,
                  raw_value: str, field_def: dict) -> tuple[Optional[float], str]:
    """
    Call Claude to extract a clean float from a raw catchall value string.
    Returns (float_or_none, reasoning_string).
    """
    prompt = build_extraction_prompt(
        raw_value=raw_value,
        canonical_units=field_def["canonical_units"],
        field_notes=field_def.get("notes", ""),
    )
    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            max_completion_tokens=200,
        )
        raw = (response.choices[0].message.content or "").strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )

        parsed    = json.loads(raw)
        value     = parsed.get("value")
        reasoning = parsed.get("reasoning", "")

        if value is not None:
            value = float(value)

        return value, reasoning

    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"
    except Exception as e:
        return None, f"API error: {e}"


# ── Database helpers ──────────────────────────────────────────────────────────

def ensure_column_exists(conn: sqlite3.Connection, column: str) -> bool:
    """
    Add column to samples table if it doesn't already exist.
    Returns True if column was added, False if it already existed.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(samples)")
    existing = {row[1] for row in cur.fetchall()}
    if column in existing:
        return False
    cur.execute(f"ALTER TABLE samples ADD COLUMN {column} REAL")
    conn.commit()
    return True


def fetch_catchall_rows(conn: sqlite3.Connection,
                         description_pattern: str) -> list[dict]:
    """
    Fetch all additional_measurement catchall rows matching the description pattern.
    Returns list of dicts with display_name, value, description, notes.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT display_name, value, description, notes
        FROM catchall_items
        WHERE item_type = 'additional_measurement'
          AND description LIKE ?
          AND value IS NOT NULL
          AND value != ''
        ORDER BY display_name
    """, (description_pattern,))
    return [
        {
            "display_name": row[0],
            "value":        row[1],
            "description":  row[2],
            "notes":        row[3],
        }
        for row in cur.fetchall()
    ]


def update_sample_field(conn: sqlite3.Connection,
                         display_name: str, column: str,
                         value: float) -> None:
    """Write extracted value to named column for a sample."""
    cur = conn.cursor()
    cur.execute(
        f"UPDATE samples SET {column} = ? WHERE display_name = ?",
        (value, display_name),
    )


# ── pipeline_mining.py patcher ────────────────────────────────────────────────

def patch_pipeline_mining(column: str,
                            mining_path: Path,
                            dry_run: bool = False) -> dict:
    """
    Patch pipeline_mining.py to recognise a newly promoted column.

    Four locations are updated:
      1. FIELD_MAP  — any entry pointing to "json:<column>" → bare column name
      2. NAMED_COLUMNS  — column added to the set if not already present
      3. SELECT in load_corpus  — column added after the last promoted column
      4. NUMERIC_FIELDS in load_corpus  — column added to the list

    Writes a .bak backup before modifying. Idempotent — safe to re-run.
    Returns a dict describing what was changed.
    """
    if not mining_path.exists():
        return {"error": f"{mining_path} not found — skipping patch"}

    src      = mining_path.read_text(encoding="utf-8")
    original = src
    changes  = []

    # ── 1. FIELD_MAP: strip json: prefix ─────────────────────────────────
    json_ref = f'"json:{column}"'
    bare_ref = f'"{column}"'
    if json_ref in src:
        src = src.replace(json_ref, bare_ref)
        changes.append(f"FIELD_MAP: replaced {json_ref} → {bare_ref}")

    # ── 2. NAMED_COLUMNS: add column to set ──────────────────────────────
    # Check if already present (idempotent)
    if f'"{column}"' not in src.split("NAMED_COLUMNS")[1].split("}")[0]:
        # Insert after "derived_sheet_resistance_Ohm_sq" in NAMED_COLUMNS block
        # We find the closing brace of NAMED_COLUMNS and insert before the last entry
        anchor = '"derived_sheet_resistance_Ohm_sq",'
        # Count occurrences — NAMED_COLUMNS is the first occurrence
        idx = src.find("NAMED_COLUMNS")
        block_start = src.find(anchor, idx)
        if block_start != -1:
            # Find end of this line
            line_end = src.find("\n", block_start)
            src = src[:line_end + 1] + f'    "{column}",\n' + src[line_end + 1:]
            changes.append(f'NAMED_COLUMNS: added "{column}"')
        else:
            changes.append("NAMED_COLUMNS: anchor not found — manual edit needed")

    # ── 3. SELECT query: add column ───────────────────────────────────────
    select_entry = f"            s.{column},"
    if select_entry not in src:
        # Find the SELECT block in load_corpus and insert after the last
        # known promoted column (or after derived_sheet_resistance_Ohm_sq)
        # Strategy: find all promoted column SELECT lines and insert after the last
        promoted_cols = [f["column"] for f in PROMOTION_FIELDS]
        lines = src.split("\n")

        # Find the SELECT block: starts after "cur.execute(", ends at "FROM samples"
        in_select = False
        last_select_promoted_idx = None
        select_anchor_idx = None

        for i, line in enumerate(lines):
            if 'cur.execute("""' in line and "SELECT" not in line:
                # Wait for actual SELECT
                pass
            if "SELECT" in line and "cur.execute" not in line and in_select is False:
                in_select = True
            if in_select and "s.derived_sheet_resistance_Ohm_sq," in line:
                select_anchor_idx = i
                last_select_promoted_idx = i
            if in_select and select_anchor_idx is not None:
                for pc in promoted_cols:
                    if f"s.{pc}," in line:
                        last_select_promoted_idx = i
            if in_select and "p.authors" in line:
                break

        if last_select_promoted_idx is not None:
            lines.insert(last_select_promoted_idx + 1, f"            s.{column},")
            src = "\n".join(lines)
            changes.append(f"SELECT: added s.{column}")
        else:
            changes.append("SELECT: insertion point not found — manual edit needed")

    # ── 4. NUMERIC_FIELDS: add column to list ────────────────────────────
    # Check within NUMERIC_FIELDS block only
    numeric_entry = f'"{column}"'
    numeric_block_start = src.find("NUMERIC_FIELDS")
    numeric_block_end   = src.find("]", numeric_block_start)
    numeric_block       = src[numeric_block_start:numeric_block_end]

    if numeric_entry not in numeric_block:
        # Find insertion point: after last promoted column or after
        # derived_sheet_resistance_Ohm_sq in NUMERIC_FIELDS
        promoted_cols = [f["column"] for f in PROMOTION_FIELDS]
        lines = src.split("\n")

        in_numeric    = False
        last_idx      = None
        numeric_start = None

        for i, line in enumerate(lines):
            if "NUMERIC_FIELDS" in line and "=" in line:
                in_numeric    = True
                numeric_start = i
            if in_numeric and '"derived_sheet_resistance_Ohm_sq"' in line:
                last_idx = i
            if in_numeric and last_idx is not None:
                for pc in promoted_cols:
                    if f'"{pc}"' in line:
                        last_idx = i
            if in_numeric and numeric_start is not None and "]" in line and i > numeric_start:
                break

        if last_idx is not None:
            lines.insert(last_idx + 1, f'        "{column}",')
            src = "\n".join(lines)
            changes.append(f'NUMERIC_FIELDS: added "{column}"')
        else:
            changes.append("NUMERIC_FIELDS: insertion point not found — manual edit needed")

    # ── Write if changed ──────────────────────────────────────────────────
    if src == original:
        return {"column": column, "changes": [], "note": "already up to date"}

    if not dry_run:
        backup = mining_path.with_suffix(".py.bak")
        backup.write_text(original, encoding="utf-8")
        mining_path.write_text(src, encoding="utf-8")

    return {
        "column":  column,
        "changes": changes,
        "dry_run": dry_run,
        "backup":  str(mining_path.with_suffix(".py.bak")) if not dry_run else None,
    }


# ── Main promotion logic ──────────────────────────────────────────────────────

def promote_field(conn: sqlite3.Connection,
                   client, deployment: str,
                   field_def: dict,
                   dry_run: bool = False,
                   verbose: bool = False) -> dict:
    """
    Promote one field from catchall into a named samples column.
    Returns a summary dict of results.
    """
    column  = field_def["column"]
    pattern = field_def["description_pattern"]

    print(f"\n{'─'*60}")
    print(f"Promoting: {column}")
    print(f"  Pattern : {pattern}")
    print(f"  Units   : {field_def['canonical_units']}")

    # Ensure column exists in DB
    if not dry_run:
        added = ensure_column_exists(conn, column)
        if added:
            print(f"  Column  : created in samples table")
        else:
            print(f"  Column  : already exists — will overwrite non-null values")

    # Fetch matching catchall rows
    rows = fetch_catchall_rows(conn, pattern)
    print(f"  Rows    : {len(rows)} catchall entries matched")

    if not rows:
        print(f"  ⚠ No matching catchall rows found — check description_pattern")
        return {"column": column, "matched": 0, "extracted": 0, "null": 0, "errors": 0}

    results = {
        "column":    column,
        "matched":   len(rows),
        "extracted": 0,
        "null":      0,
        "errors":    0,
        "rows":      [],
    }

    for i, row in enumerate(rows, 1):
        display_name = row["display_name"]
        raw_value    = row["value"]

        if verbose:
            print(f"  [{i}/{len(rows)}] {display_name}: \"{raw_value}\"", end=" → ")

        value, reasoning = extract_value(client, deployment, raw_value, field_def)

        if verbose:
            if value is not None:
                print(f"{value} ({reasoning})")
            else:
                print(f"null ({reasoning})")
        elif i % 5 == 0 or i == len(rows):
            print(f"  [{i}/{len(rows)}] processed...", end="\r")

        row_result = {
            "display_name": display_name,
            "raw_value":    raw_value,
            "extracted":    value,
            "reasoning":    reasoning,
        }
        results["rows"].append(row_result)

        if value is not None:
            results["extracted"] += 1
            if not dry_run:
                update_sample_field(conn, display_name, column, value)
        elif "error" in reasoning.lower():
            results["errors"] += 1
        else:
            results["null"] += 1

        time.sleep(0.3)

    if not dry_run:
        conn.commit()

    print(f"\n  Results : {results['extracted']} extracted, "
          f"{results['null']} null, {results['errors']} errors"
          + (" [DRY RUN — no writes]" if dry_run else " [written to DB]"))

    return results


def run_promotion(db_path: Path,
                   field_names: Optional[list[str]] = None,
                   dry_run: bool = False,
                   verbose: bool = False,
                   skip_patch: bool = False) -> None:
    """
    Main entry point. Promotes all defined fields (or a subset by name),
    then patches pipeline_mining.py to recognise the new columns.
    """
    print("=" * 60)
    print("Schema Promotion Pipeline")
    print("=" * 60)
    if dry_run:
        print("⚠ DRY RUN — no database writes or file patches will be made")

    # Select fields to promote
    fields_to_run = PROMOTION_FIELDS
    if field_names:
        fields_to_run = [
            f for f in PROMOTION_FIELDS
            if f["column"] in field_names
        ]
        missing = set(field_names) - {f["column"] for f in fields_to_run}
        if missing:
            print(f"\n[ERROR] Unknown field(s): {missing}")
            print(f"Defined fields: {[f['column'] for f in PROMOTION_FIELDS]}")
            sys.exit(1)

    print(f"\nFields to promote: {len(fields_to_run)}")
    for f in fields_to_run:
        print(f"  {f['column']}")

    if not db_path.exists():
        print(f"\n[ERROR] Database not found: {db_path}")
        print("Run build_sqlite.py first.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)

    # Locate pipeline_mining.py (sibling file)
    mining_path = Path(__file__).resolve().parent / "pipeline_mining.py"

    print(f"\nInitialising AI client...")
    try:
        client, deployment = _import_ai_client()
        print(f"  Deployment: {deployment}")
    except Exception as e:
        print(f"[ERROR] Could not initialise AI client: {e}")
        conn.close()
        sys.exit(1)

    all_results = []
    all_patches = []

    for field_def in fields_to_run:
        # 1. Promote values into SQLite
        result = promote_field(
            conn=conn,
            client=client,
            deployment=deployment,
            field_def=field_def,
            dry_run=dry_run,
            verbose=verbose,
        )
        all_results.append(result)

        # 2. Patch pipeline_mining.py
        if not skip_patch:
            patch_result = patch_pipeline_mining(
                column=field_def["column"],
                mining_path=mining_path,
                dry_run=dry_run,
            )
            all_patches.append(patch_result)

    conn.close()

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Promotion Summary")
    print(f"{'='*60}")
    total_matched   = sum(r["matched"]   for r in all_results)
    total_extracted = sum(r["extracted"] for r in all_results)
    total_null      = sum(r["null"]      for r in all_results)
    total_errors    = sum(r["errors"]    for r in all_results)

    for r in all_results:
        status = "✓" if r["extracted"] > 0 else "⚠"
        print(f"  {status} {r['column']:<45} "
              f"{r['extracted']:>3} extracted / {r['matched']:>3} matched")

    print(f"\n  Total matched   : {total_matched}")
    print(f"  Total extracted : {total_extracted}")
    print(f"  Total null      : {total_null}")
    print(f"  Total errors    : {total_errors}")

    # ── Patch summary ─────────────────────────────────────────────────────
    if all_patches:
        print(f"\n{'─'*60}")
        print(f"pipeline_mining.py patches")
        print(f"{'─'*60}")
        any_changes = False
        for p in all_patches:
            if p.get("error"):
                print(f"  ⚠ {p['column']}: {p['error']}")
            elif not p.get("changes"):
                print(f"  ✓ {p['column']}: already up to date")
            else:
                any_changes = True
                print(f"  ✓ {p['column']}:")
                for change in p["changes"]:
                    print(f"      {change}")
        if any_changes and not dry_run:
            print(f"\n  Backup written : pipeline_mining.py.bak")
            print(f"  Verify with   : grep -n '<column>' pipeline_mining.py")

    if dry_run:
        print(f"\n  DRY RUN complete — re-run without --dry-run to write")
    else:
        print(f"\n  ✓ Promotion complete")
        print(f"  Next step: re-run Phase A mining")
        print(f"    python3 pipeline_mining.py phase-a")

    # Print null/error rows
    problem_rows = [
        row for r in all_results
        for row in r.get("rows", [])
        if row["extracted"] is None
    ]
    if problem_rows and verbose:
        print(f"\n{'─'*60}")
        print(f"Null/error rows ({len(problem_rows)}):")
        for row in problem_rows:
            print(f"  {row['display_name']}: \"{row['raw_value']}\"")
            print(f"    Reason: {row['reasoning']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Promote catchall measurements into named SQLite columns "
            "and patch pipeline_mining.py to recognise them."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("../data/ingested/records.db"),
        help="SQLite database path (default: ../data/ingested/records.db)",
    )
    parser.add_argument(
        "--field",
        action="append",
        dest="fields",
        metavar="COLUMN_NAME",
        help=(
            "Promote only this field (column name). "
            "Can be specified multiple times. "
            "Default: promote all defined fields."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview extraction results and patches without writing anything.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print each row's raw value, extracted value, and reasoning.",
    )
    parser.add_argument(
        "--skip-patch",
        action="store_true",
        help="Skip patching pipeline_mining.py (database writes still happen).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all defined promotion fields and exit.",
    )

    args = parser.parse_args()

    if args.list:
        print("Defined promotion fields:")
        for f in PROMOTION_FIELDS:
            print(f"  {f['column']}")
            print(f"    Pattern : {f['description_pattern']}")
            print(f"    Units   : {f['canonical_units']}")
        return

    run_promotion(
        db_path=args.db,
        field_names=args.fields,
        dry_run=args.dry_run,
        verbose=args.verbose,
        skip_patch=args.skip_patch,
    )


if __name__ == "__main__":
    main()
