# C2QA QREM — Project Continuity & Coding Priorities
## Updated May 21, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Stage 4 T1 loss channel breakdown panel complete (May 21). ε_ctrl fixed to controls baseline. T1 slider extended to 1000µs. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | ✅ Operational. Three-pass pipeline. max_tokens = 64000. New resonator geometry fields added (May 16). Manual exclusions mechanism added (May 19). |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | ✅ Live at https://c2qa-materials-explorer.onrender.com. See Explorer header for live corpus counts. |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | ✅ Operational. 1 positive finding (Ta-Hf Tc vs deposition temperature). |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | `t1_decomposition.py` Stage B complete and validated. Stage C (UI integration) complete May 21 — panel shows in Baby QREM when corpus profile loaded. Stage D (material property sliders → T1) is Stage 5, planned. |

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
      |   → Hardware Profile Updater → qubit profile YAML   ← transitional
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

## Recent Completions (May 21, 2026)

### Stage 4 — T1 Loss Channel Breakdown Panel (Baby QREM UI)

New collapsible panel in the Error Attribution section of `qrem_ui.html`. Shows the T1 loss channel decomposition when a corpus-derived profile is loaded:

- **tan_delta** with provenance tag
- **Five channels:** Pad TLS, Junction TLS, Quasiparticle, Vortex, Radiation — each with T1 contribution and provenance
- **T1 predicted** vs **T1 measured** (from profile) with ✓/✗ within 5× validation indicator
- Panel is triggered by clicking the "T1 Loss Channel Breakdown ▸" header
- Panel **disappears immediately** when either T1 or T2 slider is touched — the decomposition is only valid at profile values, not at hypothetical slider positions
- Panel is hidden when `tan_delta_provenance === CLASS_DEFAULT` — no real surface loss data means no meaningful decomposition to show (baseline profile, Bland, Wang all hidden; Joshi profiles show)

**`slidersMoved` flag design:** Set to `false` on every profile load, `true` on any slider touch. Simpler and more robust than tracking exact slider values.

**`profileRawT1`:** Stores the actual profile T1 before slider clamping, used for "T1 measured" display. Prevents showing clamped slider value (e.g. 500µs) when real T1 is 794µs.

### T1 Slider Extended to 1000µs

Previously capped at 500µs, which clipped Bland_2025_Qubit_16 (T1=794µs) and prevented the decomposition panel from appearing. Slider range, ticks, and staircase curve all extended to 1000µs.

### ε_ctrl Fixed to Controls Baseline (`estimator.py`)

**Bug fixed:** ε_ctrl was being derived from the selected corpus profile (e.g. Wang_2026_Transmon_2 with T2=51µs), producing ε_ctrl=0 due to clamping when coherence errors dominated the error budget.

**Fix:** ε_ctrl is now always derived from `transmon_baseline_2026` — the controls baseline — regardless of which qubit profile is selected. `transmon_baseline_2026` is explicitly the controls baseline: it encodes pulse engineering quality (pulse errors, leakage, calibration), which is fixed by the control system and independent of material properties. Corpus profiles contribute T1 and T2 only.

**Implementation:** `load_profile(profiles_dir=profiles_dir, qubits='transmon_baseline_2026')` called in `run_estimation()` before the main profile load. `Path` import added to `estimator.py`. Legacy path fallback resolves baseline relative to the legacy profile directory.

### Qubit Profile Housekeeping

Three stale qubit profiles (missing Stage 4 sections, pre-dating `generate_qubit_profile.py` Stage 4 extension) deleted and regenerated from Explorer:
- `Bland_2025_Qubit_16.yaml` — regenerated May 21, now has materials/device/surface_participation sections and defaults_path
- `Wang_2026_Transmon_1.yaml` — regenerated May 21
- `Wang_2026_Transmon_2.yaml` — regenerated May 21

`transmon_baseline_2026.yaml` patched manually with Stage 4 sections (`materials: {}`, `device: {}`, `surface_participation: {}`) and `defaults_path: ../mapping_models/transmon_analytical_defaults.yaml`.

`generate_qubit_profile.py` confirmed already correct — all future generated profiles will include Stage 4 sections automatically.

---

## Recent Completions (May 19-20, 2026)

### T2_ramsey_us Column
`T2_ramsey_us` added as named column in `build_sqlite.py`, `serve_materials.py`, and `materials_explorer.html`. Extraction prompt updated with explicit T2 disambiguation (echo vs Ramsey). Re-ingested Joshi 2026, Wang 2026, Xia 2025.

### Explorer: derived_tan_delta
New `derived_tan_delta` column: `tan_delta_effective_surface` → `loss_tangent_interface` → `loss_tangent_substrate` priority. Appears as "Loss tangent (best available)" in Explorer dropdown. Key input to T1 loss model.

### Explorer: Q_TLS,0 as Plottable Field
`Q_TLS_0` added as distinct plottable field — physically distinct from Qi, not folded into `derived_Qi`.

### Explorer: Per-Point Symbol Encoding
Solid vs open circles for derived best-available fields (`derived_Qi`, `derived_T2_us`, `derived_tan_delta`). Legend inside chart when both variants present.

### Explorer: Sidecar Download Buttons
MD · JSON format toggle and ↓ download button in sticky detail panel header.

### Explorer: Strip Plot Jitter Fix
Jitter now range-relative (`yRange * 0.01`) rather than value-relative. Fixes compressed-range fields like fidelity (99–100%).

### derive.py: Sheet Resistance Cascade
`_derive_sheet_resistance_from_resistivity()` added. `derive_all()` runs in dependency order. Kinetic inductance coverage: 7→15 samples.

### Manual Exclusions Mechanism
`data/ingested/exclusions.json` + `build_sqlite.py` support. Three current exclusions: Hays 2026 (theory proposal), Marcenac 2026 (NV center), WangX 2026 (ZnO donor). JSONL never modified — exclusions applied at build time only.

---

## Next Coding Priorities

### Track A: Baby QREM

**1. Material class defaults lookup table in `transmon_analytical_defaults.yaml`**
Currently a single tan_delta class default (8.1e-4, alpha-Ta on sapphire). Should be a material-keyed lookup table so Re, Nb, Al etc. get appropriate defaults rather than falling back to Ta. Structure:
```yaml
material_class_defaults:
  Ta:
    Tc_K: 4.4
    tan_delta_effective_surface: 8.1e-4   # alpha-Ta, Crowley 2023
  Re:
    Tc_K: 1.7
    tan_delta_effective_surface: null      # not yet characterized
  Nb:
    Tc_K: 9.2
    tan_delta_effective_surface: null
  Al:
    Tc_K: 1.2
    tan_delta_effective_surface: 2.0e-3
```
`t1_decomposition.py` looks up `derived_material` or `film_material` from the record. Falls back to single default if material not in table.

**2. Corpus-average PUKs per material class — two tiers**

Discussed May 21. Two distinct use cases, buildable in sequence:

**Tier 3 — Device property average (buildable now):** Query `records.db` grouped by `derived_material`, compute mean ± std of T1_us, T2_us across all samples of that class (minimum n≥3). Write as synthetic qubit profile YAMLs (e.g. `Ta_corpus_average.yaml`) that appear in the QREM dropdown. Provenance label: `[CORPUS AVERAGE — N samples]`. Simpler and immediately useful — no mapping layer needed.

**Tier 2 — Material property average (requires Stage C first):** Compute per-material-class averages of Tc_K, RRR, derived_Qi, derived_tan_delta, mean_free_path_nm. Feed through the Tier 2 mapping functions (t1_decomposition.py) to derive a predicted T1 — this is more physically meaningful than averaging T1 directly, because it answers "what T1 should a typical Ta film achieve given what the corpus says about its surface loss?" Propagate std through the mapping functions as uncertainty bounds.

**Key design decisions:**
- Aggregation unit: `derived_material` (same as Phase A stratification)
- Minimum threshold: n≥3 samples to report a corpus average; fall back to static CLASS_DEFAULT otherwise
- Report mean ± std — a corpus average T1 of 150µs ± 80µs tells a different story than 150µs ± 10µs
- Generated by a new script `compute_class_defaults.py` at build time, writing synthetic YAMLs to `hardware_profiles/qubits/`
- Only geometry-independent (intrinsic) fields averaged — same rule as schema promotion

**3. Decomposition panel: hide when tan_delta is CLASS_DEFAULT**
Currently the panel shows for all corpus profiles including those with no surface loss data (Wang, Bland). The correct criterion: only show when `tan_delta_provenance` is `MEASURED` or `DERIVED` — i.e. when the profile has real tan_delta data. Joshi profiles (tan_delta_effective_surface measured) should show; Wang and Bland (all class defaults for tan_delta) should not. This requires the `allDefaults` check to be reinstated based on `tan_delta_provenance` only.

**4. Stage 5 — Material property sliders**
Sliders for tan_delta, p_MS_pad, (eventually RRR, mean_free_path) that run *forward* through `t1_decomposition.py` → predicted T1 → into staircase and resource estimate. Forward direction is well-determined (one set of material inputs → one T1 output). The T1 and T2 coherence sliders remain for "what if" exploration; material sliders are a separate interactive layer. Depends on Stage 4 panel being stable first.

**5. Readout fidelity** — wire into QEC model (currently loaded but unused).

**6. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Ingester / Explorer

**6. Extraction prompt fix: normal_state_resistivity_uOhm_cm** — Bahrami 2026 and Yang 2026 resistivity values in catchall rather than named field. `build_sqlite.py` fallback and `derive.py` cascade in place — once prompt fixed and papers re-ingested, derived sheet resistance jumps from ~8 to ~22, kinetic inductance from 15 to ~22.

**7. Prev/next navigation in sidecar footer** — ← → arrows to cycle through samples in current filtered set. `getFilteredSamples()` array provides ordered list.

**8. Exclusions UI** — Management interface for `exclusions.json` in pipeline UI. Currently requires manual JSON editing.

**9. SI file linking** — DOI-based naming: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Ingester recognizes pair, ingests as single logical record. **Do not ingest Bland SI as standalone — wait for this feature.**

**10. Corpus expansion** — older literature ingestion. Collection in progress.

**11. Ic/Jc disambiguation** — `derive.py` functions, schema columns, extraction prompt fix.

### Track C: Longer Term

**12. Community upload feature** — public Explorer with PDF upload.

**13. Materials Predictor** — Gaussian process regression per material class.

**14. Tier 2 modular reconnection** — reconnect modular overhead cost model (Arquin) when Center-wide architecture research matures.

---

## Key Scientific Insights (May 21)

**On ε_ctrl as a controls baseline:**
- `transmon_baseline_2026` is not just a materials baseline — it is the **controls baseline**. It encodes pulse engineering quality (pulse errors, leakage, calibration) which is fixed by the control system and independent of which material is being studied.
- ε_ctrl = 5.83e-4, always. Corpus profiles contribute T1 and T2 only; ε_ctrl never changes.
- Previous bug: ε_ctrl was derived from the selected corpus profile. For Wang_2026_Transmon_2 (T2=51µs), coherence errors alone exceeded the baseline error budget, clamping ε_ctrl to 0. Fixed.

**On the Stage 4 decomposition panel design:**
- Panel is static and read-only — it shows what the model predicts for this specific sample's material data.
- Panel disappears when sliders are touched — the moment you move T1 or T2, you are no longer describing a real material, you're doing hypothetical exploration. The decomposition belongs to the material, not to the hypothetical.
- Stage 5 will add material property sliders (tan_delta, p_MS_pad) running *forward* through the loss model → predicted T1 → staircase. Forward direction is well-determined; inverse (slider T1 → material properties) is underdetermined and not attempted.

**On the decomposition panel visibility criterion:**
- Showing the panel when tan_delta is CLASS_DEFAULT is misleading — it implies the model knows something about the sample's surface loss when it doesn't.
- Correct criterion: show only when `tan_delta_provenance` is MEASURED or DERIVED. In practice: Joshi profiles (tan_delta_effective_surface measured from 71 resonators) → show. Bland and Wang (no surface loss data) → hide.
- TLS saturation explains why measured T1 can exceed single-photon model prediction — expected, not a bug.

---

## Key Scientific Insights (May 19)

**On Q_TLS,0 vs Qi:**
- Q_TLS,0 is the TLS-limited Q in the unsaturated (single-photon) limit, free of other loss contributions. Physically distinct from Qi — belongs in its own field.
- The Qi strip plot is effectively a "who made test resonators" plot. Qubit-focused papers appear in Q_TLS,0 instead.

**On ingester leakage:**
- C2QA acknowledgment alone is not sufficient for relevance. The paper must report superconducting materials characterization data.
- Three leakage classes: theory proposals (Hays), non-superconducting quantum systems (Marcenac NV center, WangX ZnO). Handle via `exclusions.json`.

**On resistivity in the corpus:**
- ρn well-measured in Bahrami 2026 and Yang 2026 but in catchall. Prompt fix pending.

---

## Key Scientific Insights (May 16)

**On p_MS and the resonator → qubit chain:**
- p_MS_resonator varies 30x across typical resonator geometries. Without knowing the resonator gap, Q_TLS,0 alone carries 6x uncertainty in tan_delta.
- Gold standard: fit Q_TLS,0 vs p_MS across many resonators → extract tan_delta directly (Joshi/Bland approach).
- Bland Figure S5: resonator Q_TLS,0 and transmon Q lie on the same line vs p_MS. Inversion chain correct.

**On TLS saturation:**
- Resonator measurements extract tan_delta at single-photon powers (TLS unsaturated). Qubits operate at multi-photon powers where TLS partially saturates. Measured T1 can legitimately exceed single-photon model prediction — correct behavior, not a bug.

**On junction TLS:**
- Single effective loss tangent (p_junction_surface × tan_delta_junction) is physically correct. Per-interface sum approach was wrong.

---

## Data Provenance Principles

**Peer review is inherited, not intrinsic.**

| Source | Confidence |
|---|---|
| Peer-reviewed paper (main text) | Highest |
| SI file linked to paper via DOI | High |
| arXiv preprint | Medium-high |
| External database entry with traceable DOI | Medium |
| External database entry, no traceable publication | Low |

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Exclusions are build-time overlays** — `exclusions.json` excludes records from the SQLite view without touching the JSONL.
- **Records are PUKs** — self-contained. Target architecture: QREM reads PUKs directly, no YAML export step.
- **AI proposes, humans approve** — every extracted value has confidence + source citation.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — correlations tested within material class. `derived_material` drives Phase A; `sim_material_class` drives Explorer sidebar.
- **Schema evolution is frequency-driven** — geometry-independent properties only.
- **Materials-first estimation** — gate fidelity is an output, not an input.
- **ε_ctrl is fixed to the controls baseline** — `transmon_baseline_2026` is the controls baseline. Corpus profiles contribute T1 and T2 only. ε_ctrl = 5.83e-4, always.
- **The estimator always estimates** — tiered fallback: `[MEASURED]` → `[DERIVED]` → `[CLASS DEFAULT]` → `[ASSUMED]`.
- **Stage 4 decomposition panel is read-only** — disappears when sliders touched. Stage 5 adds forward-direction material sliders.
- **Explorer is the Explorer** — literature database and discovery tool, not a physics inference engine.
- **Resonator is calibration, not loss channel** — v2.5 model. Qi → tan_delta → pad T1, never Qi/ω directly as qubit T1.
- **General solutions over one-offs** — new derived fields follow the established `derived_X` fallback pattern.

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py

# Baby QREM (port 8000)
cd "2026-04 c2qa_qrem" && python3 scripts/serve.py

# Rebuild SQLite after any JSONL, build_sqlite.py, or exclusions.json changes
cd ingester && python3 build_sqlite.py

# T1 decomposition (validation)
cd src/qrem
python3 t1_decomposition.py hardware_profiles/mapping_models/example_material_record.yaml hardware_profiles/mapping_models/transmon_analytical_defaults.yaml

# Backfill similarity profiles — ALWAYS check line counts before swapping
python3 backfill_similarity_profiles.py --filter <pattern>
wc -l ../data/ingested/records_with_profiles.jsonl  # must match records.jsonl
wc -l ../data/ingested/records.jsonl
# Only if counts match:
mv ../data/ingested/records.jsonl ../data/ingested/records_backup.jsonl
mv ../data/ingested/records_with_profiles.jsonl ../data/ingested/records.jsonl
python3 build_sqlite.py

# Standard commit
git add . && git add ../data/ingested/records.db && git commit -m "description" && git push
```

---

*Last updated: May 21, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
