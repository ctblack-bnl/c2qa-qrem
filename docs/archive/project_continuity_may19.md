# C2QA QREM — Project Continuity & Coding Priorities
## Updated May 19, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Materials-first estimation complete. T1/T2 → fidelity → code distance. T1 sensitivity curve. Auto-run UI. Part A declutter complete. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | ✅ Operational. Three-pass pipeline. max_tokens = 64000. New resonator geometry fields added (May 16). Manual exclusions mechanism added (May 19). |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | ✅ Live at https://c2qa-materials-explorer.onrender.com. 221 samples (after 3 exclusions), 100% profile coverage. |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | ✅ Operational. 1 positive finding (Ta-Hf Tc vs deposition temperature). |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | `t1_decomposition.py` Stage B complete (May 16). Validated against 4 Joshi 2026 qubits. Not yet integrated into estimator.py or UI. |

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

## Recent Completions (May 19, 2026)

### Explorer: derived_tan_delta

New `derived_tan_delta` column added to `build_sqlite.py` and `serve_materials.py`, following the established `derived_Qi` / `derived_T2_us` pattern:

- **Priority:** `tan_delta_effective_surface` → `loss_tangent_interface` → `loss_tangent_substrate`
- **Appears in Explorer dropdown as:** "Loss tangent (best available)"
- **Coverage:** 19 samples (Hedrick 2026 Al, Joshi 2026 β-Ta, Bland 2025 α-Ta)
- **Why it matters:** `tan_delta_effective_surface` is the key input to the T1 loss model: `tan_delta = 1/(Q_TLS,0 × p_MS_resonator)` → `T1_pad_TLS = 1/(p_MS_pad × tan_delta × 2πf)`

### Explorer: Q_TLS,0 Added as Plottable Field

`Q_TLS_0` added to `ALL_NUMERIC_FIELDS` in `serve_materials.py` as "Q_TLS,0 (unsaturated TLS Q)". This is a physically distinct quantity from Qi — extracted from power/temperature sweep fitting rather than single-photon readout — and belongs in its own field, not folded into `derived_Qi`. Bland 2025 and Joshi 2026 resonator records appear here.

### Explorer: Dropdown Rationalization

Removed redundant raw fields from the Explorer measurement dropdown:
- Removed: `Qi internal`, `Qi single photon` (superseded by `Qi (best available)`)
- Removed: `Loss tangent substrate`, `Loss tangent interface` (superseded by `Loss tangent (best available)`)

Rationale: exposing raw variants alongside derived best-available fields invites confusion about which to use. Raw values remain accessible in the detail drawer when clicking any data point.

### Explorer: Click Hint Restyled

The "Click any data point for full material information" hint was:
- Moved inside the chart canvas (absolute positioned, upper right)
- Given a border box for visibility
- Shortened to "Click a data point for full info"
- Brightened (opacity 0.7 → 0.92) and enlarged (11px → 13px)
- `pointer-events: none` so it doesn't block clicks on nearby data points

### Manual Exclusions Mechanism

New `data/ingested/exclusions.json` file + `build_sqlite.py` support for post-hoc exclusion of wrongly-ingested records. **Core principle: JSONL is never modified — exclusions are applied only at build time.**

**Design:**
- `exclusions.json` is an append-only list of exclusion entries
- Match priority: DOI → arXiv ID → filename (same as processed ledger)
- `build_sqlite.py` reads the file at build time and skips matching records
- Human-readable `reason` field required for each exclusion

**Workflow:**
```bash
# Add entry to data/ingested/exclusions.json, then:
cd ingester && python3 build_sqlite.py
```

**Current exclusions (3):**

| Paper | Reason |
|---|---|
| Hays 2026 (PRX Quantum, doi:10.1103/dd96-gcb6) | Theory proposal — no experimental materials data. T1=3×10⁹µs is a noise model estimate for an unbuilt qubit ("harmonium"). C2QA acknowledgment caused false high-relevance. |
| Marcenac 2026 (arXiv:2604.11743) | NV center / FPGA control paper. T1/T2 are NV spin coherence times, not superconducting qubit coherence. Known ingester leakage type. |
| WangX 2026 (arXiv:2603.05615) | ZnO semiconductor donor spin qubit paper. No Tc, RRR, Qi, or T1 data. C2QA acknowledgment covers DFT calculations only. |

**exclusions.json entry format:**
```json
{
  "doi": "10.1103/dd96-gcb6",
  "arxiv_id": null,
  "filename": "2025-PRXQuantum-Hays.pdf",
  "excluded_at": "2026-05-18",
  "excluded_by": "manual",
  "reason": "..."
}
```

### Resistivity Fallback Scaffolding

`build_sqlite.py` now computes `derived_resistivity_uOhm_cm` with a two-step fallback:
1. Geometry derivation via `derive.py` (requires R vs T geometry fields — rarely reported)
2. Fallback to `gf("normal_state_resistivity_uOhm_cm")` — a directly reported named field

**Current status:** The fallback code is in place but not yet firing — Bahrami 2026 and Yang 2026 resistivity values were extracted into `catchall.additional_measurements` (free text) rather than into the named field. The underlying data is correctly captured; it just needs the extraction prompt updated to route resistivity into the named schema field.

**Note:** Yang 2026 resistivity values ("Residual resistivity of Ta-Hf alloy film") use a slightly different description than Bahrami/Joshi. Both will be resolved by the prompt fix below.

---

## Next Coding Priorities

### Track A: Baby QREM

**1. Stage C — Integrate t1_decomposition.py into estimator.py**
The Stage 4 backend exists and is validated. Next step: wire it into the estimation pipeline so T1_pad_TLS appears in the resource estimate output alongside ε_T1/ε_T2/ε_ctrl.

**2. Part B drawer UI** — bottom drawer triggered by ε_T1 affordance. Shows T1 decomposed into TLS/QP/vortex/radiation channels with per-channel provenance. Prerequisite: Stage C integration first.

**3. Stage 5 — Upstream material property sliders** — RRR, Qi, loss tangent sliders feeding through Tier 2 mapping functions into T1. Depends on Stage C.

**4. Readout fidelity** — wire into QEC model (currently loaded but unused).

**5. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Ingester / Explorer

**6. Extraction prompt fix: normal_state_resistivity_uOhm_cm** — Update the Pass 2 extraction prompt to extract resistivity directly into the named schema field rather than catchall. Re-ingest Bahrami 2026 and Yang 2026. The fallback in `build_sqlite.py` will then fire automatically and surface ~17 additional resistivity values (8 Bahrami Ta, 8 Yang Ta-Hf, 1 Joshi β-Ta).

**7. Per-point symbol encoding for derived fields** — When a "best available" derived field (e.g. `derived_Qi`) is selected in the Explorer, encode the measurement variant as a symbol (solid circle = `Qi_single_photon`, open circle = `Qi_internal`). Show a legend only when a derived field is selected. Scientific motivation: a bimodal distribution in `derived_Qi` could be an artifact of mixing measurement regimes (TLS-saturated vs unsaturated) rather than real materials variation — the symbol encoding makes this visible at a glance. Implementation touches `serve_materials.py` (return source field per data point) and `materials_explorer.html` (per-point Chart.js styles + conditional legend).

**8. Exclusions UI** — Add a management interface for `exclusions.json` to the pipeline UI (Stage 4 or new Stage 5). Should show current exclusions with reasons, allow adding new exclusions by DOI/arXiv ID/filename, and trigger a db rebuild. Currently exclusions require manual JSON editing.

**9. SI file linking** — DOI-based naming convention: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Ingester recognizes pair and ingests as single logical record with `source_files: [main, SI]`. Currently SI files ingested as independent papers with no link to companion. **Do not ingest Bland SI as standalone — wait for this feature.**

**10. Corpus expansion** — older literature ingestion. Collection in progress.

**11. Ic/Jc disambiguation** — `derive.py` functions, schema columns, extraction prompt fix. Material Jc (intrinsic) vs junction Jc (device property) currently conflated.

### Track C: Longer Term

**12. Community upload feature** — public Explorer with PDF upload.

**13. Materials Predictor** — Gaussian process regression per material class.

**14. Tier 2 modular reconnection** — reconnect modular overhead cost model (Arquin) when Center-wide architecture research matures.

---

## Key Scientific Insights (May 19)

**On Q_TLS,0 vs Qi:**
- Papers that fabricate qubits (Bland, Joshi) report Q_TLS,0 from resonator test structures rather than raw Qi. Q_TLS,0 is extracted from power/temperature sweep fitting — it is the TLS-limited Q in the unsaturated (single-photon) limit, free of other loss contributions. It cannot be obtained without first measuring Qi, but the raw Qi values are often not separately tabulated.
- Q_TLS,0 should not be folded into `derived_Qi` — they are physically distinct. Q_TLS,0 belongs in its own plottable field and is the preferred input for the loss model.
- The Qi strip plot is effectively a "who made test resonators" plot. Qubit-focused papers appear in Q_TLS,0 instead.

**On ingester leakage:**
- Three classes of leakage papers identified and excluded (May 19): theory proposals with no experimental data (Hays), non-superconducting quantum systems (Marcenac NV center, WangX ZnO). All had C2QA acknowledgments causing false high-relevance classification.
- The Dai 2026 (PRX Quantum, drive-induced transitions in 3D transmon) was reviewed and retained — it has real T1/T2 measurements on a fabricated device and TLS characterization content relevant to the corpus, even though materials characterization is not the primary focus.
- Pattern: C2QA acknowledgment alone is not sufficient for relevance. The paper must report superconducting materials characterization data.

**On resistivity in the corpus:**
- Normal-state resistivity (ρn in µΩ·cm) is well-measured in Bahrami 2026 (8 Ta samples) and Yang 2026 (8 Ta-Hf samples) but currently sits in the catchall. The data is correctly captured; it just needs the extraction prompt updated to route it into the named `normal_state_resistivity_uOhm_cm` field.
- ρn is an intrinsic material property (geometry-independent) and connects directly to mean free path and superconducting limit classification — a key input to the vortex loss model.

---

## Key Scientific Insights (May 16)

**On p_MS and the resonator → qubit chain:**
- p_MS_resonator varies 30x across typical resonator geometries (CPW gap 2-16µm: 2.2e-3 to 3.7e-4). Without knowing the resonator gap, Q_TLS,0 alone carries 6x uncertainty in tan_delta.
- The gold standard is Joshi/Bland's approach: fit Q_TLS,0 vs p_MS across many resonators → extract tan_delta directly, bypassing individual geometry uncertainty.
- Bland Figure S5 is the definitive proof: resonator Q_TLS,0 and transmon Q lie on the same line vs p_MS. The inversion chain is correct.

**On TLS saturation:**
- Resonator measurements extract tan_delta at single-photon powers (TLS unsaturated). Qubits operate at multi-photon powers where TLS partially saturates — effective tan_delta is lower. This is why measured qubit T1 can legitimately exceed the single-photon model prediction. Our model uses single-photon tan_delta and will systematically underpredict T1 for good qubits. This is correct behavior, not a bug.

**On junction TLS:**
- The per-interface sum approach (applying pad film tan_delta_MA to junction) was wrong — junction has no significant exposed metal-air surface. Single effective loss tangent (p_junction_surface × tan_delta_junction) is physically correct.
- Junction tan_delta varies with fabrication: HV deposition gives higher hydrocarbon contamination → higher junction TLS. UHV (Joshi, Bland) achieves lower junction tan_delta.

---

## Data Provenance Principles

**Peer review is inherited, not intrinsic.** SI files and external database entries carry peer review credibility if traceable to a published paper via DOI.

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
- **Exclusions are build-time overlays** — `exclusions.json` excludes records from the SQLite view without touching the JSONL. The canonical ingestion record is preserved for auditability.
- **Records are PUKs** — self-contained. Target architecture: QREM reads PUKs directly, no YAML export step.
- **AI proposes, humans approve** — every extracted value has confidence + source citation.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — correlations tested within material class. `derived_material` drives Phase A; `sim_material_class` drives Explorer sidebar.
- **Schema evolution is frequency-driven** — geometry-independent properties only.
- **Materials-first estimation** — gate fidelity is an output, not an input. ε_ctrl fixed from clean baseline.
- **The estimator always estimates** — tiered fallback: `[MEASURED]` → `[DERIVED]` → `[CLASS DEFAULT]` → `[ASSUMED]`.
- **Explorer is the Explorer** — literature database and discovery tool, not a physics inference engine.
- **Resonator is calibration, not loss channel** — v2.5 model. Qi → tan_delta → pad T1, never Qi/ω directly as qubit T1.
- **General solutions over one-offs** — new derived fields follow the established `derived_X` fallback pattern. Catchall scraping for individual papers is not the right fix; prompt improvements are.

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

*Last updated: May 19, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
