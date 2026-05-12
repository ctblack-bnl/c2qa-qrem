# C2QA QREM — Quantum Resource Estimation and Materials Pipeline

A modular, staged pipeline for quantum resource estimation and materials characterization data for superconducting qubit systems. The system estimates the physical resources (qubits and error correction overhead) required to run quantum circuits on real hardware, connects those estimates to physical material properties, and automatically extracts structured materials data from scientific publications into a searchable database.

**Core principle throughout: AI proposes, humans approve.** Every AI inference carries a confidence score and source citation. Simplifying assumptions are always documented explicitly in tool outputs.

**Live Explorer:** https://c2qa-materials-explorer.onrender.com

---

## Six Components

**Baby QREM** — takes a quantum circuit and a qubit hardware profile, and estimates how many physical qubits and how much error correction overhead are needed to run it. Gate fidelity is derived from material properties (T1, T2, gate time) rather than taken as input — making the tool directly useful to materials scientists. Modular overhead is deliberately out of scope; Baby QREM is a single-module resource estimator. The T1 sensitivity curve shows exactly which T1 threshold gets you across each code distance step.

**Publications Ingester** — reads scientific papers (PDFs) and automatically extracts structured materials characterization data into a database. Three-pass pipeline: relevance classification, full extraction, and similarity profile generation. Handles idempotent processing and human review flagging. Includes a browser-based ingestion pipeline UI.

**Materials Database + Explorer** — a structured, queryable store of materials characterization records following the Five-Center Materials Working Group schema (v0.8, six blocks). Populated by the ingester. Browsable via the C2QA QIS Materials Explorer UI with four tabs: Explore, Search, Findings, and Catchall. Explorer filters by normalized substrate (Silicon, Sapphire, Silicon Carbide, Diamond, Other) and groups by normalized deposition method (DC Sputtering, RF Sputtering, Ebeam Evaporation, etc.) — collapsing raw string variants to clean canonical labels.

**Corpus Mining Pipeline** — operates over all ingested records to extract, reason about, and formalize materials-to-device connection hypotheses. Three phases: Phase A (mechanical evidence extraction and co-occurrence analysis, per material class), Phase B (AI reasoning constrained to evidence tables), Phase C (AI write-up of structured findings). Approved findings enter `findings.jsonl` and feed the mapping layer.

**Materials Predictor** — similarity search is operational (hybrid scoring: 75% semantic profile + 25% numeric field distance). Gaussian process regression not yet built.

**Materials-to-Device Mapping Layer** — bridges material properties (Tc, RRR, Qi, loss tangent) to device parameters (T1, gate fidelity) for samples without direct device measurements. Designed, not yet fully built. First approved mining findings now provide initial entries.

---

## Prerequisites

- Python 3.10+ recommended (3.9 minimum — some deprecation warnings with Qiskit)
- API access: Azure Claude via Anthropic Foundry (for ingester and mining pipeline)

```bash
pip install qiskit networkx pyyaml anthropic
```

---

## Directory Structure

```
2026-04 c2qa_qrem/
  src/qrem/
    parser.py                         ← Stage 1: OpenQASM → CircuitIR
    circuit_ir.py                     ← Internal circuit representation
    analyzer.py                       ← Stage 2: interaction graph, circuit depth
    estimator.py                      ← Stage 3: materials-first estimation (Tier 1)
    estimator_tier2_modular.py        ← Tier 2 modular functions (preserved, not active)
    profile_loader.py                 ← Profile loader: qubits + QEC
    hardware_profiles/
      qubits/
        transmon_baseline_2026.yaml   ← Baseline: T1=200µs, T2=300µs, gate=50ns
        {sample_display_name}.yaml    ← Corpus-derived profiles (Hardware Profile Updater)
      error_correction/
        surface_code_1e6.yaml         ← Surface code threshold + target LER
      superconducting.yaml            ← Legacy monolithic profile (still supported)

  scripts/
    serve.py                          ← HTTP server: Baby QREM UI
    qrem_ui.html                      ← Baby QREM browser UI

  ingester/
    pipeline_ingest.py                ← Main loop: find PDFs, classify, extract, write JSONL
    pipeline_mining.py                ← Corpus mining: Phase A → B → C
    prompts.py                        ← Relevance check + extraction + profile prompts
    processed_ledger.py               ← DOI-primary / filename-fallback idempotency ledger
    build_sqlite.py                   ← Loads JSONL into SQLite; derived quantities, similarity
                                         profile, derived_material columns
    derive.py                         ← Deterministic derived quantities computed at build time
    promote_fields.py                 ← Schema field promotion from catchall to named columns
    backfill_similarity_profiles.py   ← Pass 3 backfill; --filter flag for targeted reprocessing
    generate_qubit_profile.py         ← Hardware Profile Updater: QREM YAML from corpus sample
    serve_materials.py                ← HTTP server: Materials Explorer + Ingestion Pipeline UI
    materials_explorer.html           ← Explorer UI: Explore / Search / Findings / Catchall tabs
    ingest_pipeline.html              ← Pipeline UI: Stages 1-4 (ingest → dedup → build → mine)
    config.py                         ← Azure/Claude API configuration (env vars)
    openai_client.py                  ← Provider abstraction (Azure Claude via Anthropic Foundry)
    io_jsonl.py                       ← Append-only JSONL read/write utilities
    json_utils.py                     ← Safe JSON serialization

  data/
    circuits/                         ← Input .qasm circuit files
      test_circuit.qasm               ← 3-qubit repetition code syndrome (5 qubits, depth 8)
      test_circuit_02.qasm            ← VQE ansatz layer (4 qubits)
      qft_5qubit.qasm                 ← Quantum Fourier Transform (5 qubits, depth 11)
    papers/                           ← Drop PDFs here for ingestion (subfolders supported)
    ingested/
      records.jsonl                   ← Append-only canonical ingestion ledger (source of truth)
      processed_ledger.json           ← Tracks processed papers (skip on re-run)
      deduplication.json              ← Human decisions on duplicate paper pairs
      records.db                      ← SQLite browse database (derived, rebuildable)
      findings.jsonl                  ← Append-only approved mining findings ledger
      mining_evidence.jsonl           ← Phase A output: evidence tables per hypothesis
      mining_reasoned.jsonl           ← Phase B output: AI reasoning per hypothesis
      mining_findings.jsonl           ← Phase C output: structured findings for human review
      mining_findings_report.md       ← Phase C output: human-readable markdown report
```

---

## Environment Setup

```bash
# For the ingester and mining pipeline (Claude via Azure Foundry)
export PROVIDER=claude
export AZURE_CLAUDE_API_KEY=your-key-here
export AZURE_CLAUDE_BASE_URL=https://your-endpoint.services.ai.azure.com/anthropic
export AZURE_CLAUDE_DEPLOYMENT=claude-sonnet-4-6
```

The client factory in `ingester/openai_client.py` wraps both Azure Claude and Azure OpenAI behind a common interface. Switch providers by changing the `PROVIDER` env var.

---

## Running Baby QREM

### UI (recommended)

```bash
cd "2026-04 c2qa_qrem"
python3 scripts/serve.py
# Open http://localhost:8000/scripts/qrem_ui.html
```

The UI auto-runs on page load with default profile and circuit. No run button — estimation updates automatically when any control changes. Controls: circuit selector, qubit profile dropdown, T1/T2 sliders, success rate target. The T1 sensitivity staircase shows physical qubit count vs T1 on a log scale, with code distance thresholds labeled.

### CLI

```bash
cd src/qrem
python3 estimator.py ../../data/circuits/test_circuit.qasm hardware_profiles/superconducting.yaml
```

### What Baby QREM estimates

Baby QREM is a **single-module resource estimator**. It answers the question: *"I have a superconducting qubit with this T1 and T2. If I run this quantum circuit, how many physical qubits do I need, and how does that change as my materials improve?"*

Gate fidelity is **derived** from T1, T2, and gate time — it is an output, not an input:

```
ε_T1    = gate_time / T1          (energy relaxation — materials)
ε_T2    = gate_time / T2          (dephasing — materials + environment)
ε_ctrl  = fixed from baseline     (pulse errors — engineering, not materials)
fidelity = 1 - ε_T1 - ε_T2 - ε_ctrl
```

The required logical error rate is derived from circuit depth and target success rate, making resource estimates circuit-specific rather than generic. Modular overhead (inter-module links, purification, communication qubits) is deliberately out of scope for Baby QREM — those functions are preserved in `estimator_tier2_modular.py` but not active.

Every input follows a four-tier fallback hierarchy so the estimator always produces a result:

| Tier | Label | Source |
|---|---|---|
| 1 | `[MEASURED]` | Directly reported in the paper |
| 2 | `[DERIVED]` | Computed from measured quantities via physics formulas |
| 3 | `[CLASS DEFAULT]` | Typical value for this material class |
| 4 | `[ASSUMED]` | Baseline profile default |

### Example output (test_circuit.qasm, T1=200µs, T2=300µs)

```
Derived gate fidelity    : 99.900%
Code distance (d)        : 5
Physical qubits/logical  : 49 (= 2d² - 1)
Logical qubits           : 5
TOTAL physical qubits    : 245
Feasible                 : YES
```

---

## Running the Publications Ingester

### UI (recommended)

```bash
cd ingester
export PROVIDER=claude
export AZURE_CLAUDE_API_KEY=your-key-here
python3 serve_materials.py
# Open http://localhost:8001/ingest_pipeline.html
```

Four-stage pipeline UI:
1. **Ingest** — select papers directory, start ingestion, watch live progress log
2. **Review duplicates** — side-by-side comparison of potential duplicate pairs (arXiv preprint vs published version)
3. **Build database** — one click; shows warnings for unrecognized film materials; link to Explorer on success
4. **Mine corpus** — run Phase A→B→C; review findings; approve / send back / reject

### CLI

```bash
cd ingester
caffeinate python3 pipeline_ingest.py
python3 build_sqlite.py

# Mining pipeline
python3 pipeline_mining.py phase-a
python3 pipeline_mining.py phase-b
python3 pipeline_mining.py phase-c
```

### Three-pass processing

Each paper goes through up to three passes:

**Pass 1 — Relevance check (~15 seconds):** Claude reads the paper and classifies relevance (high / medium / low), paper type, and DOI. Low-relevance papers are logged and skipped — no further API cost.

**Pass 2 — Full extraction (~60-90 seconds):** For relevant papers only. Claude extracts structured materials characterization data following the six-block schema. Sparse output — only fields actually reported in the paper are included. Every field carries a confidence score (high / medium / low) and a specific source citation.

**Pass 3 — Similarity profile (~15-20 seconds):** Generates an 8-dimension semantic profile (Block 6) for use in Explorer similarity search. Non-fatal — if it fails, the record is still written and profiles can be backfilled later.

### Idempotency

Papers already processed are automatically skipped. The processed ledger uses DOI as the primary key (stable even if the file is renamed) with filename as a fallback. Re-running on the same directory is safe.

### Building the SQLite browse database

```bash
python3 build_sqlite.py
```

Open `data/ingested/records.db` in DB Browser for SQLite (free, sqlitebrowser.org). Three tables:

- **papers** — one row per paper: outcome, DOI, title, authors, journal, sample count
- **samples** — one row per extracted sample: all schema fields, derived quantities (prefixed `derived_`), similarity profile dimensions (prefixed `sim_`), `derived_material` (for mining stratification), `derived_substrate` and `derived_deposition_method` (normalized canonical values for Explorer filtering and grouping)
- **catchall_items** — one row per catchall entry: additional measurements, anomalous observations, correlations

The SQLite database is derived and rebuildable at any time from the JSONL ledger. It is not a source of truth.

### Useful queries

```sql
-- Coverage summary
SELECT
    COUNT(*) as total_samples,
    SUM(CASE WHEN Tc_K IS NOT NULL THEN 1 ELSE 0 END) as has_Tc,
    SUM(CASE WHEN RRR IS NOT NULL THEN 1 ELSE 0 END) as has_RRR,
    SUM(CASE WHEN Qi_internal_quality_factor IS NOT NULL THEN 1 ELSE 0 END) as has_Qi,
    SUM(CASE WHEN T1_us IS NOT NULL THEN 1 ELSE 0 END) as has_T1
FROM samples;

-- All samples with key measurements
SELECT display_name, derived_material, Tc_K, RRR, Qi_internal_quality_factor, T1_us
FROM samples
ORDER BY derived_material, display_name;

-- All author-stated correlations (primary input to corpus mining)
SELECT display_name, description
FROM catchall_items
WHERE item_type = 'correlation';
```

---

## Corpus Mining Pipeline

The mining pipeline extracts materials-to-device connection hypotheses from the full corpus of ingested records. It runs as Stage 4 of the ingestion pipeline UI.

**Phase A (mechanical):** Reads all correlation catchall items, maps descriptive terms to canonical field names, and produces evidence tables showing co-occurrence of paired measurements across the corpus — both globally (all materials) and per material class (stratified by `derived_material`). Also produces a measurement frequency report driving schema evolution.

**Phase B (AI reasoning):** One API call per evidence table with sufficient data (≥3 samples). Claude reasons over the evidence, cites specific samples, and attempts self-falsification. Prior approved findings fed as context.

**Phase C (AI write-up):** Structured human-reviewable finding per hypothesis — title, summary, supporting and complicating records, QREM implications, questions for the reviewer.

**Human review:** Accept (including negative/inconclusive findings — they are real results) / Send Back / Reject. Approved findings enter `findings.jsonl` and become the initial entries in the QREM mapping layer.

Per-material-class stratification is essential — cross-material hypothesis testing is confounded by material identity. The `derived_material` column (deterministic, whitelist-based normalization of `film_material`) drives Phase A stratification.

---

## JSONL Ledger Design

All ingester records are written to an append-only JSONL file. Every record contains the full Pass 1, Pass 2, and Pass 3 outputs, provenance metadata, and human review flags. Records are never modified in place.

```
records.jsonl      ← canonical ledger (source of truth)
  → records.db     ← SQLite projection (derived, rebuildable)

findings.jsonl     ← approved mining findings (append-only, independent of corpus reset)
```

Every ingested record starts with `human_reviewed: false` and `human_approved: false`. Records should be reviewed before feeding into the QREM materials-to-device mapping layer.

---

## Current Corpus State (May 11, 2026)

| Metric | Value |
|---|---|
| Papers processed | 115 |
| Papers ingested | ~57 |
| Skip rate | ~44% |
| Samples extracted | 158 |
| Catchall items | ~1,378 |
| Author-stated correlations | 41 |
| Similarity profiles | 158 (100%) |
| Coverage: Tc | 39% |
| Coverage: RRR | 20% |
| Coverage: Qi | 17% |
| Coverage: T1 | 13% |

**Material breakdown:** Ta (35), other (27), Al (16), unknown (13), NbSe2 (12), Re (12), Ta-Hf (12), PtSi (11), Mo3Al2C (5), NbN (5), TaN (2), Nb (1)

**Mining results:** 19 sufficient evidence tables (global + per-material-class). 1 positive finding: Tc vs deposition temperature in Ta-Hf (83:17), confidence 0.72. Remaining findings inconclusive — expected at current corpus size.


---

## Key Design Decisions

**Baby QREM is a single-module estimator.** Modular overhead (inter-module links, purification, communication qubit counts) is a separate Center-wide research problem. Baby QREM stays out of that space. Tier 2 modular functions are preserved in `estimator_tier2_modular.py` for future reconnection when that research matures.

**Gate fidelity is derived, not input.** Fidelity is computed from T1, T2, and gate time. This makes the tool directly useful to materials scientists: vary T1, watch physical qubit count change. The T1 sensitivity curve shows exactly which T1 threshold crosses each code distance step.

**ε_ctrl is fixed from the baseline profile.** The control error term is derived once from the unmodified baseline and held constant when T1/T2 sliders move. Without this, moving a slider would corrupt ε_ctrl and blur the code distance staircase steps.

**The estimator always estimates.** For any given corpus record, some quantities are measured, some can be derived, some must be assumed. The estimator handles all cases gracefully and documents every assumption — it never refuses to give a number.

**Append-only JSONL as canonical ledger.** Reproducibility and auditability. Any downstream artifact can be regenerated from the JSONL. In-place mutation would break this guarantee.

**Three-pass ingestion.** Pass 1 (relevance) is cheap; irrelevant papers are rejected before incurring full extraction cost. Pass 2 (extraction) produces sparse output — only fields actually reported in the paper. Pass 3 (similarity profile) is non-fatal and backfillable.

**DOI-primary idempotency.** The processed ledger uses DOI as the primary key, filename as fallback. Papers are recognized as already processed even if renamed.

**Hardware profiles as data, not code.** Platform parameters live in YAML files. Changing qubit profiles or running sensitivity analysis requires only selecting a different file — no code changes.

**Per-material stratification for mining.** Materials-to-device correlations must be tested within a material class, not cross-corpus. Cross-material comparisons are confounded by material identity. `derived_material` (deterministic, whitelist-based) drives Phase A; `sim_material_class` (AI-generated) drives the Explorer sidebar filter.

**Schema evolution is frequency-driven.** Fields are promoted from the catchall to named database columns based on measurement frequency across the corpus. Only geometry-independent (intrinsic) material properties are promotable. Three fields promoted as of May 2026: `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K`.

**Provider abstraction.** `openai_client.py` wraps both Azure Claude and Azure OpenAI behind a common interface. Switch providers by changing the `PROVIDER` environment variable.

---

## Known Limitations

**Baby QREM:**
- Single-module only — SWAP routing overhead not modeled; physical qubit counts are lower bounds.
- Analytical surface code approximation — not full Stim simulation.
- T gate counting is a placeholder (0) — magic state factory costs underestimated for T-gate-heavy circuits.
- Modular overhead (inter-module links, purification) not modeled — preserved in `estimator_tier2_modular.py`, not active.
- Loss mechanism attribution (T1 → TLS / quasiparticle / vortex / radiation breakdown) not yet implemented — planned as Stage 4.

**Publications Ingester:**
- Qi and T1 data reported only in figures (not tables) may be missed or extracted at lower confidence.
- PDFs over ~24MB fail due to base64 encoding — compress with ghostscript at 150dpi before ingesting.
- Human review is essential before using extracted records in quantitative analysis — value confusion errors (e.g. Tc vs Qi, Ic vs Jc) have been observed in testing.
- SI files are currently ingested as separate papers with no link to the main paper — planned fix via DOI-based naming convention.

---

## Specification Documents

Full design rationale, interface contracts, and implementation details:

- `quantum_resource_estimator_spec_v09.md` — Baby QREM pipeline architecture, materials-first estimation model, tiered fallback hierarchy, hardware profiles, development sequence
- `publications_ingester_spec_v08.md` — ingester design, three-pass pipeline, corpus mining architecture, per-material stratification, schema evolution
- `materials_characterization_schema_v08.md` — six-block schema, all fields, similarity profile vocabulary, governance, schema evolution process
- `qrem_scientific_vision.md` — the three modes of materials-to-device connection (direct measurement, known physics, corpus-discovered), scientific rationale for the pipeline architecture
- `project_continuity_may11.md` — current development state, next coding priorities, running the full system

---

*C2QA QREM Project — May 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
