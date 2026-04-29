# Publications Ingester Module
## Specification Document v0.7

**Version:** 0.7 — Corpus Mining Pipeline, Schema Evolution Redesign, `/api/corpus` endpoint
**Date:** April 28, 2026
**Status:** Operational — 97 papers, 155 samples, ~1,318 catchall items, 100% profile coverage
**Context:** Component of the C2QA Materials Characterization Database effort

---

## Purpose

The Publications Ingester reads scientific papers and automatically extracts structured materials characterization data into a database. It sidesteps the central incentive problem of scientific data sharing — scientists already publish. By extracting data from publications, the database gets populated without asking anyone to fill out a form.

**Core value proposition:** submit your paper, get your data in the database automatically, with full citation credit. Records with device performance data (T1, T2, gate fidelity) can immediately populate QREM hardware profiles. The full corpus feeds the corpus mining pipeline, which extracts materials-to-device connection hypotheses.

---

## Code Structure

```
ingester/
  pipeline_ingest.py        — main loop: find PDFs, classify, extract, profile, write JSONL
  pipeline_mining.py        — corpus mining: Phase A (evidence) → B (reasoning) → C (write-up)
  prompts.py                — relevance check + extraction prompt (v3) + profile prompt
  processed_ledger.py       — DOI-primary / filename-fallback idempotency ledger
  build_sqlite.py           — loads JSONL into SQLite; derived quantities + similarity profile columns
  derive.py                 — deterministic derived quantities computed at build time
  backfill_similarity_profiles.py — Pass 3 backfill for existing records
  generate_qubit_profile.py — Hardware Profile Updater: generates QREM YAML from corpus sample
  serve_materials.py        — HTTP server: Materials Explorer + Ingestion Pipeline UI
  test_corpus_fetch.py      — test suite for /api/corpus endpoint
  materials_explorer.html   — Explorer UI: Explore / Search / Catchall tabs
  ingest_pipeline.html      — Pipeline UI: Stages 1-4 (ingest → dedup → build → mine)
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
    mining_evidence.jsonl   — Phase A output: evidence tables per hypothesis
    mining_corpus_gaps.jsonl — Phase A output: stated but unmeasurable hypotheses
    mining_out_of_scope.jsonl — Phase A output: device/circuit physics correlations
    mining_measurement_frequency.json — Phase A output: field frequency across corpus
    mining_reasoned.jsonl   — Phase B output: AI reasoning per hypothesis
    mining_findings.jsonl   — Phase C output: structured findings for human review
    mining_findings_report.md — Phase C output: human-readable markdown report
    findings.jsonl          — append-only approved findings ledger (source of truth)
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

Open `http://localhost:8001/ingest_pipeline.html` — four-stage UI:
1. **Ingest** — select papers directory, click Start, watch live progress log
2. **Review duplicates** — side-by-side comparison of potential duplicate pairs
3. **Build database** — one click; link to Materials Explorer appears on success
4. **Mine corpus** — run Phase A→B→C pipeline; review findings; approve/reject/send back

### Command Line

```bash
cd ingester
caffeinate python3 pipeline_ingest.py
python3 build_sqlite.py

# Mining pipeline
python3 pipeline_mining.py phase-a
python3 pipeline_mining.py phase-b
python3 pipeline_mining.py phase-c
```

### Resetting the Corpus

```bash
rm ../data/ingested/records.jsonl
rm ../data/ingested/processed_ledger.json
rm ../data/ingested/records.db
caffeinate python3 pipeline_ingest.py
```

Note: `findings.jsonl` (approved mining findings) is intentionally not reset with the corpus — it is an independent append-only ledger.

---

## Current Corpus State (April 28, 2026)

| Metric | Value |
|---|---|
| Papers processed | 97 |
| Papers ingested | ~56 |
| Papers skipped (not relevant) | ~41 (~44% skip rate) |
| Samples extracted | 155 |
| Catchall items | ~1,318 |
| Similarity profiles | 155 (100%) |
| Correlations in catchall | 41 |
| Mining findings produced | 3 |

**Named column coverage:** Tc 39%, RRR 20%, Qi 17%, T1 13%

Note: coverage reflects named column population only. Additional values exist in `additional_measurements` catchall for fields not yet promoted to named columns.

---

## Extraction Pipeline — Three-Pass Design

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
                  | — Catch-all: additional measurements, anomalies, correlations
                  |
             [PASS 3] SIMILARITY PROFILE  (~15-20 seconds)
                  | — 8-dimension semantic profile (see Schema Block 6)
                  | — Controlled vocabulary; keyed by sample_id
                  | — Non-fatal: failure writes empty profile, record still saved
                  |
             Record written to JSONL: human_reviewed: false, human_approved: false
```

PDFs are sent directly to Claude as base64. PDF-to-markdown conversion was rejected — it loses figure data, which is significant for materials papers.

Pass 3 failure is non-fatal — the record is always written. Profiles can be regenerated later via `backfill_similarity_profiles.py`.

---

## Corpus Mining Pipeline — Phase A → B → C

The corpus mining pipeline operates over all ingested records to extract materials-to-device connection hypotheses. It runs as Stage 4 of the ingestion pipeline UI.

```
[PHASE A] EVIDENCE EXTRACTION  (mechanical, no AI)
         | — Reads all correlation catchall items
         | — Maps descriptive terms to canonical field names (FIELD_MAP)
         | — Classifies: matched hypothesis / corpus gap / out of scope
         | — Scans corpus for cross-sample co-occurrence evidence
         | — Produces measurement frequency report
         | — Outputs: mining_evidence.jsonl, mining_corpus_gaps.jsonl,
         |            mining_out_of_scope.jsonl, mining_measurement_frequency.json
         |
[PHASE B] AI REASONING  (Claude, constrained to evidence table)
         | — Hypothesis, stated correlations, evidence records per call
         | — Cites specific samples; attempts self-falsification
         | — Chunked at 30 records; conservative merge (lowest confidence wins)
         | — Prior approved findings fed as context in subsequent runs
         | — Outputs: mining_reasoned.jsonl
         |
[PHASE C] AI WRITE-UP  (Claude)
         | — Structured human-reviewable finding per hypothesis
         | — Title, summary, supporting/complicating records,
         |   QREM implications, per-material recommendation,
         |   questions for reviewer
         | — Outputs: mining_findings.jsonl, mining_findings_report.md
         |
[HUMAN REVIEW]  (Stage 4 UI)
         | — Accept Finding / Send Back for Revision / Reject Finding
         | — Accept = finding is scientifically correct (including negative results)
         | — Approved findings → findings.jsonl (append-only)
```

### Current Mining Results (April 28)

Of 41 correlation items: 11 out of scope (device/circuit physics), 16 corpus gaps (unmappable or unmeasurable), 13 matched hypotheses. Only 3 hypotheses have ≥3 cross-sample evidence records — all produced negative or inconclusive findings, which is honest given current corpus coverage.

**Key insight from Phase B:** Cross-material hypothesis testing is confounded by material identity. Per-material-class analysis is the correct unit — Ta, Ta-Hf, NbSe2, NbN each have sufficient samples for focused analysis within-material. Future Phase A will build per-material-class evidence tables.

### Correlation Classification

Phase A classifies each correlation into one of three buckets:

**Matched hypothesis** — both measurement terms map to known field names, cross-sample evidence scan run.

**Corpus gap** — one or both terms are unmappable, or both map but no samples have both fields measured simultaneously. These document what we'd like to know but can't yet measure. Feeds schema promotion decisions.

**Out of scope** — device/circuit physics correlations with no materials characterization relevance (dispersive coupling, Bell fidelity, Rabi rates, etc.). Documented but not fed to Phase B.

### Schema Evolution via Measurement Frequency

Phase A produces a measurement frequency report: how often each term appears in `additional_measurements` across materials samples. Fields appearing in >5% of materials samples are schema promotion candidates.

**Current top candidates (confirmed via catchall value diagnostics):**

| Field | Frequency | Status |
|---|---|---|
| Sheet kinetic inductance | 49× | Promoted to schema v0.7 |
| Vortex activation temperature | 11× | Promoted to schema v0.7 |
| Mean free path | 9× | Promoted to schema v0.7 |

**Domain rule:** Only geometry-independent (intrinsic) material properties are promoted. Sheet Lk yes; total Lk no. Jc-material yes; Ic no.

**Promotion mechanics:** Values are already stored in `catchall_items.value` as clean numerics by Claude during Pass 2. Promotion adds a named column in `build_sqlite.py` reading from that field — no prompt changes, no re-ingestion required.

---

## Large PDF Handling

The API has a 32MB request size limit. Base64 encoding inflates file size by ~33%, so PDFs must be under ~24MB. Papers exceeding this receive `outcome: failed` with error `content_length_limit`.

**Workaround:** Compress with ghostscript at 150dpi:
```bash
gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -dNOPAUSE -dQUIET -dBATCH \
   -dColorImageResolution=150 -dGrayImageResolution=150 \
   -sOutputFile="compressed.pdf" "original.pdf"
```

Note: `/screen` and `/printer` presets may strip figures — use explicit DPI settings instead.

To reprocess a failed paper: remove its entry from `processed_ledger.json` and rerun.

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
| **Review paper** | No primary records. Paper queue for follow-up ingestion. |
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
| niobium diselenide | NbSe2 |
| platinum silicide | PtSi |

Crystal phase always goes in `film_crystal_phase`, never in `film_material`.

### Domain Knowledge Glossary

```
RRR → quasiparticle density → T1 relaxation time
Surface oxide thickness → TLS density → T2 dephasing and Qi
Loss budget decomposition (metal-air, metal-substrate, substrate-air) → dominant loss channel
Mean free path l vs coherence length ξ → clean vs dirty limit → dominant loss mechanism
  l > ξ (clean limit) → vortex motion dominant
  l < ξ (dirty limit) → different loss mechanisms
Kinetic inductance (sheet) → resonator frequency; superinductor applications
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
- Sheet kinetic inductance (per square, pH/sq) vs total kinetic inductance (pH) — always extract the per-square value

### Catchall Rules
- `suspected_relevance` must cite specific physics, not generic statements
- `correlations_observed` — author-stated only, never inferred from data
- No `schema_promotion_candidates` type — flag notable unmapped fields as `additional_measurement` with clear suspected_relevance; schema promotion is decided by corpus-wide frequency analysis, not per-paper judgment

---

## Similarity Profile Prompt (Pass 3)

Pass 3 sends Claude the completed PUK (all structured fields + full catchall) and asks it to generate an 8-dimension semantic profile using controlled vocabularies. One profile is generated per sample in the paper, keyed by `sample_id`. Full vocabulary defined in Schema Block 6.

**Profile dimensions:** `material_class`, `transport_regime`, `loss_mechanisms`, `device_type`, `coherence_tier`, `science_focus`, `growth_method`, `key_correlations`.

**Profile version:** `1.0` — bump when vocabulary changes. Use `backfill_similarity_profiles.py` to regenerate stale profiles across the corpus.

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

**Important:** The `catchall_items.value` field is already populated with clean numeric values by Claude during Pass 2 (e.g. "1.195 nH/sq", "109.3 ± 0.8 nm"). This enables schema promotion without re-ingestion — values are already extracted, just not in named columns.

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

**Planned:** `derived_material_Jc_A_m2` = Ic_film / (film_width × film_thickness); `derived_junction_Jc_uA_um2` = Ic_junction / junction_area_um2. Requires disambiguation of material vs junction Ic in extraction — see schema v0.7 Ic/Jc note.

**Important:** `derived_BCS_gap_meV` is computed deterministically from `Tc_K`. Any hypothesis involving both fields is therefore not testing an independent relationship. The corpus mining pipeline flags this explicitly in Phase B output.

---

## API Endpoints

Served by `serve_materials.py` at `localhost:8001`.

| Endpoint | Description |
|---|---|
| `GET /api/samples` | All samples with numeric + profile fields |
| `GET /api/fields` | Available numeric fields (only those with data) |
| `GET /api/catchall` | Catchall items, optionally filtered by type |
| `GET /api/corpus` | All samples as self-contained records: structured fields + sample_json + catchall (nested). Optional `?types=` filter on catchall types. |
| `GET /api/coverage` | Coverage summary |
| `GET /api/sample/{display_name}` | Full sample detail + catchall for slide-in panel |
| `GET /api/similar?display_name=...&n=12` | Hybrid similarity search |
| `GET /api/generate_profile?display_name=...&save=true` | Generate QREM qubit profile from corpus sample |
| `GET /api/mining/findings` | Load mining findings from mining_findings.jsonl |
| `GET /api/mining/status` | Poll mining pipeline progress |
| `POST /api/mining/run` | Start full Phase A→B→C pipeline |
| `POST /api/mining/approve` | Approve a finding → appended to findings.jsonl |
| `POST /api/mining/reject` | Reject a finding |
| `POST /api/mining/revise` | Mark finding for revision with notes |
| `POST /api/mining/reset` | Reset finding to pending |
| `POST /api/ingest/start` | Start ingestion run |
| `POST /api/build` | Run build_sqlite |
| `POST /api/duplicates/decide` | Record a duplicate decision |

### `/api/corpus` Design

Returns all ingested samples as self-contained records. Each record contains:
- All named column fields (same as `/api/samples`)
- `sample_json` — full raw Pass 2 extraction including unpromoted fields
- `derived_json` — all derived quantities as a parsed dict
- `catchall` — nested list of catchall items for this sample

Two SQL queries total (not N+1): samples then catchall, merged in Python by `display_name`. Validated with `test_corpus_fetch.py` — 10/10 tests passing.

---

## SQLite Database

Three tables. Derived from JSONL, rebuildable at any time — not a source of truth.

**`papers`** — one row per paper: outcome, DOI, title, authors, journal, sample count.

**`samples`** — one row per extracted sample: all schema fields, R vs T fields, derived quantities (prefixed `derived_`), similarity profile dimensions (prefixed `sim_`), `sample_json` blob, `display_name` = `{first_author}_{year}_{sample_id}`.

**`catchall_items`** — one row per catchall entry, with `display_name` for joining to samples.

---

## Materials Explorer UI

**Local:** `http://localhost:8001/materials_explorer.html`
**Hosted:** `https://c2qa-materials-explorer.onrender.com` (auto-deploys from GitHub main branch)

**Explore** — Strip plot and scatter plot, any measurement vs material category or pair. Sidebar filters by `material_class` from similarity profile. Click any point to open detail panel.

**Search** — Table, Ranked, and Similar sub-views. Similarity result cards show matched profile tags and numeric field chips.

**Catchall** — All catchall items filtered by type.

**Findings tab** — Planned. Read-only view of approved `findings.jsonl` on hosted Explorer. Updates on git push.

### Similarity Search

Hybrid scoring: 75% profile score (8 semantic dimensions) + 25% numeric score (z-score normalized field distance). Falls back gracefully to profile-only or numeric-only.

---

## The Catch-All as First-Class Output

| Type | Description | Count |
|---|---|---|
| `additional_measurement` | Measurement with no named schema field (includes former schema_candidate items) | ~1,209 |
| `anomalous_observation` | Unexpected result flagged by authors | ~68 |
| `correlation` | Author-stated materials-to-device connection | 41 |

The 41 author-stated correlations are peer-reviewed claims connecting material properties to device performance — the primary input to the corpus mining pipeline Phase A.

Note: `schema_candidate` type has been retired and merged into `additional_measurement`. Schema promotion is now driven by corpus-wide frequency analysis via the mining pipeline, not per-paper Claude judgment.

---

## Human Review

Review happens at two levels:

**Record-level review** (`human_reviewed`, `human_approved` flags) — individual extracted records. Flags are set in JSONL and projected to SQLite. Review UI planned as a future Explorer feature.

**Finding-level review** (Stage 4 of ingestion pipeline UI) — corpus mining findings. Three actions:
- **Accept Finding** — finding is scientifically correct, recorded in `findings.jsonl`
- **Send Back for Revision** — needs reconsideration; reviewer notes sent to next mining run as context
- **Reject Finding** — analysis is flawed, not recorded

Accepting a negative result is correct and encouraged — negative findings are real scientific results.

---

## Relevance Classification

**High — always ingest:** C2QA funding acknowledgment; Ta, Nb, Al, TiN, NbTiN, TaN, Re, NbN, NbSe2, PtSi materials; Josephson junction characterization; superconducting resonator loss studies.

**Medium — ingest material properties, flag application:** Superconducting materials in non-qubit applications; adjacent materials with potential qubit relevance.

**Low — skip:** Classical materials; superconducting power applications; high-Tc materials not relevant to quantum circuits; purely theoretical papers; quantum error correction / circuit-level papers with no materials content.

**Observed performance:** ~44% of corpus correctly skipped.

---

## Processed Papers Ledger

Fully idempotent. DOI is the primary key; filename is the fallback.

**Outcome values:** `ingested`, `skipped`, `failed`, `unknown`

Failed papers are logged but not blocked. Reprocess by removing the entry from `processed_ledger.json`.

---

## Deduplication

arXiv preprints and published versions matched by title similarity (≥ 0.85). Workflow:
1. Ingestion Pipeline UI shows potential duplicate pairs
2. Human decides: keep A, keep B, or not a duplicate
3. Decisions written to `deduplication.json`
4. `build_sqlite.py` excludes the losing paper from SQLite view

The JSONL retains both records — deduplication only affects the SQLite view.

---

## Hardware Profile Updater

`generate_qubit_profile.py` projects a corpus sample into a QREM qubit hardware profile YAML. Measured fields labeled `[MEASURED]`; unmeasured fields use defaults from `transmon_baseline_2026.yaml`, labeled `[ASSUMED]`. Full provenance block included.

Most materials papers measure T1 and T2 but not gate fidelity — profiles from such papers will have measured coherence but assumed gate parameters.

The current YAML approach is transitional. Target architecture: QREM queries the database directly, generating profiles in memory.

---

## Known Limitations

- Qi and T1 data in figures only may be missed or extracted at lower confidence
- Value confusion (Tc/Qi, Ic/Jc) observed — human review essential for medium-confidence extractions
- PDFs over ~24MB fail due to base64 encoding — compress with ghostscript at 150dpi
- arXiv/published version deduplication requires human review — titles can change dramatically
- Gate fidelity is rarely measured in materials papers — most qubit profiles will have assumed gate parameters
- Cross-material hypothesis testing is confounded by material identity — per-material-class analysis needed
- Similarity profile quality depends on Pass 2 extraction quality — sparse records get less informative profiles

---

## Relationship to QREM

**Direct path** — samples with measured T1, T2, gate fidelity, or inter-module link properties feed directly into QREM hardware profiles via the Hardware Profile Updater.

**Indirect path** — samples with only material properties (Tc, RRR, resistivity) feed the Materials Predictor and Mapping Layer (planned) to translate into QREM parameters.

**Mining path** — approved `findings.jsonl` entries become the initial entries in the QREM mapping layer, connecting material properties to device performance.

---

## Development Phases

| Phase | Status | Description |
|---|---|---|
| Phase 1 — Manual template | Skipped | — |
| Phase 2 — AI-assisted extraction | ✅ Complete | Three-pass pipeline, enriched prompt, Materials Explorer, derived quantities, deduplication, ingestion pipeline UI, Hardware Profile Updater, hybrid similarity search, `/api/corpus`, public hosting |
| Phase 3 — Corpus mining | ✅ Complete | Phase A→B→C pipeline, human review UI (Stage 4), `findings.jsonl` ledger, measurement frequency report, schema promotion mechanics |
| Phase 4 — Schema evolution UI | Next | Stage 4 sub-step surfaces promotion candidates from frequency report for human approval. Per-material-class Phase A analysis. |
| Phase 5 — Human review UI | Planned | Record-level review mechanism integrated into Explorer |
| Phase 6 — Active literature monitoring | Planned | Automated arXiv/journal monitoring; weekly human review queue |

---

*End of Specification v0.7*
*Updated April 28, 2026.*
