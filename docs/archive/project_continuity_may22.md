# C2QA QREM — Project Continuity & Coding Priorities
## Updated May 22, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Stages 1–4 complete. T1 loss channel breakdown panel operational. Panel shows only when real TLS data (measured tan_delta, Qi, or Q_TLS_0) is present in profile — hides for CLASS_DEFAULT. ε_ctrl fixed to controls baseline. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | ✅ Operational. Three-pass pipeline. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | ✅ Live at https://c2qa-materials-explorer.onrender.com. |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | ✅ Operational. Run May 22 — see Mining State below. |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | `t1_decomposition.py` complete and validated. UI panel integrated. Stage 5 (material property sliders → T1) planned. |

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

## Recent Completions (May 22, 2026)

### Profile Loader Bug Fix — Critical

`profile_loader.py` was silently dropping the `materials`, `device`, and `surface_participation` sections from every qubit YAML on load. This meant `t1_decomposition.py` never received any measured material data — all decompositions fell back to CLASS_DEFAULT regardless of what was in the YAML. Fixed by adding these three sections to `SECTION_KEYS["qubits"]`. This was the root cause of the decomposition panel always showing CLASS_DEFAULT.

### generate_qubit_profile.py — Three New Derived Field Fallbacks

The profile generator now correctly implements the `derived_X` fallback pattern for three fields, matching `build_sqlite.py`:

- **T2**: `T2_echo_us` → `T2_ramsey_us` — previously only checked echo, missing Ramsey-only samples
- **Qi**: `Qi_single_photon` → `Qi_internal` — previously looked up wrong column name (`Qi_internal_quality_factor` vs actual DB column `Qi_internal`)
- **tan_delta**: new field, `tan_delta_effective_surface` → `loss_tangent_interface` → `loss_tangent_substrate` — was completely absent before

Each field is tagged with which variant was used (e.g. `[MEASURED — T2_ramsey]`).

### t1_decomposition.py — tan_delta Path Fix

Added `materials.tan_delta` as a Priority 1 fallback path in `_extract_tan_delta()`, alongside the existing `interfaces.tan_delta_effective_surface` path. The YAML generator writes to `materials.tan_delta`; the decomposition now reads from it.

### qrem_ui.html — Decomposition Panel Show/Hide

Panel now hides when `tan_delta_provenance === 'CLASS_DEFAULT'`. Shows only when real TLS data exists in the profile. In practice: profiles with measured `tan_delta_effective_surface` (e.g. Chang 2025, Joshi profiles) show the panel; profiles with no surface loss data (Wang, Bland, baseline) correctly hide it.

### build_sqlite.py — Three Promoted Fields Restored

`mean_free_path_nm`, `vortex_activation_temperature_K`, and `kinetic_inductance_sheet_pH_sq` were documented as promoted in May 9 schema update but were missing from `build_sqlite.py`. Restored as named columns, populated from catchall at build time.

### pipeline_mining.py — FIELD_MAP Updates

Updated for schema evolution since last mining run:
- `"qtls"` → `Q_TLS_0` (was wrongly `Qi_internal` — scientifically incorrect)
- Added `"qtls,0"`, `"unsaturated tls quality"` etc. → `Q_TLS_0`
- `"loss tangent"`, `"tan delta"`, `"surface loss tangent"` → `derived_tan_delta`
- `"surface participation"`, `"pms"` → `p_MS_resonator` (now named column)
- Added `"resonator gap width"`, `"gap width"` → `resonator_gap_width_um`
- `T2_ramsey_us`, `qubit_frequency_GHz` updated from `json:` to named columns

### Corpus Mining Run — May 22

15 evidence tables sufficient for Phase B. Key results:
- No new positive findings. Most hypotheses correctly flagged as inconclusive or unsupported — expected at current corpus size.
- Three `derived_tan_delta_vs_derived_tan_delta` findings are schema artifacts (both sides map to same field) — should be rejected. Root cause: Joshi/Wang correlations comparing β-Ta vs α-Ta surface loss both map to `derived_tan_delta`. Cross-material comparisons of the same quantity need a different representation in Phase A.
- Previous positive finding (Tc vs deposition temperature in Ta-Hf) is missing — the correlation catchall item that seeded it is no longer in the corpus. The Yang 2026 PNAS paper contains the data clearly (Table 2 shows monotonic Tc suppression 550→850°C), but the current ingestion missed this correlation. The finding remains in `findings.jsonl` (append-only) but is no longer supported by the live corpus.
- `Tc_K_vs_film_thickness_nm__nbse2` (conf 0.65) remains the one partially-supported finding, consistent with prior approval.

---

## Next Coding Priorities

### Priority 1 — Corpus-Average PUKs (Track A)

**This is the next big thing.** The current architecture has a single `transmon_analytical_defaults.yaml` that applies CLASS_DEFAULT values to all materials. The goal is to replace this with per-material YAML files whose values are computed from the corpus — so class defaults improve automatically as more papers are ingested.

This is two steps that form one coherent transition:

**Step 1 — `compute_class_defaults.py` (new script):** Queries `records.db` grouped by `derived_material`, computes mean ± std of device properties (T1_us, T2_us) and material properties (Tc_K, derived_tan_delta, derived_Qi, mean_free_path_nm) for each material class with n≥3 samples. Writes synthetic qubit profile YAMLs (e.g. `Ta_corpus_average.yaml`) to `hardware_profiles/qubits/`. Provenance label: `[CORPUS AVERAGE — N samples]`. Run standalone for now; eventually called at end of `build_sqlite.py`.

**Step 2 — Per-material lookup in `transmon_analytical_defaults.yaml`:** Expand from single defaults to material-keyed table. `t1_decomposition.py` looks up by `derived_material` or `film_material`, falls back to single default if material not in table.

Key design decisions (discussed May 22):
- Aggregation unit: `derived_material` (same as Phase A stratification)
- Minimum threshold: n≥3 to report corpus average; fall back to static CLASS_DEFAULT otherwise
- Report mean ± std — uncertainty matters
- Only geometry-independent (intrinsic) fields averaged
- Tier 3 (device property average) is buildable now; Tier 2 (material property → predicted T1) requires the mapping layer

### Priority 2 — Decomposition Panel: Hide When tan_delta is CLASS_DEFAULT for Specific Material

Currently the panel shows for Chang (measured tan_delta) and hides for everything else. But as more profiles are regenerated, profiles with Qi but no p_MS_resonator will have Qi populated but tan_delta still CLASS_DEFAULT — the panel correctly hides for these. This is working correctly. No code change needed; just regenerate profiles from Explorer as needed.

### Priority 3 — Centralized Field Registry (Track B)

**New priority identified May 22.** The same field name mappings are maintained in four separate places:
- `FIELD_MAP` in `pipeline_mining.py`
- `DERIVED_MATERIAL_FIELDS` / `MATERIAL_FIELD_MAPPINGS` in `generate_qubit_profile.py`
- Column definitions in `build_sqlite.py`
- Priority chains in `t1_decomposition.py`

These drift out of sync as schema evolves (as happened with `Qi_internal` column name, `json:` vs named column prefixes, etc.). A shared `schema_fields.py` in the ingester directory would define canonical field names, fallback chains, and text→field mappings once, imported by all consumers. Design requires care — each consumer uses the registry differently. Deliberate design session needed before coding.

### Track A: Baby QREM

**4. Decomposition panel: Qi path** — when `Qi` and `p_MS_resonator` are both non-null in a profile, `t1_decomposition.py` can derive tan_delta via the Joshi inversion. The panel should show for these profiles. Currently the panel only shows when `tan_delta` is directly measured. The Qi path is implemented in `t1_decomposition.py` but `p_MS_resonator` is rarely reported — this will become relevant as more papers with resonator geometry data are ingested.

**5. Stage 5 — Material property sliders** — tan_delta, p_MS_pad sliders running forward through `t1_decomposition.py` → predicted T1 → staircase. Forward direction is well-determined. Depends on corpus-average PUKs being stable first.

**6. Readout fidelity** — wire into QEC model (currently loaded but unused).

**7. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Ingester / Explorer

**8. Missing correlation: Yang 2026 Ta-Hf deposition temperature vs Tc** — Table 2 of the PNAS paper clearly shows monotonic Tc suppression from 550→850°C deposition temperature, but current ingestion missed this as a correlation item. Options: manually add to JSONL catchall, or re-ingest and hope extraction catches it. The finding remains in `findings.jsonl` but is unsupported by the live corpus.

**9. Extraction prompt fix: normal_state_resistivity_uOhm_cm** — Bahrami 2026 and Yang 2026 resistivity values in catchall rather than named field. `build_sqlite.py` fallback in place — once prompt fixed and papers re-ingested, derived sheet resistance coverage improves significantly.

**10. Prev/next navigation in sidecar footer** — ← → arrows to cycle through samples in current filtered set.

**11. Exclusions UI** — Management interface for `exclusions.json` in pipeline UI. Currently requires manual JSON editing.

**12. SI file linking** — DOI-based naming: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Do not ingest SI files as standalone in the meantime.

**13. Corpus expansion** — older literature ingestion. Collection in progress.

### Track C: Longer Term

**14. Community upload feature** — public Explorer with PDF upload.

**15. Materials Predictor** — Gaussian process regression per material class.

**16. Tier 2 modular reconnection** — reconnect modular overhead cost model (Arquin) when Center-wide architecture research matures.

---

## Key Scientific Insights (May 22)

**On the profile loader bug:**
- `profile_loader.py` `SECTION_KEYS["qubits"]` was missing `materials`, `device`, `surface_participation`. These sections were silently dropped on every profile load, meaning `t1_decomposition.py` never saw any measured material data. All decompositions used CLASS_DEFAULT. Fixed with one line.
- This bug had been present since Stage 4 was built — the decomposition panel was never actually using corpus data until today.

**On corpus mining and the self-referential hypothesis:**
- `derived_tan_delta_vs_derived_tan_delta` is a Phase A artifact: the Joshi/Wang correlations comparing β-Ta vs α-Ta surface loss both map to `derived_tan_delta` on both sides. This is correct FIELD_MAP behavior — both quantities are surface loss tangents — but the resulting hypothesis is scientifically vacuous. Cross-material comparisons of the same quantity need a different Phase A representation, not a FIELD_MAP fix.

**On corpus mining value:**
- Mining correctly identifies what the corpus cannot yet support. Honest negatives and inconclusives at current corpus size are real scientific results, not failures. The pipeline is working correctly. Value increases as corpus grows.

**On the tan_delta show/hide criterion:**
- Show the panel if any of these are non-null in the profile: `tan_delta`, `Q_TLS_0`, or (`Qi` AND `p_MS_resonator`). Currently only `tan_delta` gates the panel in practice, because `Q_TLS_0` is rarely reported and `p_MS_resonator` is rarely reported alongside `Qi`. This is correct and will naturally expand as more papers with resonator geometry data are ingested.

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Exclusions are build-time overlays** — `exclusions.json` excludes records from the SQLite view without touching the JSONL.
- **Records are PUKs** — self-contained. Target architecture: QREM reads PUKs directly, no YAML step.
- **AI proposes, humans approve** — every extracted value has confidence + source citation.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — correlations tested within material class. `derived_material` drives Phase A; `sim_material_class` drives Explorer sidebar.
- **Schema evolution is frequency-driven** — geometry-independent properties only.
- **Materials-first estimation** — gate fidelity is an output, not an input.
- **ε_ctrl is fixed to the controls baseline** — `transmon_baseline_2026` encodes pulse engineering quality. Corpus profiles contribute T1 and T2 only. ε_ctrl = 5.83e-4, always.
- **The estimator always estimates** — tiered fallback: `[MEASURED]` → `[DERIVED]` → `[CORPUS AVERAGE]` → `[CLASS DEFAULT]` → `[ASSUMED]`.
- **Stage 4 decomposition panel is read-only** — disappears when sliders touched. Stage 5 adds forward-direction material sliders.
- **Resonator is calibration, not loss channel** — v2.5 model. Qi → tan_delta → pad T1, never Qi/ω directly as qubit T1.
- **General solutions over one-offs** — new derived fields follow the established `derived_X` fallback pattern.
- **Don't ingest SI files as standalone** — wait for SI file linking implementation.

---

## Data Provenance Hierarchy

| Tier | Source | Label |
|---|---|---|
| 1 | Directly measured in the paper | `[MEASURED]` |
| 2 | Derived from measured quantities via physics formulas | `[DERIVED]` |
| 3 | Corpus-computed average for this material class (n≥3) | `[CORPUS AVERAGE — N samples]` ← planned |
| 4 | Static value for this material class | `[CLASS DEFAULT]` |
| 5 | Baseline profile assumption | `[ASSUMED]` |

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py

# Baby QREM (port 8000)
cd "2026-04 c2qa_qrem" && python3 scripts/serve.py

# Rebuild SQLite after any JSONL, build_sqlite.py, or exclusions.json changes
cd ingester && python3 build_sqlite.py

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

*Last updated: May 22, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
