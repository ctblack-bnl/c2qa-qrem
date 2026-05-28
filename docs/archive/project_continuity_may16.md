# C2QA QREM — Project Continuity & Coding Priorities
## Updated May 16, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Materials-first estimation complete. T1/T2 → fidelity → code distance. T1 sensitivity curve. Auto-run UI. Part A declutter complete. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | ✅ Operational. Three-pass pipeline. max_tokens = 64000. New resonator geometry fields added (May 16). |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | ✅ Live at https://c2qa-materials-explorer.onrender.com. 226 samples, 100% profile coverage. |
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

## Recent Completions (May 16, 2026)

### Loss Channel Model — Stage B Complete

`t1_decomposition.py` fully rewritten implementing the v2.5 two-level loss model:

**Core physics (Joshi 2026 inversion):**
```
tan_delta = 1 / (Q_TLS,0_resonator × p_MS_resonator)   [calibration]
T1_pad_TLS = 1 / (p_MS_pad × tan_delta × 2π × f_qubit)  [apply to pad]
```

**Key changes from v2.4:**
- Resonator excluded from Level 1 qubit loss sum — calibration only, not a loss channel
- Junction TLS uses single effective loss tangent (p_junction_surface × tan_delta_junction), not per-interface sum with pad film defaults
- Units fix: frequency correctly converted GHz → cycles/µs (×1000) before computing omega
- QP channel always uses non-equilibrium floor (not thermal value) — thermal QP negligible at 20mK for all practical Tc
- Vortex defaults set to 1e9 µs for dirty-limit and unknown regime — not a significant loss channel in current state-of-art devices
- Validation threshold widened to 5x with note about TLS saturation at qubit operating power

**Validation against Joshi 2026 (all pass 5x threshold):**

| Qubit | f (GHz) | T1 measured | T1 predicted | ratio |
|---|---|---|---|---|
| Q1 | 2.613 | 397 µs | 152 µs | 0.38 ✅ |
| Q2 | 2.736 | 585 µs | 148 µs | 0.25 ✅ |
| Q6 | 4.696 | 236 µs | 100 µs | 0.42 ✅ |
| Q11 | 5.804 | 40 µs | 84 µs | 2.10 ✅ |

Frequency scaling (1/f trend) correct. Q11 overprediction correctly reflects radiative coupling to package modes — a system effect outside the model scope.

**Key defaults (Joshi-geometry anchor):**
- `p_MS_pad` = 1.3e-4 (Joshi 2026, measured)
- `p_MS_resonator` = 8.63e-4 (mid-range CPW, s=6µm)
- `tan_delta_effective_surface` = 8.1e-4 default (α-Ta/sapphire, Crowley 2023); 1.6e-3 for β-Ta (Joshi 2026)
- `p_junction_surface` = 2.9e-5 (calibrated to give T1_junction_TLS ~1000 µs)
- `tan_delta_junction` = 2.0e-3 (Al/AlOx class default)
- `T1_QP_nonequilibrium` = 1000 µs (non-equilibrium floor, well-shielded system)
- `T1_radiation` = 5000 µs (Purcell-filtered 2D transmon)

**Honest model assessment:**
- T1_pad_TLS prediction reliable to within 2-4x — gap is TLS saturation at qubit operating power
- Most useful as a ranking/screening tool, not for absolute T1 prediction
- For film-only records: output is T1_pad_TLS as a materials benchmark, cleanest use case
- System background channels (QP, junction, radiation) are anchored to Joshi — not independently constrained

**Companion files updated:**
- `transmon_analytical_defaults.yaml` — junction_tls block added, p_MS_pad corrected (was 5e-3, now 1.3e-4), vortex defaults raised
- `example_material_record.yaml` — replaced placeholder with real Joshi Qubit 2 data
- `joshi_2026_qubit1/6/11.yaml` — validation records for frequency scaling test

### Resonator Geometry Schema Fields (May 16)

New fields added to schema, extraction prompt (`prompts.py`), and database (`build_sqlite.py`):

| Field | Purpose |
|---|---|
| `resonator_type` | CPW or lumped_element — determines geometry table to use |
| `resonator_gap_width_um` | CPW gap width s — primary determinant of p_MS_resonator |
| `p_MS_resonator` | Surface participation ratio of resonator — needed to invert Q_TLS,0 → tan_delta |
| `p_MS_pad` | Surface participation ratio of qubit pad — needed to convert tan_delta → T1_pad_TLS |

**Why these matter:** Without p_MS_resonator, Q_TLS,0 alone cannot give tan_delta — a 6x range in p_MS_resonator (from CPW gap width variation) gives 6x uncertainty in tan_delta. These fields are now extracted from papers when reported.

**Current population after re-ingestion:**
- Joshi 2026: p_MS_pad = 1.3e-4 on all 11 qubits; resonator geometry on 3 resonator records
- Bland 2025: resonator geometry on CPW resonator record (gap=9µm, p_MS=8.75e-4); p_MS_pad null (in SI, not ingested yet)

**Operational notes:**
- max_tokens bumped to 64000 (was 32000) — needed for large papers like Bland (57 qubits)
- Backfill null-check bug fixed in `backfill_similarity_profiles.py` line 215
- Safe backfill checklist: always run `wc -l` on both files before swapping — counts must match

### Papers Re-ingested (May 16)
- **Joshi 2026** (arXiv:2603.13174) — β-Ta transmon qubits. 12 samples + 3 resonator geometry records. Primary validation case for t1_decomposition.
- **Bland 2025** (Nature, doi:10.1038/s41586-025-09687-4) — α-Ta on silicon, millisecond coherence. 57 individual qubit records + resonator. Key insight: Figure S5 confirms resonator → tan_delta → qubit pad T1 chain (transmon Q lies on same line as resonator Q_TLS,0 vs p_MS).

---

## Next Coding Priorities

### Track A: Baby QREM

**1. Stage C — Integrate t1_decomposition.py into estimator.py**
The Stage 4 backend exists and is validated. Next step: wire it into the estimation pipeline so T1_pad_TLS appears in the resource estimate output alongside ε_T1/ε_T2/ε_ctrl.

**2. Part B drawer UI** — bottom drawer triggered by ε_T1 affordance. Shows T1 decomposed into TLS/QP/vortex/radiation channels with per-channel provenance. Prerequisite: Stage C integration first.

**3. Stage 5 — Upstream material property sliders** — RRR, Qi, loss tangent sliders feeding through Tier 2 mapping functions into T1. Depends on Stage C.

**4. Readout fidelity** — wire into QEC model (currently loaded but unused).

**5. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Ingester / Mining

**6. SI file linking** — DOI-based naming convention: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Ingester recognizes pair and ingests as single logical record with `source_files: [main, SI]`. Currently SI files ingested as independent papers with no link to companion. Open question: SI files are often tables/figures without narrative — may need adjusted prompt handling. **Do not ingest Bland SI as standalone — wait for this feature.**

**7. Corpus expansion** — older literature ingestion. Collection in progress.

**8. Ic/Jc disambiguation** — `derive.py` functions, schema columns, extraction prompt fix. Material Jc (intrinsic) vs junction Jc (device property) currently conflated.

### Track C: Longer Term

**9. Community upload feature** — public Explorer with PDF upload.

**10. Materials Predictor** — Gaussian process regression per material class.

**11. Tier 2 modular reconnection** — reconnect modular overhead cost model (Arquin) when Center-wide architecture research matures.

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
- **Records are PUKs** — self-contained. Target architecture: QREM reads PUKs directly, no YAML export step.
- **AI proposes, humans approve** — every extracted value has confidence + source citation.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — correlations tested within material class. `derived_material` drives Phase A; `sim_material_class` drives Explorer sidebar.
- **Schema evolution is frequency-driven** — geometry-independent properties only.
- **Materials-first estimation** — gate fidelity is an output, not an input. ε_ctrl fixed from clean baseline.
- **The estimator always estimates** — tiered fallback: `[MEASURED]` → `[DERIVED]` → `[CLASS DEFAULT]` → `[ASSUMED]`.
- **Explorer is the Explorer** — literature database and discovery tool, not a physics inference engine.
- **Resonator is calibration, not loss channel** — v2.5 model. Qi → tan_delta → pad T1, never Qi/ω directly as qubit T1.

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py

# Baby QREM (port 8000)
cd "2026-04 c2qa_qrem" && python3 scripts/serve.py

# Rebuild SQLite after any JSONL or build_sqlite.py changes
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

*Last updated: May 16, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
