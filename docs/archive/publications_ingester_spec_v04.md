# Publications Ingester Module
## Specification Document v0.4

**Version:** 0.4 — Derived quantities, deduplication, ingestion pipeline UI, R vs T extraction
**Date:** April 25, 2026
**Status:** Operational — 85+ records, 130 samples, 1169 catchall items
**Context:** Component of the C2QA Materials Characterization Database effort

---

## Purpose

The Publications Ingester reads scientific papers and automatically extracts structured materials characterization data into a database. It sidesteps the central incentive problem of scientific data sharing — scientists already publish. By extracting data from publications, the database gets populated without asking anyone to fill out a form.

**Core value proposition:** submit your paper, get your data in the database automatically, with full citation credit.

---

## Code Structure

```
ingester/
  pipeline_ingest.py      — main loop: find PDFs, classify, extract, write JSONL
  prompts.py              — relevance check + extraction prompt (v3 enriched)
  processed_ledger.py     — DOI-primary / filename-fallback idempotency ledger
  build_sqlite.py         — loads JSONL into SQLite; applies deduplication and derived quantities
  derive.py               — deterministic derived quantities computed from extracted fields
  serve_materials.py      — local HTTP server: Materials Explorer + Ingestion Pipeline UI
  materials_explorer.html — browser UI: strip plot, scatter, data table, catchall corpus
  ingest_pipeline.html    — browser UI: ingest → deduplicate → build database workflow
  config.py               — Azure/Claude API configuration (env vars)
  openai_client.py        — provider abstraction (Azure Claude via Anthropic Foundry)
  io_jsonl.py             — append-only JSONL read/write utilities
  json_utils.py           — safe JSON serialization

data/
  papers/                 — drop PDFs here (subfolders supported, discovered recursively)
  ingested/
    records.jsonl         — append-only canonical ledger (source of truth)
    processed_ledger.json — tracks processed papers (skip on re-run)
    deduplication.json    — human decisions on duplicate paper pairs
    records.db            — SQLite browse database (derived, rebuildable)
```

---

## Running the Pipeline

### Recommended: Ingestion Pipeline UI

Start the server (with API key set):

```bash
cd ingester
export PROVIDER=claude
export AZURE_CLAUDE_API_KEY=your-key-here
python3 serve_materials.py
```

Open `http://localhost:8001/ingest_pipeline.html` — a three-stage UI:

1. **Ingest** — select papers directory, click Start, watch live progress log
2. **Review duplicates** — side-by-side comparison of potential duplicate pairs; decide keep/not-a-duplicate for each
3. **Build database** — one click; on success, link to Materials Explorer appears

### Command Line (alternative)

```bash
cd ingester
caffeinate python3 pipeline_ingest.py   # ingest all PDFs in data/papers/
python3 build_sqlite.py                  # rebuild SQLite from JSONL
```

### Resetting the Corpus

```bash
rm ../data/ingested/records.jsonl
rm ../data/ingested/processed_ledger.json
rm ../data/ingested/records.db
caffeinate python3 pipeline_ingest.py
```

---

## Current Corpus State (April 25, 2026)

| Metric | Value |
|---|---|
| Papers processed | 85 |
| Papers ingested | ~50 |
| Papers skipped (not relevant) | ~35 (~44% skip rate) |
| Samples extracted | 130 |
| Catchall items | 1,169 |

**Coverage:** Tc 56%, RRR 32%, Qi 19%, T1 12%

```sql
-- Coverage query
SELECT
    COUNT(*) as total_samples,
    SUM(CASE WHEN Tc_K IS NOT NULL THEN 1 ELSE 0 END) as has_Tc,
    SUM(CASE WHEN RRR IS NOT NULL THEN 1 ELSE 0 END) as has_RRR,
    SUM(CASE WHEN Qi_internal IS NOT NULL THEN 1 ELSE 0 END) as has_Qi,
    SUM(CASE WHEN T1_us IS NOT NULL THEN 1 ELSE 0 END) as has_T1
FROM samples;
```

---

## Extraction Pipeline — Two-Pass Design

```
Input: PDF file
         |
    [PASS 1] RELEVANCE CHECK  (~15 seconds, cheap)
         | — Relevance: high / medium / low
         | — Paper type: primary / review / process_comparison
         | — DOI extraction
         |
         ├── LOW → log as skipped, write to JSONL, stop
         |
         └── HIGH or MEDIUM →
                  |
             [PASS 2] FULL EXTRACTION  (~60-90 seconds)
                  | — Sparse output: only fields present in the paper
                  | — Confidence + source reference for every field
                  | — Catch-all: additional measurements, anomalies,
                  |              correlations, schema candidates
                  |
             Record written to JSONL: human_reviewed: false, human_approved: false
```

PDFs are sent directly to Claude as base64 — text, tables, figures, and captions are all read in one pass. PDF-to-markdown conversion was considered and rejected: it loses figure data, which is significant for materials papers.

---

## Scope

**Always extracted:** Material properties, fabrication parameters, sample description.

**When present:** Qubit device performance (resonators, junctions, transmons).

**Always included regardless of device context:** Kinetic inductance, critical current density, film stoichiometry — these are material properties even in non-qubit papers.

**Excluded:** Non-qubit device performance metrics (SNSPD reset times, TWPA parameters, accelerator cavity performance) — these go to the catchall only, flagged.

### Paper Types

| Type | Handling |
|---|---|
| **Primary research** | One record per sample. Highest-value input. |
| **Review paper** | No primary records. Outputs: schema evolution proposals + primary paper queue for follow-up ingestion. |
| **Process comparison** | Linked family of records sharing provenance but varying fabrication parameters. Table-heavy papers are particularly high-value. |

---

## Extraction Prompt — v3 Enriched

### Material Name Standardization
Claude uses standard chemical abbreviations for `film_material`:

| Paper description | Extracted as |
|---|---|
| tantalum, Ta film | Ta |
| niobium, Nb film | Nb |
| niobium titanium nitride | NbTiN |
| tantalum nitride | TaN |
| Ta-Hf alloy (83% Ta, 17% Hf) | Ta-Hf (83:17) |

Crystal phase always goes in `film_crystal_phase`, never in `film_material` (e.g. alpha-Ta → `film_material: Ta`, `film_crystal_phase: alpha-Ta (bcc)`).

### Domain Knowledge Glossary
The prompt includes known materials-to-device connections to ground `suspected_relevance` entries:

```
RRR → quasiparticle density → T1 relaxation time
Surface oxide thickness → TLS density → T2 dephasing and Qi
xi < l (clean limit) → vortex motion is primary loss channel
xi > l (dirty limit) → different loss mechanisms dominate
Two-qubit gate fidelity → code distance → module count
  (99.5% → 16 modules; 99.9% → 2 modules for representative circuit)
```

### R vs T Curve Extraction
If an R vs T curve or table is present, the prompt extracts:

- `normal_state_resistance_Ohm` — resistance just above Tc
- `room_temperature_resistance_Ohm` — resistance at ~300K
- `measured_structure_width_um` — patterned structure width
- `measured_structure_length_um` — patterned structure length

These enable derivation of sheet resistance and RRR when not directly reported. The intrinsic properties (sheet resistance, resistivity) are what allow comparison across samples with different device geometries.

### Error Prevention Rules
- Tc and Qi confusion (similar numeric ranges in some papers)
- RRR is dimensionless — if units are present it is a different quantity
- T1 may be reported in ms — always convert to µs
- Qi vs Qc — internal vs coupling quality factor

### Catchall Rules
- `suspected_relevance` must cite specific physics, not generic statements
- `correlations_observed` — author-stated only, never inferred from data
- `schema_promotion_candidates` — explain specifically what would be lost without the field

---

## Sparse Output Design

Only fields actually present in the paper are included. Absence means not reported — never zero.

| Confidence | Meaning |
|---|---|
| `high` | Value from a structured table with explicit units |
| `medium` | Value from prose, clear unambiguous claim |
| `low` | Inferred or calculated from other reported values |
| `derived` | Computed by `derive.py` from other extracted fields |

Every field also carries a source reference: "Table I column 3", "Figure 3 caption", etc.

---

## Derived Quantities

`derive.py` computes deterministic derived quantities from extracted fields at SQLite build time — not during ingestion. This means:

- The JSONL stays pure (what papers report)
- New derivations can be added without re-ingesting the corpus
- Rebuilding SQLite takes seconds

**Rule:** If a paper already reports a quantity, the reported value is used. Derivation only happens when the quantity is not directly reported.

| Derived quantity | Formula | Requires |
|---|---|---|
| `derived_resistivity_uOhm_cm` | Rs × t × 0.1 | sheet_resistance + film_thickness |
| `derived_BCS_gap_meV` | 1.764 × kB × Tc | Tc_K |
| `derived_coherence_length_nm` | sqrt(Φ0 / (2π × Hc2)) | upper_critical_field_T |
| `derived_kinetic_inductance_pH_sq` | ℏ × Rs / (π × Δ) | sheet_resistance + Tc |
| `derived_RRR_from_RvT` | R(300K) / R(Tc+) | room_temp_R + normal_state_R |
| `derived_sheet_resistance_Ohm_sq` | Rn × (width / length) | normal_state_R + geometry |

All derived values include sanity bounds checking. Values outside physically reasonable ranges are flagged rather than silently used.

---

## Processed Papers Ledger

The ingester is fully idempotent. DOI is the primary key; filename is the fallback. Papers are recognized as already processed even if renamed.

**Outcome values:** `ingested`, `skipped`, `failed`

Failed papers are logged but not blocked. Reprocess by removing the entry from `processed_ledger.json` and rerunning.

---

## Deduplication

arXiv preprints and their published versions cannot be matched by title similarity alone — titles often change significantly between preprint and publication. The deduplication workflow:

1. After ingestion, the Ingestion Pipeline UI (Stage 2) shows potential duplicate pairs based on title similarity
2. Human reviews each pair and decides: keep A, keep B, or not a duplicate
3. Decisions are written to `data/ingested/deduplication.json`
4. `build_sqlite.py` reads this file and excludes the losing paper when building the database

The JSONL always retains both records — deduplication only affects the SQLite view.

---

## SQLite Database

`build_sqlite.py` projects the JSONL into three tables. The database is derived and rebuildable at any time — it is not a source of truth.

**`papers`** — one row per paper: outcome, DOI, title, authors, journal, sample count.

**`samples`** — one row per extracted sample. Key fields:
- `display_name` — `{first_author}_{year}_{sample_id}` (e.g. `Bahrami_2026_D1`)
- All structured schema fields (Tc_K, RRR, Qi_internal, T1_us, etc.)
- R vs T fields: `normal_state_resistance_Ohm`, `room_temperature_resistance_Ohm`, `measured_structure_width_um`, `measured_structure_length_um`
- Derived quantity columns (prefixed `derived_`)

**`catchall_items`** — one row per catchall entry, with `display_name` for joining.

---

## Materials Explorer UI

Served by `serve_materials.py` on port 8001. Open `http://localhost:8001/materials_explorer.html`.

**API endpoints:**
- `GET /api/samples` — all samples with numeric fields
- `GET /api/fields` — available numeric fields (only those with data in current corpus)
- `GET /api/catchall` — catchall items, optionally filtered by type
- `GET /api/coverage` — coverage summary
- `GET /api/sample/{display_name}` — full sample detail + catchall for slide-in panel

**Four tabs:**

**By Material** (default) — strip/dot plot. Y = any measurement, X = material categories with X+Y jitter to separate overlapping points. Tooltip shows single nearest point only. Click any point to open the slide-in detail panel.

**Scatter Plot** — any two continuous fields, colored by material/substrate/deposition method.

**Data Table** — all samples with key fields, confidence color-coded (green=high, blue=medium, orange=low).

**Catchall Corpus** — all catchall items filtered by type.

**Slide-in detail panel** — clicking any data point slides in a panel showing the full sample record: description, reference with DOI link, all measurements with confidence, all catchall items color-coded by type. Click outside to dismiss.

**Dropdowns** — dynamically populated from fields that have actual data in the corpus. Fields with zero values do not appear. As the schema grows, new fields appear automatically.

---

## The Catch-All as First-Class Output

The catchall is a primary scientific output, not a fallback.

| Type | Description | Count |
|---|---|---|
| `additional_measurement` | Measurement with no schema field | ~750 |
| `schema_candidate` | Important parameter absent from schema | ~108 |
| `anomalous_observation` | Unexpected result flagged by authors | ~45 |
| `correlation` | Author-stated materials-to-device connection | ~31 |

The 31 author-stated correlations are particularly valuable — they are peer-reviewed claims connecting material properties to device performance, forming the evidence base for the QREM mapping layer.

---

## Human Review Philosophy

Review is **living**, not batch. Scientists encounter records needing attention through normal Explorer use — spotting an outlier on the strip plot, noticing their own paper's data looks wrong, seeing a material name that doesn't match. The `human_reviewed` and `human_approved` flags provide infrastructure for a review UI whose design should emerge from actual usage patterns, not be designed in the abstract.

---

## Relevance Classification

**High — always ingest:** C2QA funding acknowledgment; Ta, Nb, Al, TiN, NbTiN, TaN, PtSi, Re, NbN materials; Josephson junction characterization; superconducting resonator loss studies.

**Medium — ingest material properties, flag application:** Superconducting materials in non-qubit applications (SNSPDs, accelerator cavities); adjacent materials with potential qubit relevance.

**Low — skip:** Classical materials; superconducting power applications; high-Tc superconductors not relevant to quantum circuits; purely theoretical papers.

**Observed performance:** ~44% of corpus correctly skipped as not relevant.

---

## Known Limitations

- Qi and T1 data reported only in figures may be missed or extracted at lower confidence
- Value confusion (Tc/Qi) has been observed — human review essential for medium-confidence extractions; prompt includes explicit warnings
- Large PDFs (>5MB) may take 2-3 minutes for Pass 2
- arXiv/published version deduplication requires human review — title changes between preprint and publication can be dramatic

---

## Relationship to QREM

The ingester feeds the QREM pipeline two ways:

**Direct path** — samples with measured T1, T2, gate fidelity, or inter-module link properties can feed directly into a QREM hardware profile without going through the predictor or mapping layer.

**Indirect path** — samples with only material properties (Tc, RRR, resistivity) feed the Materials Predictor and Mapping Layer, which translate them into QREM hardware profile parameters.

**Catchall mining** (planned) — run Claude analysis over the ~31 author-stated correlations and ~750 additional measurements to extract materials-to-device connections, ranked by how many papers support each one. These become the initial entries in the QREM mapping layer.

---

## Development Phases

| Phase | Status | Description |
|---|---|---|
| Phase 1 — Manual template | Skipped | — |
| Phase 2 — AI-assisted extraction | ✅ Complete | Two-pass pipeline, enriched prompt, Materials Explorer, derived quantities, deduplication, ingestion pipeline UI |
| Phase 3 — Catchall mining | Next | Claude analysis over catchall corpus; populate QREM mapping layer |
| Phase 4 — Human review UI | Planned | Review mechanism integrated into Explorer; design to emerge from usage |
| Phase 5 — Active literature monitoring | Planned | Automated arXiv/journal monitoring; weekly human review queue |

---

*End of Specification v0.4*
*Original document produced April 2026. Updated and streamlined April 25, 2026.*
