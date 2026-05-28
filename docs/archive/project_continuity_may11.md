# C2QA QREM — Project Continuity & Coding Priorities
## Updated May 11, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Materials-first estimation complete. T1/T2 → fidelity → code distance. T1 sensitivity curve. Auto-run UI. Part A UI declutter complete May 9. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | Operational. Three-pass pipeline. 115 papers, 158 samples, ~1,378 catchall items, 100% profile coverage. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | Live at https://c2qa-materials-explorer.onrender.com. Major UI update May 11 (see below). |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | Operational. Per-material-class stratification, schema promotion, findings deduplication all complete. 1 positive finding (Ta-Hf Tc vs deposition temperature). |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | Designed, not built. First approved findings in `findings.jsonl`. Tier 2 physics formulas identified — awaiting Stage 4 implementation in QREM. |

---

## How They Connect

```
Scientific Papers
      ↓
[2] Publications Ingester (Pass 1 → Pass 2 → Pass 3)
      ↓
[3] Materials Database
    (Tc, RRR, Qi, T1, derived quantities, catchall, similarity_profiles)
      |
      |── Measured device performance (T1, T2, gate fidelity)
      |   → Hardware Profile Updater → qubit profile YAML   ← current (transitional)
      |   [target: QREM reads PUKs directly, no YAML step]
      |                                        ↓
      |── All corpus records              [1] Baby QREM
      |   → [4] Corpus Mining Pipeline        ↑
      |        → findings.jsonl               |
      |        → [6] Mapping Layer ───────────┘
      |
      └── Material properties (Tc, RRR, loss tangent)
          → [5] Materials Predictor → [6] Mapping Layer
```

**The scientific question the pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and run this quantum circuit, how many physical qubits do I need?"*

---

## Recent Completions (May 9–11, 2026)

### Explorer UI — Major Update (May 11)

- **Derived substrate normalization** — `normalize_substrate()` in `build_sqlite.py` maps raw substrate strings to canonical short list: Silicon, Sapphire, Silicon Carbide, Diamond, Other. Fixed `\bsi\b` regex bug (was matching "intrinsic" → Silicon Carbide via "sic"); fixed `serve_materials.py` missing `derived_substrate` and `derived_deposition_method` in `fetch_samples()` SELECT.
- **Derived deposition method normalization** — `normalize_deposition_method()` maps to: DC Sputtering, RF Sputtering, Ebeam Evaporation, Thermal Evaporation, MBE, ALD, CVD, PLD, Other. Correctly filters patterning methods (EBL) to Other.
- **Substrate filter** — now uses `derived_substrate` canonical values (5 options) instead of raw strings (20+ options). Filter bug fixed — was causing infinite recursion via double `onFilterChange()` definition.
- **Group by deposition method** — now uses `derived_deposition_method` canonical values, eliminating label proliferation.
- **Chart height** — fixed `.chart-wrapper` to `height: 320px; flex: none`. `.layout` height adjusted to `calc(100vh - 90px)` to keep status bar visible.
- **Header rebrand** — "C2QA // QIS Materials Explorer". Subtitle removed.
- **Filter label** — "Search display name" → "Filter by author / paper" (partial match on display_name).
- **Catchall sample names clickable** — `display_name` in catchall list now opens detail drawer.

### Baby QREM UI — Part A Declutter (May 9)

- Circuit Analysis and Simplifying Assumptions moved into `▸ Reference Details` collapsible
- Error Attribution panel full-width single column
- Top table removed from Error Attribution (redundant with sliders and metric cards)
- Gate Error Decomposition bar is now sole Error Attribution content
- ε_T1 row styled with `▸` affordance as Part B drawer trigger
- Section labels shortened; header/chart/card padding tightened
- Derived Fidelity metric card restored

### Mining + Schema (May 9)

- Schema promotion operational (`promote_fields.py`). Three fields promoted: `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K`. Phase A now has 19 sufficient evidence tables.
- Findings deduplication guard — `↻ previously approved` badges, Replace button, Explorer reads from canonical `/api/approved_findings`.
- Schema promotion UI — Stage 4 candidates section auto-loads. Candidates filtered to fields defined in `promote_fields.py` not yet in schema.
- Extraction prompt fix — `film_material` is superconducting film identity only; junction material goes in `junction_material`.

---

## Current State

### Baby QREM

Materials-first estimation working:
```
T1, T2 (sliders) + gate_time (fixed from profile)
  → ε_T1 = gate_time / T1
  → ε_T2 = gate_time / T2
  → ε_ctrl (fixed from clean baseline — engineering term, not materials)
  → ε_total → derived gate fidelity → code distance → physical qubits
```

UI at `localhost:8000/scripts/qrem_ui.html`. Auto-runs on load. T1 sensitivity staircase (log y-axis, labeled by code distance d). Error Attribution shows ε_T1/ε_T2/ε_ctrl decomposition with ε_T1 as Part B drawer trigger.

### Explorer

UI at `localhost:8001/materials_explorer.html` (local) and `https://c2qa-materials-explorer.onrender.com` (hosted).

**Corpus state:** 115 papers processed, 158 samples, 1,378 catchall items, 100% similarity profiles.

**Material breakdown (derived_material):** Ta (35), other (27), Al (16), unknown (13), NbSe2 (12), Re (12), Ta-Hf (12), PtSi (11), Mo3Al2C (5), NbN (5), TaN (2), Nb (1)

**Named column coverage:** Tc 39%, RRR 20%, Qi 17%, T1 13%

**Substrate breakdown (derived_substrate):** Silicon majority, Sapphire, Silicon Carbide, Diamond, Other (mica, GaN, AlN, ZnO, Au/hBN)

**Deposition method breakdown:** DC Sputtering (56), Unknown (63), Ebeam Evaporation (12), Other (10), ALD (7), Thermal Evaporation (5), MBE (3), CVD (2)

---

## Next Coding Priorities

### Track A: Baby QREM (blocked pending colleague conversation)

**1. Loss mechanism attribution (Stage 4 backend)** — Break T1 into TLS / quasiparticle / vortex motion / radiation contributions using standard Tier 2 physics formulas. Pure Python in `estimator.py`, no HTML needed first.

- `T1_TLS ≈ Qi / (2πf)` — from internal quality factor
- `T1_QP` — from Tc via thermal activation: `n_qp ∝ exp(−1.76 Tc / T_operating)`
- `T1_vortex` — from mean free path relative to coherence length (clean vs dirty limit). Corpus support: approved finding shows dirty-limit Ta films have ~10× higher vortex activation temperature than clean-limit films.
- `T1_radiation` — class default if nothing relevant measured

Each channel labeled individually with its provenance tier (`[MEASURED]`, `[DERIVED]`, `[CLASS DEFAULT]`, `[ASSUMED]`). Does not require corpus mining findings — standard analytical formulas. **Note: model details being worked out with colleague — implement after that conversation.**

**2. Part B drawer UI** — Bottom drawer triggered by clicking ε_T1. Shows T1 decomposed into TLS/QP/vortex/radiation channels with per-channel provenance. Upstream material property sliders (Qi, Tc, mean free path) update main page metrics and staircase in real time. Staircase must stay visible. Bottom drawer pushes content up, does not overlay. **Prerequisite: Stage 4 backend (#1) must exist first.**

**3. Pluggable mapping model profiles** — extend YAML profile pattern to T1 decomposition models. New directory: `hardware_profiles/mapping_models/`. First implementation: `t1_decomposition_analytical.yaml`. Allows different center groups to contribute models without touching core estimator code.

**4. RRR → T1 sensitivity sliders (Stage 5)** — upstream material property sliders feeding through Tier 2 mapping functions. T1 sensitivity staircase becomes a material property sensitivity curve. Depends on #1.

**5. Readout fidelity** — wire into QEC model (currently loaded but unused).

**6. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Ingester / Mining

**7. SI file linking** — implement DOI-based naming convention so SI files ingest as part of the same logical record. Convention: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Pass 2 extraction has access to both documents; record carries `source_files: [main, SI]`. **Blocked: need to collect SI files first. Open question: SI files are often tables/figures without narrative context — may need adjusted prompt handling.**

**8. Corpus expansion** — older literature ingestion. Collection in progress.

**9. Ic/Jc disambiguation** — `derive.py` functions, schema columns, extraction prompt fix. Two physically distinct quantities currently conflated: material Jc (bulk film, intrinsic) and junction Jc (device property).

### Track C: Longer Term

**10. Community upload feature** — public Explorer with PDF upload. Requires real server infrastructure (not Render). Architecture: upload queue → existing three-pass pipeline → record appears in Explorer. Pass 1 relevance check acts as content filter.

**11. Materials Predictor** — Gaussian process regression per material class.

**12. Tier 2 modular reconnection** — reconnect modular overhead cost model (Arquin) when Center-wide architecture research matures. Functions preserved in `estimator_tier2_modular.py`.

---

## Long-Term Vision: Data-Driven Hypothesis Generation

The current corpus mining pipeline is **author-guided**: Phase A finds correlations the authors stated in papers, Phase B tests them against the corpus. This is scientifically conservative and avoids the multiple comparisons problem, but it is limited to what authors noticed and chose to report.

A future evolution — appropriate once the corpus is substantially larger (likely 500+ samples with denser per-material coverage) — would move toward **data-driven hypothesis generation**: the system proposes hypotheses from the data itself, not from author statements.

The model for this is the SEM Metadata Pipeline (separate project), specifically its Stage 04 — Open Questions Synthesis. In that pipeline, each ingested record generates 2-3 `open_questions` during extraction: specific scientific unknowns anchored to what was actually measured in that image/paper. Stage 04 then clusters those questions across the corpus by theme, ranks by scientific significance and answerability, and produces proto-hypotheses that seed the discovery engine — regardless of whether any author stated them.

Applied to the materials pipeline this would look like:
- **Pass 2 extension** — during extraction, Claude also generates 2-3 open questions per sample. E.g. "this paper measured high RRR but not T1 — is there a pattern across Ta samples between RRR and T1?"
- **Phase A extension** — collects, deduplicates, and clusters open questions across the corpus by theme
- **Phase B** — tests the highest-significance, most-answerable clusters against the evidence tables, same as today
- **Result** — findings that go beyond what any author stated, structured and human-reviewable

Key safeguards needed before building this:
- **Multiple comparisons**: the open-questions approach sidesteps brute-force field-pair fishing by generating targeted questions from scientific intuition embedded in the extraction prompt. Still need to be careful about testing too many hypotheses on small per-material datasets.
- **Per-material stratification is essential**: cross-material correlations are almost meaningless due to material identity confounding. Already implemented for author-stated correlations; must carry forward.
- **Minimum corpus size**: most per-material datasets currently have 5-16 samples — too small for reliable correlation detection. Target: ~30+ samples per material class before data-driven generation is meaningful for that class. Ta (35) is close; others are not yet there.

**Reference:** See SEM Metadata Pipeline architecture doc (April 2026) for Stage 04 design, particularly the open questions synthesis and clustering approach.

---

## Data Provenance Principles

**Peer review is inherited, not intrinsic.** SI files and external database entries carry peer review credibility if traceable to a published paper via DOI.

| Source | Confidence | Rationale |
|---|---|---|
| Peer-reviewed paper (main text) | Highest | Full peer review, narrative context |
| SI file linked to paper via DOI | High | Same peer review umbrella |
| arXiv preprint | Medium-high | Author-accountable, not yet reviewed |
| External database entry with traceable DOI | Medium | Peer review inherited if link exists |
| External database entry, no traceable publication | Low | Unreviewed direct submission |
| Raw dataset repository (Zenodo, Figshare) | Variable | Depends on paper linkage |

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — self-contained. Target architecture: QREM reads PUKs directly, no YAML export step. Current Explorer → YAML → QREM workflow is transitional.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. Every mining finding requires human review before entering `findings.jsonl`.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — correlations must be tested within a material class. `derived_material` (deterministic, whitelist-based) drives Phase A; `sim_material_class` (AI-generated) drives Explorer sidebar filter.
- **Schema evolution is frequency-driven** — geometry-independent (intrinsic) properties only. Promotion = adding named columns; no re-ingestion needed.
- **Materials-first estimation** — gate fidelity is an output, not an input. ε_ctrl fixed from clean baseline, does not vary with T1/T2 slider changes.
- **The estimator always estimates** — documents assumptions, flags uncertainty, never refuses to give a number. Tiered fallback: `[MEASURED]` → `[DERIVED]` → `[CLASS DEFAULT]` → `[ASSUMED]`.
- **findings.jsonl is append-only** — supersede old entries by hypothesis_key, never mutate in place. Explorer filters to latest per key.
- **film_material is superconducting film identity only** — junction material goes in `junction_material`. Existing records handled by `derived_material` normalization.
- **Explorer is the Explorer** — literature database and discovery tool, not a physics inference engine. Materials-to-device reasoning belongs in QREM.
- **BCS gap maps to Tc** — `derived_BCS_gap_meV` is a deterministic transform of Tc_K. Author correlations mentioning "BCS gap" are mapped to `Tc_K` in FIELD_MAP.

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py
# Open http://localhost:8001/ingest_pipeline.html
# Open http://localhost:8001/materials_explorer.html

# Baby QREM (port 8000)
cd "2026-04 c2qa_qrem" && python3 scripts/serve.py
# Open http://localhost:8000/scripts/qrem_ui.html

# Rebuild SQLite after any JSONL or build_sqlite.py changes
cd ingester && python3 build_sqlite.py

# Mining pipeline (after ingestion + build)
python3 pipeline_mining.py phase-a
python3 pipeline_mining.py phase-b
python3 pipeline_mining.py phase-c

# Backfill similarity profiles for specific paper
python3 backfill_similarity_profiles.py --filter Zaman
python3 backfill_similarity_profiles.py --dry-run  # preview

# Standard commit
git add . && git commit -m "description" && git push
```

---

*Last updated: May 11, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
