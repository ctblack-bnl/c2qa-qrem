# C2QA QREM — Project Architecture & Next Steps
## Continuity Document — May 2, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Major overhaul May 2. Materials-first estimation: T1/T2 → fidelity → code distance. T1 sensitivity curve. Auto-run. See Baby QREM section. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | Operational. Three-pass pipeline. 97 papers, 155 samples, ~1,318 catchall items, 100% profile coverage. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | Live at https://c2qa-materials-explorer.onrender.com. Explore/Search/Catchall tabs, hybrid similarity search, material class sidebar. |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | Operational. Phase A→B→C pipeline. 41 correlations, 3 findings (all negative/inconclusive — honest and expected). Human review UI in Stage 4. |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | Designed, not built. Corpus mining feeds it. First findings produced April 28. |

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

## Baby QREM — Current State (May 2)

### What Was Done This Session

**Materials-first estimation (major architectural change).** The estimator no longer takes gate fidelity as an input. Instead:

```
T1, T2 (material properties) + gate_time (device parameter, fixed)
  → ε_T1 = gate_time / T1
  → ε_T2 = gate_time / T2
  → ε_ctrl (fixed from baseline profile — engineering term, not materials)
  → ε_total = ε_T1 + ε_T2 + ε_ctrl
  → derived gate fidelity = 1 - ε_total
  → code distance → physical qubits
```

The fidelity slider is gone. T1 and T2 sliders replace it. Gate fidelity is now an output shown in the metric cards.

**ε_ctrl correctly fixed.** Key design decision: ε_ctrl (pulse errors, leakage, calibration) is derived once from the clean unmodified baseline profile, then held constant regardless of slider changes. This required loading the profile twice in `run_estimation` — once clean for ε_ctrl derivation, once with overrides for estimation. Without this fix, moving the T1 slider would also change ε_ctrl, making it impossible to see clean staircase steps.

**T1 sensitivity curve.** The staircase chart x-axis is now T1 (µs) on a log y-axis (physical qubits). Steps are labeled by code distance d. Current position shown with stacked label (T1 value / qubit count). Built analytically — no API sweep. The researcher can now clearly read: "I need T1 ≥ X to reach code distance d=5."

**Auto-run.** The Run button is removed. Estimation triggers automatically — T1/T2 sliders debounced 400ms, all dropdowns immediate. Boots with defaults on page load (test_circuit.qasm + transmon_baseline_2026).

**Layout overhaul.** Circuit Analysis and Error Attribution panels moved below the chart in a two-column grid. Left panel is controls only — no scrolling needed. The panels are correctly placed near their related controls conceptually.

**Slider initialization from profile.** New `/api/profile_values` endpoint in `serve.py`. On boot and on profile dropdown change, sliders initialize to the actual profile T1/T2 values with correct [MEASURED] / [ASSUMED] provenance tags.

**Error Attribution panel** (renamed from "Coherence Budget"). Shows T1, T2, gate time, T1-limited ceiling, derived fidelity, and the gate error decomposition bar (ε_T1 / ε_T2 / ε_ctrl with fractions). Gate time shown as read-only with [MEASURED]/[ASSUMED] tag.

**Gate time updated.** Both `superconducting.yaml` and `transmon_baseline_2026.yaml` updated from 200ns → 50ns (more representative of current tunable-coupler state of the art).

**Default profiles on boot.** `loadCircuits()` and `loadProfiles()` now explicitly select `test_circuit.qasm` and `transmon_baseline_2026` as defaults regardless of alphabetical ordering.

### Files Changed This Session

| File | Change |
|---|---|
| `src/qrem/estimator.py` | Materials-first: `_derive_control_error_baseline()`, `_compute_coherence_budget()` forward calculation; `run_estimation()` loads clean profile for ε_ctrl; `estimate()` accepts `epsilon_control_baseline` param |
| `src/qrem/hardware_profiles/qubits/transmon_baseline_2026.yaml` | gate_time 200ns → 50ns |
| `src/qrem/hardware_profiles/superconducting.yaml` | gate_time 200ns → 50ns |
| `scripts/serve.py` | New `/api/profile_values` endpoint for slider initialization |
| `scripts/qrem_ui.html` | Full UI overhaul — T1/T2 sliders, auto-run, below-chart panels, log-scale T1 sensitivity curve, Error Attribution panel, default profile/circuit selection |

### What the Estimator Currently Does

```
QASM circuit + Qubit profile YAML
    ↓
Stage 1 — Parse
  gate list, qubit count, T gate count
    ↓
Stage 2 — Analyze
  circuit depth via critical path
  interaction graph, hub qubits, locality score
    ↓
Stage 3 — Single-module estimate
  clean profile → ε_ctrl (fixed baseline)
  T1, T2 (slider) + gate_time → ε_T1, ε_T2
  ε_total → derived gate fidelity
  depth + success rate → per-gate LER target
  → code distance d
  → physical qubits per logical (2d²-1)
  → total physical qubits
```

### What the Estimator Does NOT Yet Do

- **Loss mechanism attribution** — T1 breakdown by mechanism (TLS, quasiparticle, vortex motion). Would connect directly to materials properties (RRR → quasiparticle loss, Qi → TLS loss). Next major capability.
- **RRR → T1 sensitivity** — routing upstream material properties through the coherence model. Depends on validated corpus mining findings for the mapping functions.
- **T gate counting** — placeholder (0). Magic state factory underestimated for T-heavy circuits.
- **Readout fidelity** — in profile and directly usable, not yet wired into QEC model.

---

## Corpus Mining Pipeline — Current State

Operational end-to-end. Lives in `ingester/pipeline_mining.py`, runs as Stage 4 of the ingestion pipeline UI.

**Current results (April 28):** 41 correlations → 11 out of scope, 16 corpus gaps, 13 hypotheses matched → 3 findings (all negative/inconclusive). Key insight: per-material-class analysis is needed — cross-material testing is confounded by material identity.

---

## Schema Evolution — Current State

Three fields promoted to Block 3 in schema v0.7: `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K`. Values already in `catchall_items.value` as clean numerics. **Promotion not yet implemented in `build_sqlite.py`** — first Track A priority.

---

## Hosted Infrastructure

| Service | URL | Auto-deploys from |
|---|---|---|
| Materials Explorer | https://c2qa-materials-explorer.onrender.com | GitHub main branch |
| Baby QREM | Local only (localhost:8000) | — |
| Ingestion + Mining Pipeline | Local only (localhost:8001/ingest_pipeline.html) | — |

---

## Repository & Running

**GitHub:** `https://github.com/ctblack-bnl/c2qa-qrem`

```bash
# Standard commit
git add . && git commit -m "description" && git push

# Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py

# Baby QREM (port 8000)
cd 2026-04\ c2qa_qrem && python3 scripts/serve.py
# Open http://localhost:8000/scripts/qrem_ui.html

# Mining pipeline
cd ingester
python3 pipeline_mining.py phase-a
python3 pipeline_mining.py phase-b
python3 pipeline_mining.py phase-c
```

---

## Coding Priorities — Next Sessions

### Track A: Mining + Schema (ingester side)

**1. Schema promotion implementation** — add `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K` as named columns in `build_sqlite.py`. Re-run Phase A after — expect significantly more cross-sample evidence.

**2. Per-material-class Phase A** — stratify evidence tables by material class (Ta, Ta-Hf, NbSe2, NbN). Bahrami Ta series (8 samples, wide mean free path range) is particularly promising.

**3. Stage 4 schema evolution UI** — surface measurement frequency report for human approval of field promotions.

**4. Explorer Findings tab** — read-only view of approved `findings.jsonl`, updating on git push.

### Track B: Baby QREM (next capabilities)

**5. Loss mechanism attribution** — break T1 into contributions by mechanism: TLS, quasiparticle, vortex motion, radiation. This is the direct bridge to materials properties (RRR → quasiparticle, Qi → TLS). Makes the Error Attribution panel scientifically complete and connects directly to corpus mining findings.

**6. RRR → T1 sensitivity** — once loss mechanism mapping functions exist (from corpus mining findings), add RRR as an upstream slider that feeds into T1 via the mapping layer. The T1 sensitivity curve then becomes a material property sensitivity curve.

**7. Readout fidelity** — wire `readout_fidelity_pct` and `readout_time_ns` from qubit profiles into the QEC model. Currently loaded but unused.

**8. T gate counting** — replace placeholder with actual T gate count from circuit analysis.

### Medium effort

**9. Ic/Jc disambiguation** — new `derive.py` functions, new schema columns, extraction prompt fix.

**10. Mining config file** — extract `FIELD_MAP`, `DEVICE_PHYSICS_TERMS`, system prompts to `mining_config.yaml`.

**11. Corpus expansion** — older literature ingestion.

### Larger effort

**12. Materials Predictor** — Gaussian process regression per material class.

**13. Tier 2 reconnection** — modular overhead, when Center-wide architecture research matures. Functions preserved in `estimator_tier2_modular.py`.

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — self-contained. Hardware profiles, similarity profiles, and mining findings are projections of records. The target architecture is that QREM reads PUKs directly from the database — no YAML export step. The current Explorer → YAML → QREM workflow is transitional.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. Every mining finding requires human review before entering `findings.jsonl`.
- **Sparse extraction** — only fields actually reported in a paper are included. Absence = not reported, never zero.
- **Configuration as data, not code** — hardware profiles, mining field maps, domain context are YAML/config files, not hardcoded logic.
- **Explicit assumptions in every output** — QREM documents all simplifying assumptions; mining pipeline documents all classification decisions.
- **Single-module first** — materials → single-module resource estimator is the primary Baby QREM deliverable. Modular overhead (Tier 2) is a separate Center-wide research problem.
- **Schema evolution is frequency-driven** — promotion candidates surface from measurement frequency across corpus, not per-paper AI judgment.
- **Geometry-independent properties only** — only intrinsic material properties promotable to named columns.
- **Circuit depth drives error correction** — per-gate LER target derived from circuit depth and success rate, not hardcoded.
- **Materials-first estimation** — gate fidelity is derived from T1, T2, and gate time. It is an output, not an input. ε_ctrl (engineering term) is fixed from the clean baseline profile and does not vary with slider changes.
- **The estimator always estimates** — it documents assumptions, flags uncertainty, shows measured vs assumed — but never refuses to give a number.

---

*Last updated: May 2, 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
