# Publications Ingester Module
## Specification Document v0.5

**Version:** 0.5 — Hardware Profile Updater, Ranked List tab, public Explorer, large PDF handling
**Date:** April 26, 2026
**Status:** Operational — 91 papers, 134 samples, ~1,200 catchall items
**Context:** Component of the C2QA Materials Characterization Database effort

---

## Purpose

The Publications Ingester reads scientific papers and automatically extracts structured materials characterization data into a database. It sidesteps the central incentive problem of scientific data sharing — scientists already publish. By extracting data from publications, the database gets populated without asking anyone to fill out a form.

**Core value proposition:** submit your paper, get your data in the database automatically, with full citation credit. Records with device performance data (T1, T2, gate fidelity) can immediately populate QREM hardware profiles.

---

## Code Structure

```
ingester/
  pipeline_ingest.py        — main loop: find PDFs, classify, extract, write JSONL
  prompts.py                — relevance check + extraction prompt (v3 enriched)
  processed_ledger.py       — DOI-primary / filename-fallback idempotency ledger
  build_sqlite.py           — loads JSONL into SQLite; deduplication and derived quantities
  derive.py                 — deterministic derived quantities computed at build time
  generate_qubit_profile.py — Hardware Profile Updater: generates QREM YAML from corpus sample
  serve_materials.py        — HTTP server: Materials Explorer + Ingestion Pipeline UI
  materials_explorer.html   — Explorer UI: strip plot, scatter, ranked list, data table, catchall
  ingest_pipeline.html      — Pipeline UI: ingest → deduplicate → build database
  config.py                 — Azure/Claude API configuration (env vars)
  openai_client.py          — provider abstraction (Azure Claude via Anthropic Foundry)
  io_jsonl.py               — append-only JSONL read/write utilities
  json_utils.py             — safe JSON serialization
  static/                   — static assets (C2QA logo)

data/
  papers/                   — drop PDFs here (subfolders supported, discovered recursively)
  ingested/
    records.jsonl           — append-only canonical ledger (source of truth)
    processed_ledger.json   — tracks processed papers (skip on re-run)
    deduplication.json      — human decisions on duplicate paper pairs
    records.db              — SQLite browse database (derived, rebuildable)
```

---

## Running the Pipeline

### Recommended: Ingestion Pipeline UI

```bash
cd ingester
export PROVIDER=claude
export AZURE_CLAUDE_API_KEY=your-key-here
python3 serve_materials.py
```

Open `http://localhost:8001/ingest_pipeline.html` — three-stage UI:
1. **Ingest** — select papers directory, click Start, watch live progress log
2. **Review duplicates** — side-by-side comparison of potential duplicate pairs
3. **Build database** — one click; link to Materials Explorer appears on success

### Command Line

```bash
cd ingester
caffeinate python3 pipeline_ingest.py
python3 build_sqlite.py
```

### Resetting the Corpus

```bash
rm ../data/ingested/records.jsonl
rm ../data/ingested/processed_ledger.json
rm ../data/ingested/records.db
caffeinate python3 pipeline_ingest.py
```

---

## Current Corpus State (April 26, 2026)

| Metric | Value |
|---|---|
| Papers processed | 91 |
| Papers ingested | ~51 |
| Papers skipped (not relevant) | ~40 (~44% skip rate) |
| Samples extracted | 134 |
| Catchall items | ~1,200 |

**Coverage:** Tc 56%, RRR 32%, Qi 19%, T1 12%

---

## Extraction Pipeline — Two-Pass Design

```
Input: PDF file
         |
    [PASS 1] RELEVANCE CHECK  (~15 seconds)
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

PDFs are sent directly to Claude as base64. PDF-to-markdown conversion was rejected — it loses figure data, which is significant for materials papers.

---

## Large PDF Handling

The API has a 32MB request size limit. Base64 encoding inflates file size by ~33%, so PDFs must be under ~24MB to process safely. Papers exceeding this limit receive `outcome: failed` with error `content_length_limit`.

**Workaround:** Compress with ghostscript at 150dpi — preserves figures while reducing file size:
```bash
gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -dNOPAUSE -dQUIET -dBATCH \
   -dColorImageResolution=150 -dGrayImageResolution=150 \
   -sOutputFile="compressed.pdf" "original.pdf"
```

**To reprocess a failed paper:** remove its entry from `processed_ledger.json` and rerun.

Note: `/screen` and `/printer` ghostscript presets may strip figures from some PDFs — use explicit DPI settings instead.

---

## Scope

**Always extracted:** Material properties, fabrication parameters, sample description.

**When present:** Qubit device performance (resonators, junctions, transmons).

**Always included regardless of device context:** Kinetic inductance, critical current density, film stoichiometry.

**Excluded:** Non-qubit device metrics (SNSPD, TWPA, accelerator cavity) — catchall only.

### Paper Types

| Type | Handling |
|---|---|
| **Primary research** | One record per sample. Highest-value input. |
| **Review paper** | No primary records. Schema evolution proposals + paper queue for follow-up ingestion. |
| **Process comparison** | Linked family of records varying fabrication parameters. Table-heavy papers are high-value. |

---

## Extraction Prompt — v3 Enriched

### Material Name Standardization

| Paper description | Extracted as |
|---|---|
| tantalum, Ta film | Ta |
| niobium, Nb film | Nb |
| niobium titanium nitride | NbTiN |
| tantalum nitride | TaN |
| rhenium, Re film | Re |
| Ta-Hf alloy (83% Ta, 17% Hf) | Ta-Hf (83:17) |

Crystal phase always goes in `film_crystal_phase`, never in `film_material`.

### Domain Knowledge Glossary

```
RRR → quasiparticle density → T1 relaxation time
Surface oxide thickness → TLS density → T2 dephasing and Qi
Loss budget decomposition (metal-air, metal-substrate, substrate-air) → dominant loss channel
xi < l (clean limit) → vortex motion is primary loss channel
Two-qubit gate fidelity → code distance → module count
  (99.5% → ~16 modules; 99.9% → ~2 modules for representative circuit)
T1 → decoherence-limited gate fidelity upper bound
  (actual fidelity also depends on control errors — T1 sets the ceiling, not the floor)
```

### R vs T Curve Extraction

When an R vs T curve or table is present, extract:
- `normal_state_resistance_Ohm`, `room_temperature_resistance_Ohm`
- `measured_structure_width_um`, `measured_structure_length_um`

These enable derivation of sheet resistance and RRR when not directly reported.

### Error Prevention Rules
- Tc and Qi confusion (similar numeric ranges in some papers)
- RRR is dimensionless — if units are reported it is a different quantity
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

`derive.py` computes deterministic quantities at SQLite build time — not during ingestion. The JSONL stays pure; new derivations can be added without re-ingesting.

| Derived quantity | Formula | Requires |
|---|---|---|
| `derived_resistivity_uOhm_cm` | Rs × t × 0.1 | sheet_resistance + film_thickness |
| `derived_BCS_gap_meV` | 1.764 × kB × Tc | Tc_K |
| `derived_coherence_length_nm` | sqrt(Φ0 / (2π × Hc2)) | upper_critical_field_T |
| `derived_kinetic_inductance_pH_sq` | ℏ × Rs / (π × Δ) | sheet_resistance + Tc |
| `derived_RRR_from_RvT` | R(300K) / R(Tc+) | room_temp_R + normal_state_R |
| `derived_sheet_resistance_Ohm_sq` | Rn × (width / length) | normal_state_R + geometry |

---

## Processed Papers Ledger

Fully idempotent. DOI is the primary key; filename is the fallback.

**Outcome values:** `ingested`, `skipped`, `failed`, `unknown`

Failed papers are logged but not blocked. Reprocess by removing the entry from `processed_ledger.json`.

---

## Deduplication

arXiv preprints and published versions cannot be matched by title similarity alone. Workflow:
1. Ingestion Pipeline UI shows potential duplicate pairs (title similarity ≥ 0.85)
2. Human decides: keep A, keep B, or not a duplicate
3. Decisions written to `deduplication.json`
4. `build_sqlite.py` excludes the losing paper from the SQLite view

The JSONL retains both records — deduplication only affects the SQLite view.

---

## SQLite Database

Three tables. Derived from JSONL, rebuildable at any time — not a source of truth.

**`papers`** — one row per paper: outcome, DOI, title, authors, journal, sample count.

**`samples`** — one row per extracted sample: all schema fields, R vs T fields, derived quantities (prefixed `derived_`), `display_name` = `{first_author}_{year}_{sample_id}`.

**`catchall_items`** — one row per catchall entry, with `display_name` for joining.

---

## Materials Explorer UI

**Local:** `http://localhost:8001/materials_explorer.html`
**Hosted:** `https://c2qa-materials-explorer.onrender.com` (auto-deploys from GitHub main branch)

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/samples` | All samples with numeric fields |
| `GET /api/fields` | Available numeric fields (only those with data) |
| `GET /api/catchall` | Catchall items, optionally filtered by type |
| `GET /api/coverage` | Coverage summary |
| `GET /api/sample/{display_name}` | Full sample detail + catchall for slide-in panel |
| `GET /api/generate_profile?display_name=...&save=true` | Generate QREM qubit profile from corpus sample |

### Five Tabs

**By Material** — strip/dot plot, any measurement vs material category, click to open detail panel.

**Scatter Plot** — any two continuous fields, colored by material/substrate/deposition method.

**Data Table** — all samples with key fields, confidence color-coded.

**Ranked List** — samples ranked best-to-worst for any selected property. Nulls skipped. Click any row to open detail panel.

**Catchall Corpus** — all catchall items filtered by type.

### Slide-In Detail Panel

Full sample record: description, reference with DOI link, all measurements with confidence, catchall items color-coded by type. Includes **"⚙ Generate Qubit Profile"** button — generates a QREM hardware profile YAML from this sample's data and saves it to `hardware_profiles/qubits/`, making it immediately available in the Baby QREM qubit dropdown.

---

## Hardware Profile Updater

`generate_qubit_profile.py` projects a corpus sample record into a QREM qubit hardware profile YAML.

**Field mapping:**
- Measured fields (T1, T2, gate fidelity, readout fidelity, gate times) → used directly, labeled `[MEASURED]`
- Unmeasured fields → defaults from `transmon_baseline_2026.yaml`, labeled `[ASSUMED]`
- Full provenance block: DOI, authors, film material, substrate, date generated, measured vs assumed field lists

**Usage:**
```bash
python3 generate_qubit_profile.py "Wang_2026_Transmon_1" --dry-run
```

**Architecture note:** The current YAML-based approach is a transitional step. The target architecture has QREM querying the database directly, generating profiles in memory without saving — the corpus record (PUK) remains the source of truth. The YAML button remains useful for manual generation and inspection.

---

## The Catch-All as First-Class Output

| Type | Description | Count |
|---|---|---|
| `additional_measurement` | Measurement with no schema field | ~800 |
| `schema_candidate` | Important parameter absent from schema | ~108 |
| `anomalous_observation` | Unexpected result flagged by authors | ~45 |
| `correlation` | Author-stated materials-to-device connection | ~31 |

The ~31 author-stated correlations are peer-reviewed claims connecting material properties to device performance — the primary evidence base for the QREM mapping layer.

---

## Human Review Philosophy

Review is **living**, not batch. Scientists encounter records needing attention through normal Explorer use. The `human_reviewed` and `human_approved` flags provide infrastructure for a review UI whose design should emerge from actual usage patterns.

---

## Relevance Classification

**High — always ingest:** C2QA funding acknowledgment; Ta, Nb, Al, TiN, NbTiN, TaN, Re, NbN, PtSi materials; Josephson junction characterization; superconducting resonator loss studies.

**Medium — ingest material properties, flag application:** Superconducting materials in non-qubit applications; adjacent materials with potential qubit relevance.

**Low — skip:** Classical materials; superconducting power applications; high-Tc materials not relevant to quantum circuits; purely theoretical papers.

**Observed performance:** ~44% of corpus correctly skipped.

---

## Known Limitations

- Qi and T1 data in figures only may be missed or extracted at lower confidence
- Value confusion (Tc/Qi) observed — human review essential for medium-confidence extractions
- PDFs over ~24MB fail due to base64 encoding inflating past the 32MB API limit — compress with ghostscript at 150dpi
- arXiv/published version deduplication requires human review — titles can change dramatically between preprint and publication
- Gate fidelity is rarely measured in materials papers — most qubit profiles will have assumed defaults for gate parameters

---

## Relationship to QREM

**Direct path** — samples with measured T1, T2, gate fidelity, or inter-module link properties feed directly into QREM hardware profiles via the Hardware Profile Updater. No predictor or mapping layer needed.

**Indirect path** — samples with only material properties (Tc, RRR, resistivity) will feed the Materials Predictor and Mapping Layer (planned) to translate into QREM parameters.

**Catchall mining** (Phase 3) — Claude analysis over ~31 author-stated correlations to extract and rank materials-to-device connections. These become the initial entries in the QREM mapping layer.

---

## Development Phases

| Phase | Status | Description |
|---|---|---|
| Phase 1 — Manual template | Skipped | — |
| Phase 2 — AI-assisted extraction | ✅ Complete | Two-pass pipeline, enriched prompt, Materials Explorer (strip plot, scatter, ranked list, data table, catchall), derived quantities, deduplication, ingestion pipeline UI, Hardware Profile Updater, public hosting on Render |
| Phase 3 — Catchall mining | Next | Claude analysis over catchall corpus; populate QREM mapping layer |
| Phase 4 — Human review UI | Planned | Review mechanism integrated into Explorer; design to emerge from usage |
| Phase 5 — Active literature monitoring | Planned | Automated arXiv/journal monitoring; weekly human review queue |

---

*End of Specification v0.5*
*Updated April 26, 2026.*
