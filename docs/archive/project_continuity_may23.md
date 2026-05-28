# C2QA QREM — Project Continuity & Coding Priorities
## Updated May 23, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Stages 1–4 complete. T1 loss channel breakdown panel operational. Panel shows only when real TLS data (measured tan_delta, Qi, or Q_TLS_0) is present in profile — hides for CLASS_DEFAULT. ε_ctrl fixed to controls baseline. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | ✅ Operational. Three-pass pipeline. Prompt updated May 23 for participation matrix papers. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | ✅ Live at https://c2qa-materials-explorer.onrender.com. |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | ✅ Operational. Run May 22 — see Mining State below. |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | `t1_decomposition.py` complete and validated. UI panel integrated. Per-material corpus-average defaults now wired in (May 23). Stage 5 (material property sliders → T1) planned. |

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

## Recent Completions (May 23, 2026)

### Corpus-Average PUKs — Complete

The single `transmon_analytical_defaults.yaml` fallback has been replaced with a full set of per-material YAMLs, computed from the corpus and regenerating automatically as papers are ingested.

**Directory rename:**
- `mapping_models/` → `material_defaults/`
- `transmon_analytical_defaults.yaml` → `transmon_general_defaults.yaml`

**New script: `compute_class_defaults.py`**

Queries `records.db` grouped by `derived_material`, generates two files per material class (n≥3):

- `hardware_profiles/qubits/{Material}_corpus_average.yaml` — device performance profile with corpus-averaged T1, T2, gate fidelities (when N≥3). Appears in Baby QREM qubit dropdown. Mode 1 use case: "I want to make qubits from tantalum."
- `hardware_profiles/material_defaults/{Material}_material_defaults.yaml` — material property defaults for `t1_decomposition.py`. Corpus-averaged fields: tan_delta, Tc_K, mean_free_path_nm, Qi. Geometry/system fields (p_MS_pad, junction TLS, QP floor, radiation) carried from general defaults with CLASS_DEFAULT. Mode 2 use case: "I made a Ta film — fill in what I didn't measure."

Files generated for 8 material classes: Ta, Al, Re, NbSe2, PtSi, Ta-Hf, NbN, Mo3Al2C. TaN and Nb below threshold (N<3).

Mixed-variant composition tracked in provenance, e.g.: `"6 x loss_tangent_interface, 1 x tan_delta_effective_surface"`.

Run: `cd ingester && python3 compute_class_defaults.py`
Dry run: `python3 compute_class_defaults.py --dry-run --material Ta`

**`generate_qubit_profile.py` updated:**

Now writes material-specific `defaults_path` into provenance. When generating a profile for a Ta sample, writes `../material_defaults/Ta_material_defaults.yaml` instead of the general defaults. Falls back to `transmon_general_defaults.yaml` for unknown materials.

The `_resolve_defaults_path()` function checks whether `{material}_material_defaults.yaml` exists before routing.

**Two-mode architecture:**
- Mode 1 — "make qubits from tantalum": select `Ta_corpus_average.yaml` in QREM dropdown. T1/T2 from corpus mean.
- Mode 2 — "I measured some properties of my Ta film": load partial measurement profile. Missing material fields filled from `Ta_material_defaults.yaml` corpus averages. Provenance tags show which values were measured vs corpus-average vs class-default.

**Data provenance hierarchy now operational (all tiers):**

| Tier | Source | Label |
|---|---|---|
| 1 | Directly measured in the paper | `[MEASURED]` |
| 2 | Derived from measured quantities via physics formulas | `[DERIVED]` |
| 3 | Corpus-computed average for this material class (n≥3) | `[CORPUS AVERAGE — Ta, N=35]` |
| 4 | Static value for this material class | `[CLASS DEFAULT]` |
| 5 | Baseline profile assumption | `[ASSUMED]` |

### Extraction Prompt Updates (May 23)

Two targeted improvements to `prompts.py` for participation matrix style papers (Wang 2026, Ganjam 2024):

1. **`tan_delta_effective_surface` from Γ_surf:** Papers using participation matrix inversion report Γ_surf directly in loss factor tables. This IS tan_delta_effective_surface. Prompt now explicitly covers this case with examples including `Γ_surf = 3.6×10⁻⁴ → tan_delta_effective_surface`.

2. **`p_MS_pad` from participation tables:** Participation tables with a "Transmon" column contain p_MS_pad in the transmon column. Prompt now explicitly says to look for this.

**Validation — Wang 2026 re-ingested:** Now correctly extracts `p_MS_pad = 4.9e-5` for all 5 transmons, and `tan_delta_effective_surface = 3.6e-4` for Tripole 1 and the aggregate loss budget record.

### Processed Ledger Structure — Documented

The processed ledger (`data/ingested/processed_ledger.json`) is a dict with a `'processed'` key containing a **list of dicts**. Each dict has: `filename`, `doi` (may be null), `date_processed`, `outcome`, `reason`.

To find entries for re-ingestion:
```bash
python3 -c "import json; ledger = json.load(open('../data/ingested/processed_ledger.json')); entries = ledger.get('processed', []); [print(repr(e['filename'])) for e in entries if 'keyword' in (e.get('filename') or '').lower()]"
```

To remove entries for re-ingestion (example: WangY):
```bash
python3 -c "
import json
path = '../data/ingested/processed_ledger.json'
ledger = json.load(open(path))
before = len(ledger['processed'])
ledger['processed'] = [e for e in ledger['processed'] if 'WangY' not in (e.get('filename') or '')]
after = len(ledger['processed'])
json.dump(ledger, open(path, 'w'), indent=2)
print(f'Removed {before - after} entries')
"
```

---

## Next Coding Priorities

### Priority 1 — Wire Corpus Averages into Stage 4 Panel (Track A)

The corpus-average YAMLs are generated and `generate_qubit_profile.py` routes to them correctly. But existing corpus-derived profiles in `qubits/` still point to the old `mapping_models/transmon_analytical_defaults.yaml` path. Two steps:

1. **Regenerate all corpus profiles** — click "Generate Qubit Profile" in Explorer for each sample, or write a batch script that calls `generate_qubit_profile.py` for all samples in the DB. This will update `defaults_path` to the material-specific file.

2. **Stage 5 — Material property sliders** — tan_delta, p_MS_pad sliders running forward through `t1_decomposition.py` → predicted T1 → staircase. Forward direction is well-determined. Depends on corpus-average PUKs being stable first. Now they are.

### Priority 2 — Centralized Field Registry (Track B)

The same field name mappings maintained in four places:
- `FIELD_MAP` in `pipeline_mining.py`
- `DERIVED_MATERIAL_FIELDS` / `MATERIAL_FIELD_MAPPINGS` in `generate_qubit_profile.py`
- Column definitions in `build_sqlite.py`
- Priority chains in `t1_decomposition.py`

A shared `schema_fields.py` would define canonical field names, fallback chains, and text→field mappings once. Design requires care — deliberate design session needed before coding.

### Track A: Baby QREM

**3. Decomposition panel: Qi path** — when `Qi` and `p_MS_resonator` are both non-null, `t1_decomposition.py` can derive tan_delta. Panel should show for these profiles. Currently only tan_delta gates the panel.

**4. Stage 5 — Material property sliders** — see Priority 1 above.

**5. Readout fidelity** — wire into QEC model (currently loaded but unused).

**6. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Ingester / Explorer

**7. Batch profile regeneration** — script to regenerate all corpus-derived qubit profiles in `qubits/` so they point to material-specific defaults. Currently requires manual Explorer clicks per sample.

**8. Missing correlation: Yang 2026 Ta-Hf deposition temperature vs Tc** — Table 2 of the PNAS paper shows monotonic Tc suppression from 550→850°C, but current ingestion missed this as a correlation item. The finding remains in `findings.jsonl` but is unsupported by the live corpus.

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

## Key Scientific Insights (May 23)

**On corpus-average PUKs and gate fidelities:**
- Gate fidelities are `[ASSUMED]` in corpus-average YAMLs because materials papers almost never report gate fidelities — they measure T1, T2, and surface loss, not randomized benchmarking. Only 2 Ta samples in the corpus have gate fidelity data (Bland_2025_Qubit_47 at 99.994%, Xia_2025 at 99.604%). This is correct and honest — not an extraction failure.
- The infrastructure is in place: `DEVICE_AVG_FIELDS` now includes gate fidelities. When N≥3 samples report them, corpus averages will appear automatically.

**On participation matrix papers:**
- Papers using participation matrix inversion (Wang 2026, Ganjam 2024) report Γ_surf directly — this IS tan_delta_effective_surface, even though it comes from matrix inversion rather than a Q_TLS,0 vs p_MS plot. The prompt now correctly handles this.
- Wang 2026 extraction quality is now good: all 5 transmons with T1/T2, p_MS_pad = 4.9e-5, tan_delta_effective_surface = 3.6e-4 for the tripole resonator calibration.

**On prompt evolution philosophy:**
- Resist whack-a-mole prompt changes. Each addition should be general enough to fire on multiple papers. The Γ_surf fix covers all participation matrix papers (Wang, Ganjam, and future Yale-style papers). The p_MS_pad table fix is less critical at current corpus size but correct.
- The prompt is already long and detailed. More specificity can hurt by making the model overthink. Stop at "good enough."

**On the two-mode architecture:**
- Mode 1 (pick a material) and Mode 2 (partial measurements + fill-in) are now both supported by the per-material YAML infrastructure. Mode 2 is more scientifically powerful — it answers "given what I measured, what T1 should my device achieve?" rather than just looking up a corpus average.

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
- **Prompt evolution: resist whack-a-mole** — only add guidance that fires on multiple paper types, not one-off fixes for individual papers.
- **Per-material defaults over single general defaults** — `{Material}_material_defaults.yaml` files replace the single `transmon_general_defaults.yaml` as the corpus grows. General defaults remain as fallback of last resort.

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py

# Baby QREM (port 8000)
cd "2026-04 c2qa_qrem" && python3 scripts/serve.py

# Rebuild SQLite after any JSONL, build_sqlite.py, or exclusions.json changes
cd ingester && python3 build_sqlite.py

# Regenerate per-material corpus-average YAMLs (run after build_sqlite.py)
cd ingester && python3 compute_class_defaults.py

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

# Find and remove ledger entries for re-ingestion
python3 -c "import json; ledger = json.load(open('../data/ingested/processed_ledger.json')); entries = ledger.get('processed', []); [print(repr(e['filename'])) for e in entries if 'keyword' in (e.get('filename') or '').lower()]"
```

---

*Last updated: May 23, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
