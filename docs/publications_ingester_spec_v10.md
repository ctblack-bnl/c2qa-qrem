# Publications Ingester Module
**Version:** 0.10 — derived_tan_delta; Explorer dropdown rationalization; manual exclusions; resistivity fallback (May 19)
**Date:** May 19, 2026
**Status:** Operational — 221 samples (after 3 exclusions), 100% profile coverage. See Explorer for live corpus counts.
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
  build_sqlite.py           — loads JSONL into SQLite; derived quantities, similarity profile,
                              derived_material columns; unrecognized materials warning
  derive.py                 — deterministic derived quantities computed at build time
  backfill_similarity_profiles.py — Pass 3 backfill; --filter flag for targeted reprocessing
  generate_qubit_profile.py — Hardware Profile Updater: generates QREM YAML from corpus sample
  serve_materials.py        — HTTP server: Materials Explorer + Ingestion Pipeline UI
  materials_explorer.html   — Explorer UI: Explore / Search / Findings / Catchall tabs
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
    exclusions.json         — manual post-hoc exclusions (JSONL never modified)
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
3. **Build database** — one click; shows ⚠ warning for unrecognized film materials; link to Explorer on success
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

# Backfill similarity profiles (targeted reprocessing)
python3 backfill_similarity_profiles.py --filter Zaman --dry-run
python3 backfill_similarity_profiles.py --filter Zaman

# IMPORTANT: always check line counts before swapping backfill output
wc -l ../data/ingested/records_with_profiles.jsonl
wc -l ../data/ingested/records.jsonl
# Only swap if counts match:
mv ../data/ingested/records.jsonl ../data/ingested/records_backup.jsonl
mv ../data/ingested/records_with_profiles.jsonl ../data/ingested/records.jsonl
python3 build_sqlite.py

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

Pass 3 failure is non-fatal — the record is always written. Profiles can be regenerated via `backfill_similarity_profiles.py --filter <pattern>`.

**Known Pass 3 issue:** The profile prompt receives sample fields as nested confidence/source dicts (e.g. `{"value": "NbSe2", "confidence": "high", "source": "..."}`) which Claude sees rather than plain values. A `_flatten_sample_for_profile()` function in `prompts.py` now flattens these before sending to Claude. Despite this, `sim_material_class` assignment for less common materials (NbSe2, PtSi) can be unreliable. This is a cosmetic issue for the Explorer sidebar — it does not affect mining correctness, which uses `derived_material` instead.

---

## Corpus Mining Pipeline — Phase A → B → C

The corpus mining pipeline operates over all ingested records to extract materials-to-device connection hypotheses. It runs as Stage 4 of the ingestion pipeline UI.

```
[PHASE A] EVIDENCE EXTRACTION  (mechanical, no AI)
         | — Reads all correlation catchall items
         | — Maps descriptive terms to canonical field names (FIELD_MAP)
         | — Classifies: matched hypothesis / corpus gap / out of scope
         | — Scans corpus for co-occurrence evidence — BOTH:
         |     global tables (all materials, cross-corpus view)
         |     per-material tables (stratified by derived_material)
         | — "other" class tables written to JSONL but never sent to Phase B
         | — Produces measurement frequency report
         |
[PHASE B] AI REASONING  (Claude, constrained to evidence table)
         | — One API call per sufficient evidence table (≥3 samples)
         | — Cites specific samples; attempts self-falsification
         | — Chunked at 30 records; conservative merge (lowest confidence wins)
         | — Prior approved findings fed as context
         |
[PHASE C] AI WRITE-UP  (Claude)
         | — Structured human-reviewable finding per hypothesis
         | — Title, summary, finding detail, supporting/complicating records,
         |   QREM implications, per-material recommendation,
         |   questions for reviewer
         |
[HUMAN REVIEW]  (Stage 4 UI)
         | — Accept / Send Back for Revision / Reject
         | — Accept = finding is scientifically correct (including negative results)
         | — Approved findings → findings.jsonl (append-only)
```

### Per-Material-Class Stratification (implemented May 5)

Phase A produces evidence tables at two stratification levels:
- **Global** (`stratification: "global"`) — all materials combined. Retains cross-corpus view; useful when the same fabrication parameter affects multiple material classes.
- **Per-material** (`stratification: "tantalum"` etc.) — within a single material class. Correct scientific unit for most materials-to-device hypotheses, since cross-material comparisons are confounded by material identity.

The `derived_material` column drives stratification — not `sim_material_class`. This is intentional: `derived_material` is deterministic (computed from `film_material` by `normalize_film_material()` in `build_sqlite.py`), while `sim_material_class` is AI-generated and less reliable for this purpose.

**`KNOWN_MATERIALS` whitelist** (in `build_sqlite.py`): Ta, Nb, Al, Re, TiN, NbN, NbTiN, TaN, NbSe2, PtSi, Ta-Hf, Mo3Al2C. Materials not in this list → `derived_material = "other"`. "other" tables are written to JSONL but excluded from Phase B. Add new materials to `KNOWN_MATERIALS` as the corpus grows — prompted by the ⚠ warning in `build_sqlite.py` output.

**FIELD_MAP note:** BCS gap terms (`"bcs gap"`, `"energy gap"`, `"superconducting gap"`) map to `Tc_K` directly rather than `derived_BCS_gap_meV`. This is correct — `derived_BCS_gap_meV` is a deterministic transform of Tc_K and carries no independent information. Author statements about the BCS gap are appropriately treated as Tc correlations.

### Current Mining Results (May 5)

41 correlations → 11 out of scope, 16 corpus gaps, 12 hypotheses matched → 15 evidence tables sufficient for Phase B. Key finding: **Tc_K vs deposition_temperature in Ta-Hf (83:17)**, confidence 0.72, positive — monotonic ~0.2–0.4 K Tc suppression across 550–850°C from a single 8-sample study. Remaining findings inconclusive or correctly flagged as derived field artifacts.

### Schema Evolution via Measurement Frequency

Phase A produces a measurement frequency report across `additional_measurements`. Fields appearing in >5% of materials samples are promotion candidates. Three fields confirmed ready for promotion:

| Field | Frequency | Units |
|---|---|---|
| `kinetic_inductance_sheet_pH_sq` | 49× | pH/sq |
| `vortex_activation_temperature_K` | 11× | K |
| `mean_free_path_nm` | 9× | nm |

**Promotion mechanics:** Values already stored in `catchall_items.value` as clean numerics. Promotion only requires adding named columns in `build_sqlite.py` — no re-ingestion needed.

**Domain rule:** Only geometry-independent (intrinsic) material properties are promotable. Sheet Lk yes; total Lk no.

---

## SQLite Database

Three tables. Derived from JSONL, rebuildable at any time — not a source of truth.

**`papers`** — one row per paper: outcome, DOI, title, authors, journal, sample count.

**`samples`** — one row per extracted sample: all schema fields, R vs T fields, derived quantities (prefixed `derived_`), `derived_material` (normalized film material for mining stratification), similarity profile dimensions (prefixed `sim_`), `sample_json` blob, `display_name` = `{first_author}_{year}_{sample_id}`.

New named columns added May 16-17:
- `resonator_type` — CPW or lumped_element
- `resonator_gap_width_um` — CPW gap width s; primary determinant of p_MS_resonator
- `p_MS_resonator` — surface participation ratio of resonator (for Q_TLS,0 → tan_delta inversion)
- `p_MS_pad` — surface participation ratio of qubit pad (for tan_delta → T1_pad_TLS)
- `Q_TLS_0` — unsaturated TLS quality factor (preferred over raw Qi for loss model input)
- `qubit_frequency_GHz` — qubit operating frequency (GHz); required for pad TLS calculation in t1_decomposition.py. Extracted by prompt and stored as named column (May 17).
- `derived_tan_delta` — best available surface loss tangent: tan_delta_effective_surface → loss_tangent_interface → loss_tangent_substrate
- `derived_resistivity_uOhm_cm` — geometry derivation first; falls back to directly reported `normal_state_resistivity_uOhm_cm`. Scaffold in place; fires for NbSe2/NbN geometry path only until Bahrami/Yang prompt fix.



**`catchall_items`** — one row per catchall entry, with `display_name` for joining to samples.

The `derived_material` column is the key addition in v0.8 — it enables reliable per-material stratification in Phase A independent of the AI-generated `sim_material_class`.

---

## Materials Explorer UI

**Local:** `http://localhost:8001/materials_explorer.html`
**Hosted:** `https://c2qa-materials-explorer.onrender.com` (auto-deploys from GitHub main branch)

**Explore** — Strip plot and scatter plot. Sidebar filters by `sim_material_class`. Click hint box (upper right of chart, "Click a data point for full info") opens detail panel. Axis labels enlarged and brightened for readability. Dropdown shows derived best-available fields only — raw Qi variants and raw loss tangent variants removed; Q_TLS,0 added as distinct plottable field.

**Search** — Table, Ranked, and Similar sub-views. Similarity result cards show matched profile tags and numeric field chips.

**Findings** — Read-only view of approved `findings.jsonl`. Cards show type badge (✓/✗/~/⚠), title, confidence, summary, clickable sample chips (green = supporting, red = complicating, each opens detail drawer). Full detail collapsed behind "▸ Show detail". Sorted: positive → negative → inconclusive → derived artifact, highest confidence first within type.

**Catchall** — All catchall items filtered by type.

### Similarity Search

Hybrid scoring: 75% profile score (8 semantic dimensions) + 25% numeric score (z-score normalized field distance). Falls back gracefully to profile-only or numeric-only.

---

## The Catch-All as First-Class Output

| Type | Description | Count |
|---|---|---|
| `additional_measurement` | Measurement with no named schema field | ~1,209 |
| `anomalous_observation` | Unexpected result flagged by authors | ~68 |
| `correlation` | Author-stated materials-to-device connection | 41 |

The 41 author-stated correlations are the primary input to Phase A. Note: `schema_candidate` type retired — merged into `additional_measurement`. Schema promotion is frequency-driven, not per-paper AI judgment.

---

## Human Review

**Record-level review** (`human_reviewed`, `human_approved` flags) — individual extracted records. Review UI planned as a future Explorer feature.

**Finding-level review** (Stage 4 UI) — three actions:
- **Accept** — finding is scientifically correct, recorded in `findings.jsonl`. Accept honest negative and inconclusive findings — they are real scientific results.
- **Send Back** — specific flaw identified; reviewer notes fed as context to next mining run.
- **Reject** — analysis is fundamentally wrong.

---

## Relevance Classification

**High — always ingest:** C2QA funding acknowledgment; Ta, Nb, Al, TiN, NbTiN, TaN, Re, NbN, NbSe2, PtSi materials; Josephson junction characterization; superconducting resonator loss studies.

**Medium — ingest material properties, flag application:** Superconducting materials in non-qubit applications; adjacent materials with potential qubit relevance.

**Low — skip:** Classical materials; superconducting power applications; high-Tc materials; purely theoretical papers; QEC / circuit-level papers with no materials content.

**Known leakage:** Some non-superconducting quantum systems (NV centers, SiV, ZnO donors) and pure theory proposals slip through as high/medium relevance when they carry a C2QA acknowledgment. Use `exclusions.json` to handle these post-hoc. Not worth fixing via prompt tuning alone — the acknowledgment signal is too strong and would risk suppressing legitimate papers.

---

## Deduplication

arXiv preprints and published versions matched by title similarity (≥ 0.85). Human decides: keep A, keep B, or not a duplicate. Decisions written to `deduplication.json`. `build_sqlite.py` excludes the losing paper from SQLite view. The JSONL retains both records.

---

## Manual Exclusions

Some records pass relevance classification but are subsequently found to be inappropriate — theory proposals, non-superconducting systems, or C2QA acknowledgment false positives. These are excluded post-hoc without modifying the JSONL.

**Mechanism:** `data/ingested/exclusions.json` — an append-only list read by `build_sqlite.py` at build time. Matching records are skipped before insertion into SQLite. Match priority: DOI → arXiv ID → filename. Each entry requires a human-readable `reason`.

**Current exclusions (3):** Hays 2026 (theory proposal, unbuilt "harmonium" qubit); Marcenac 2026 (NV center / FPGA control); WangX 2026 (ZnO semiconductor donor). All had C2QA acknowledgments causing false high-relevance.

**Rule:** A C2QA acknowledgment alone is not sufficient for relevance. The paper must report superconducting materials characterization data.

**Planned:** Exclusions management UI in the pipeline interface.

---

## Hardware Profile Updater

`generate_qubit_profile.py` projects a corpus sample into a QREM qubit hardware profile YAML. Measured fields labeled `[MEASURED]`; unmeasured fields use `transmon_baseline_2026.yaml` defaults labeled `[ASSUMED]`. Most materials papers measure T1 and T2 but not gate fidelity — profiles from such papers will have measured coherence but assumed gate parameters. The current YAML approach is transitional — target architecture has QREM querying the database directly in memory.

---

## Known Limitations

- Qi and T1 data reported only in figures may be missed or extracted at lower confidence
- Value confusion (Tc/Qi, Ic/Jc) observed — human review essential for medium-confidence extractions
- PDFs over ~24MB fail due to base64 encoding — compress with ghostscript at 150dpi (`-dColorImageResolution=150`, not `/screen` preset which strips figures)
- `sim_material_class` assignment unreliable for less common materials (NbSe2, PtSi) — cosmetic Explorer issue only, does not affect mining (uses `derived_material`)
- Gate fidelity rarely measured in materials papers — most qubit profiles will have assumed gate parameters
- SI files currently ingested as separate papers with no link to the main paper — significant gap, see SI Linking section below
- Resonator geometry (gap width, p_MS_resonator) often not reported in papers — without it, Q_TLS,0 alone has 6x uncertainty in tan_delta extraction. New fields `resonator_gap_width_um` and `p_MS_resonator` added to capture this when reported.
- SI files currently ingested as independent papers with no link to companion paper. Do not ingest SI files as standalone if the main paper is already ingested — wait for SI file linking implementation. Risk: duplicate sample records that are hard to merge.
- max_tokens = 64000 required for large multi-qubit papers (e.g. Bland 2025 with 57 qubits). Smaller papers still work fine at lower token counts.
- Normal-state resistivity (ρn) correctly extracted for Bahrami 2026 and Yang 2026 but lands in catchall rather than named field — extraction prompt fix pending. Fallback in `build_sqlite.py` is in place and will fire automatically once prompt is corrected and papers re-ingested.
- C2QA acknowledgment causes false high-relevance for theory proposals and non-superconducting systems — handle via `exclusions.json`, not prompt tuning.


---

## SI File Linking — Planned

**Current problem:** SI files are ingested as completely separate papers. Almost every paper has an SI, and SI files often contain the most detailed fabrication parameters.

**Proposed fix:** DOI-based naming convention in the papers folder:
```
{DOI_slug}_main.pdf
{DOI_slug}_SI.pdf
```
Ingester recognizes the pattern and ingests them as a single logical record. Pass 2 extraction has access to both documents. Resulting record carries `source_files: [main, SI]`.

**Open question:** SI files may need adjusted prompt handling — they are often tables and figures without narrative context, unlike main papers which have abstracts and conclusions.

**Provenance principle:** Peer review is inherited, not intrinsic. SI files and external database entries carry peer review credibility if traceable to a published paper via DOI. See continuity doc for full provenance hierarchy.

---

## Relationship to QREM

**Direct path** — samples with measured T1, T2, gate fidelity feed directly into QREM hardware profiles via the Hardware Profile Updater.

**Indirect path** — samples with only material properties (Tc, RRR, resistivity) feed the Materials Predictor and Mapping Layer (planned).

**Mining path** — approved `findings.jsonl` entries become the initial entries in the QREM mapping layer, connecting material properties to device performance.

---

## Development Phases

| Phase | Status | Description |
|---|---|---|
| Phase 1 — Manual template | Skipped | — |
| Phase 2 — AI-assisted extraction | ✅ Complete | Three-pass pipeline, Materials Explorer, derived quantities, deduplication, ingestion pipeline UI, Hardware Profile Updater, hybrid similarity search, public hosting |
| Phase 3 — Corpus mining | ✅ Complete | Phase A→B→C pipeline, human review UI, `findings.jsonl` ledger, per-material stratification, `derived_material` column, Findings tab in Explorer |
| Phase 4 — Schema evolution UI | Next | Stage 4 sub-step surfaces field promotion candidates from frequency report for human approval. Schema promotion implementation in `build_sqlite.py`. |
| Phase 4b — Manual exclusions UI | Planned | Management interface for `exclusions.json` in pipeline UI: show current exclusions, add by DOI/arXiv/filename, trigger rebuild. Currently requires manual JSON editing. |
| Phase 5 — SI file linking | Planned | DOI-based naming: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Ingester recognizes pair, ingests as single logical record with `source_files: [main, SI]`. Do not ingest SI files as standalone in the meantime. |
| Phase 6 — Human review UI | Planned | Record-level review mechanism integrated into Explorer |
| Phase 7 — Active literature monitoring | Planned | Automated arXiv/journal monitoring; weekly human review queue |

---

*End of Specification v0.10*
*Updated May 19, 2026.*
