# C2QA QREM — Project Continuity & Coding Priorities
## Updated July 6, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Stages 1–4 complete. T1 loss channel breakdown panel operational. ε_ctrl now specified directly in YAML rather than back-calculated. Live at https://c2qa-baby-qrem.onrender.com |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | ✅ Operational. Prompt updated to v4 (July 2026) with fabrication process chemistry fields. Full re-ingestion of 35 papers pending. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | ✅ Live at https://c2qa-materials-explorer.onrender.com. Five tabs: Explore, Search, Findings, Catchall, Papers. |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | ✅ Operational. Run May 22 — see Mining State below. |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | `t1_decomposition.py` complete and validated. UI panel integrated. Per-material corpus-average defaults wired in. **Priority: extract mapping layer as standalone feed-anything service — see Track D below.** |

---

## How They Connect

```
Scientific Papers
      ↓
[2] Publications Ingester (Pass 1 → Pass 2 → Pass 3)
      ↓
[3] Materials Database
    (Tc, RRR, Qi, T1, fab process, derived quantities, catchall, similarity_profiles)
      |
      |── Measured device performance (T1, T2, gate fidelity)
      |   → Hardware Profile Updater → qubit profile YAML   ← transitional
      |   [target: QREM reads PUKs directly, no YAML step]
      |                                        ↓
      |── All corpus records              [1] Baby QREM
      |   → [4] Corpus Mining Pipeline        ↑
      |        → findings.jsonl               |
      |        → [6] Mapping Layer ───────────┘
      |                    |
      |                    └── [standalone API — feeds any tool]
      |                         Microsoft QRE, Stim, HetArch, etc.
      |
      └── Material properties (Tc, RRR, loss tangent)
          → [5] Materials Predictor → [6] Mapping Layer
```

**The scientific question the pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and run this quantum circuit, how many physical qubits do I need?"*

---

## Recent Completions (July 6, 2026)

### Fabrication Process Chemistry Schema and Prompt (July 2026)

Following input from the C2QA materials group and a colleague reviewer, designed and implemented fabrication process chemistry extraction:

- **Schema v0.15** — Block 2.5 added with seven named free-text fields for base-layer processing: `substrate_prep_before_deposition`, `in_situ_substrate_bake_temperature_C`, `film_deposition_conditions`, `film_etch_chemistry`, `resist_strip_chemistry`, `post_fabrication_surface_treatment`, `dicing_protocol`. Five junction process chemistry fields added/updated in Block 2.3: `junction_pre_deposition_surface_treatment` (renamed and expanded), `junction_developer`, `junction_chamber_vacuum`, `junction_oxidation_protocol` (renamed), `junction_liftoff_chemistry`. New `fabrication_detail` catchall type added.
- **prompts.py v4** — FABRICATION PROCESS CHEMISTRY section added after RESONATOR GEOMETRY. Directive with examples following established style. Guidance framed to avoid over-anchoring on section titles. Paper citations removed; scientific context expressed as general principles.
- **Test ingestion** — tested on two papers using `--papers-dir`/`--out`/`--ledger` flags to keep test runs isolated from main corpus:
  - Joshi 2026 (beta-Ta transmon, 14 samples): all fabrication fields correctly populated including substrate-dependent in_situ bake temperatures (300°C sapphire, 600°C silicon), full etch parameters, cold developer (−10°C), UHV Plassys reference. Junction bilayer resist stack in fabrication_details catchall. QCage packaging captured.
  - Olszewski 2026 (Nb/Si process comparison, 14 samples): AZ 300T vs 1165 resist strip correctly differentiated across all sample rows; substrate prep, etch, post-fab treatment, dicing all correctly vary per sample. The three planned derived columns (`derived_resist_strip_family`, `derived_post_fab_treatment_family`, `derived_junction_vacuum_class`) will cleanly differentiate these by keyword matching.
- **Visualization design** — two planned Explorer modes documented: (1) strip chart group-by using three derived columns (same pattern as `derived_substrate`); (2) dedicated Fabrication tab with table view, one row per sample. See `fabrication_viz_design_note.md`.
- **Promotion rule relaxation** — fabrication process fields are promotable on frequency + scientific relevance, not the geometry-independence criterion that applies to material property fields.

### Recent Completions (June 12–15, 2026)

- Baby QREM UI improvements for C2QA leadership demo (metric card text, chart title, circuit details turndown, BV circuit added)
- ε_ctrl now directly specified in `transmon_baseline_2026.yaml` rather than back-calculated
- `compute_class_defaults.py` auto-called at end of `build_sqlite.py`
- Papers tab added to Explorer (fifth tab, DOE demo prep)
- Unknown sidebar filter fixed — was filtering on `sim_material_class` instead of `derived_material`
- Material colors preserved on group-by switch in strip/scatter chart

---

## Next Coding Priorities

### Priority 1 — Re-ingest All 35 Papers with v4 Prompt (Track B)

Full re-ingestion of all papers that passed triage using the new `prompts.py` v4. This populates fabrication chemistry fields across the corpus for the first time.

Steps:
1. Reset the corpus (preserve `findings.jsonl`)
2. Run `pipeline_ingest.py` against the full papers folder
3. Run `build_sqlite.py` — but first add Block 2.5 named columns (see Priority 2)
4. Run `compute_class_defaults.py`
5. Inspect fabrication field coverage in the DB

Watch for: response truncation on multi-sample papers (Bland 2025 with 57 qubits is the risk case). If truncation observed, implement Pass 2.5 architecture (see Known Limitations in ingester spec).

**Note on scope:** the steps above describe a full corpus reset (all ~35 papers re-ingested at once).
For re-ingesting a small subset (e.g. testing v4 prompt changes, backfilling a few papers after a
schema change), use the targeted re-ingestion procedure in "Running the System" instead — it only
removes the relevant entries from `processed_ledger.json` and leaves everything else untouched.

### Priority 2 — Add Block 2.5 Columns to `build_sqlite.py` (Track B)

Before re-ingestion rebuilds the DB, add named columns for the seven Block 2.5 fields and the three planned derived columns:

**Named columns to add:**
- `substrate_prep_before_deposition` (text)
- `in_situ_substrate_bake_temperature_C` (real)
- `film_deposition_conditions` (text)
- `film_etch_chemistry` (text)
- `resist_strip_chemistry` (text)
- `post_fabrication_surface_treatment` (text)
- `dicing_protocol` (text)
- Junction fields: `junction_pre_deposition_surface_treatment`, `junction_developer`, `junction_chamber_vacuum`, `junction_oxidation_protocol`, `junction_liftoff_chemistry` (all text)

**Derived columns to add (keyword matching):**
- `derived_resist_strip_family` — from `resist_strip_chemistry`: AZ300T-family, NMP-family (1165/Remover PG), acetone-only, none, other
- `derived_post_fab_treatment_family` — from `post_fabrication_surface_treatment`: piranha+BOE, BOE-only, HF-only, acid-substitute, none, other
- `derived_junction_vacuum_class` — from `junction_chamber_vacuum`: UHV, HV, unknown

These three derived columns become new group-by axes in the Explorer strip chart alongside Film material / Substrate / Deposition method.

### Priority 3 — Wire Corpus Averages into Stage 4 Panel (Track A)

The corpus-average YAMLs are generated and `generate_qubit_profile.py` routes to them correctly. But existing corpus-derived profiles in `qrem/hardware_profiles/qubits/` still point to old defaults paths. Two steps:

1. **Regenerate all corpus profiles** — batch script calling `generate_qubit_profile.py` for all samples in the DB.
2. **Stage 5 — Material property sliders** — tan_delta, p_MS_pad sliders running forward through `t1_decomposition.py` → predicted T1 → staircase.

### Track A: Baby QREM

**4. Decomposition panel: Qi path** — when `Qi` and `p_MS_resonator` are both non-null, `t1_decomposition.py` can derive tan_delta. Panel should show for these profiles. Currently only tan_delta gates the panel.

**5. Stage 5 — Material property sliders** — see Priority 3 above.

**6. Readout fidelity** — wire into QEC model (currently loaded but unused).

**7. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Explorer

**8. Fabrication tab** — table view in Explorer, one row per sample, columns for Block 2.5 named fabrication fields. Sortable, filterable, click row opens detail drawer. Phase 2 after corpus populated with v4 prompt.

**9. Missing correlation: Yang 2026 Ta-Hf deposition temperature vs Tc** — Table 2 of the PNAS paper shows monotonic Tc suppression from 550→850°C, but current ingestion missed this as a correlation item. The finding remains in `findings.jsonl` but is unsupported by the live corpus.

**10. Extraction prompt fix: normal_state_resistivity_uOhm_cm** — Bahrami 2026 and Yang 2026 resistivity values in catchall rather than named field. `build_sqlite.py` fallback in place — once prompt fixed and papers re-ingested, derived sheet resistance coverage improves significantly.

**11. Prev/next navigation in sidecar footer** — ← → arrows to cycle through samples in current filtered set.

**12. Exclusions UI** — management interface for `exclusions.json` in pipeline UI. Currently requires manual JSON editing.

**13. SI file linking** — DOI-based naming: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Do not ingest SI files as standalone in the meantime. SI linking is especially important now that Block 2.5 fabrication fields are often only in the SI.

**14. Corpus expansion** — older literature ingestion. Collection in progress.

### Track C: Longer Term

**15. Centralized Field Registry** — the same field name mappings maintained in four places. A shared `schema_fields.py` would define canonical field names, fallback chains, and text→field mappings once. Design requires care — deliberate design session needed before coding.

**16. Community upload feature** — public Explorer with PDF upload.

**17. Materials Predictor** — Gaussian process regression per material class.

**18. Tier 2 modular reconnection** — reconnect modular overhead cost model (Arquin) when Center-wide architecture research matures.

### Track D: Standalone Mapping Layer

**Strategic decision from June 2026 leadership meeting:** Extract the Materials-to-Device Mapping Layer as a standalone, feed-anything service.

**The vision:**
```
Materials Explorer (Tc, RRR, loss tangent, mean free path)
         ↓
[Mapping Layer API] — standalone service
         ↓
  predicted T1, T2, gate fidelity + provenance
         ↓
    ↙              ↘
Baby QREM      Microsoft QRE / Stim / HetArch / anything
```

**Design questions to resolve in next session:**
- What is the API contract? (inputs, outputs, format)
- How does provenance flow through to the consumer tool?
- What is the relationship to the existing `t1_decomposition.py`?
- Should this be a REST endpoint on the Explorer server, or a separate service?

---

## Key Scientific Insights

**On fabrication process chemistry and performance (July 2026):**
- Resist strip chemistry choice directly determines Qi in halogen-etched Nb/Si systems — AZ300T removes BCl3/Cl2 etch residues that NMP-family baths (1165, Remover PG) do not. This is now a named schema field and queryable corpus axis.
- Junction deposition vacuum (HV vs UHV) has been shown to be a primary determinant of T2E — now captured in `junction_chamber_vacuum` and will yield a binary derived column (`derived_junction_vacuum_class`) for corpus-level analysis.
- Post-fabrication surface treatment is material-specific — some films (Ta) tolerate and benefit from piranha+BOE; others (Re) require substitute chemistries. Authors sometimes flag the substitution explicitly, which is itself scientifically significant.
- In-situ substrate bake temperature is substrate-dependent within the same study (Joshi: 300°C for sapphire, 600°C for silicon) — extract per sample, not per paper.

**On ε_ctrl as the fundamental floor (June 2026):**
- With ε_ctrl = 5.83e-4, the physical error rate has a floor regardless of how good T1 and T2 get. For 99% success on depth-11 circuits, the floor is d=5 — already reachable. For 99.99%, the floor is d=9 — unreachable no matter how good the material.
- When ε_ctrl is 58% of the error budget (as at T1=200µs), the tool is correctly diagnosing that the bottleneck has shifted from materials to control engineering. This is a real scientific output, not a limitation.

**On Baby QREM's scope and positioning (June 2026):**
- Baby QREM is intentionally simplified — single-module, analytical QEC, no idling errors, no time-domain simulation. This is by design, not a gap to close.
- Target audiences: (1) materials scientists who need intuition for how T1 improvements translate to computational resources; (2) any resource estimation tool that needs corpus-backed material-to-device predictions.
- Current demo circuits (depth 8-11) are too shallow to stress the resource estimation meaningfully. Frame as: "These simple circuits let you see the machinery clearly. The real use case is planning hardware for algorithms that don't exist as working code yet."

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Filename-keyed last-write-wins at build time.** `build_sqlite.py` de-duplicates by `filename`, keeping the last-occurring record in JSONL order (`seen[filename] = r` overwrites earlier entries as it iterates). This means re-ingesting a paper is safe without ever touching `records.jsonl` — the newer extraction automatically supersedes the old one at build time. Old rows are inert history, not a cleanup burden.
- **Exclusions are build-time overlays** — `exclusions.json` excludes records from the SQLite view without touching the JSONL.
- **Records are PUKs** — self-contained. Target architecture: QREM reads PUKs directly, no YAML step.
- **AI proposes, humans approve** — every extracted value has confidence + source citation.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — correlations tested within material class. `derived_material` drives Phase A and Explorer sidebar filtering; `sim_material_class` is no longer used for sidebar filtering (bug fixed June 15).
- **Schema evolution is frequency-driven** — geometry-independent properties only for measurement fields. Fabrication process fields follow a relaxed rule: frequency + scientific relevance.
- **Materials-first estimation** — gate fidelity is an output, not an input.
- **ε_ctrl is fixed to the controls baseline** — now directly specified in YAML rather than back-calculated. Corpus profiles contribute T1 and T2 only. ε_ctrl = 5.83e-4, always.
- **The estimator always estimates** — tiered fallback: `[MEASURED]` → `[DERIVED]` → `[CORPUS AVERAGE]` → `[CLASS DEFAULT]` → `[ASSUMED]`.
- **Stage 4 decomposition panel is read-only** — disappears when sliders touched. Stage 5 adds forward-direction material sliders.
- **Resonator is calibration, not loss channel** — v2.5 model. Qi → tan_delta → pad T1, never Qi/ω directly as qubit T1.
- **General solutions over one-offs** — new derived fields follow the established `derived_X` fallback pattern.
- **Don't ingest SI files as standalone** — wait for SI file linking implementation. Especially important now that Block 2.5 fields are often only in the SI.
- **Prompt evolution: resist whack-a-mole** — only add guidance that fires on multiple paper types, not one-off fixes for individual papers.
- **Per-material defaults over single general defaults** — `{Material}_material_defaults.yaml` files replace the single `transmon_general_defaults.yaml` as the corpus grows. General defaults remain as fallback of last resort.
- **Repo structured for audience** — `explorer/` for materials contributors, `qrem/` for QEC/algorithms contributors. Each has its own README with plugin points for expert integration.
- **Mapping layer feeds anything** — the materials-to-device mapping layer is a standalone service, not a Baby QREM internal component. Baby QREM is one consumer among many.
- **Fabrication fields are free-text** — the vocabulary is too diverse and lab-specific for controlled enums. Derived columns (derived_resist_strip_family etc.) provide the categorical axis for plotting via keyword matching at DB build time.
- **Test ingestion is isolated** — use `--papers-dir`, `--out`, `--ledger` flags to run against a test folder with separate output files. Never touches the main corpus.

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd explorer && python3 serve_materials.py

# Baby QREM (port 8000)
cd qrem/scripts && python3 serve.py

# Rebuild SQLite after any JSONL, build_sqlite.py, or exclusions.json changes
cd explorer && python3 build_sqlite.py

# Regenerate per-material corpus-average YAMLs (run after build_sqlite.py)
cd explorer && python3 compute_class_defaults.py

# Single-paper test ingestion (isolated from main corpus)
cd explorer
python3 pipeline_ingest.py \
  --papers-dir "../data/papers/test_single" \
  --out "../data/ingested/records_test.jsonl" \
  --ledger "../data/ingested/processed_ledger_test.json"

# Backfill similarity profiles — ALWAYS check line counts before swapping
cd explorer
python3 backfill_similarity_profiles.py --filter <pattern>
wc -l ../data/ingested/records_with_profiles.jsonl  # must match records.jsonl
wc -l ../data/ingested/records.jsonl
# Only if counts match:
mv ../data/ingested/records.jsonl ../data/ingested/records_backup.jsonl
mv ../data/ingested/records_with_profiles.jsonl ../data/ingested/records.jsonl
python3 build_sqlite.py

# Standard commit
git add . && git add ../data/ingested/records.db && git commit -m "description" && git push

# Targeted re-ingestion (preferred over full reset for a handful of papers)
# Established workflow — used for Joshi+Bland (May 17), Wang 2026 (May 23), Nanayakkara (June 2)
#
# Step 1 — find the ledger entries to remove (match by filename or DOI fragment)
python3 -c "
import json
ledger = json.load(open('../data/ingested/processed_ledger.json'))
entries = ledger.get('processed', [])
for e in entries:
    if 'keyword' in (e.get('filename') or '').lower():
        print(repr(e['filename']), '|', e.get('doi'))
"

# Step 2 — remove just those entries from processed_ledger.json (edit the 'processed' list directly).
# Do NOT touch records.jsonl — it is append-only. The old record for that paper stays in place;
# build_sqlite.py's last-write-wins logic will supersede it automatically once the new one is appended.

# Step 3 — re-run against the MAIN papers folder (not --papers-dir test_single).
# Only the removed entries will be reprocessed; everything still in the ledger is skipped.
cd explorer
caffeinate python3 pipeline_ingest.py

# Step 4 — rebuild. build_sqlite.py automatically picks the latest record per filename.
python3 build_sqlite.py

# Reset corpus (preserves findings.jsonl)
rm ../data/ingested/records.jsonl
rm ../data/ingested/processed_ledger.json
rm ../data/ingested/records.db
caffeinate python3 pipeline_ingest.py
```

---

*Last updated: July 6, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
