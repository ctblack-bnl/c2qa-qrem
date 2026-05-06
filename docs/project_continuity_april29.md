# C2QA QREM — Project Architecture & Next Steps
## Continuity Document — April 29, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Rescoping complete. Single-module estimator operational with circuit depth, depth-derived LER target, staircase chart. See Baby QREM section. |
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
      |   → Hardware Profile Updater → qubit profile YAML
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

Modular architecture ("how many modules?") is a separate Center-wide research effort. Materials feed into it but do not drive it. Baby QREM deliberately stays out of that space.

---

## Baby QREM — Current State (April 29)

### What Was Done Today

**Rescoping complete.** Tier 2 (modular overhead) stripped from the active estimator and preserved intact in `estimator_tier2_modular.py`. The `EstimationResult` dataclass retains all Tier 2 fields as `Optional` defaulting to `None` — reconnecting Tier 2 requires only importing and calling the preserved functions.

**Circuit depth implemented.** `analyzer.py` now computes critical path depth via a single forward pass over the gate list. Measurements are included (Qiskit convention). Depth is shown in the Circuit Analysis panel.

**Depth-derived LER target.** The per-gate logical error rate target is now computed from circuit depth and a user-specified target circuit success rate:
```
target_LER_per_gate = 1 - success_rate ^ (1 / circuit_depth)
```
This replaces the hardcoded 1e-6 target. A depth-8 circuit at 99% success rate needs LER ~1.26e-3 — far more lenient than 1e-6, which was implicitly calibrated for circuits ~100,000 gates deep. Resource estimates are now honest and circuit-specific.

**UI improvements.** Four dropdowns → two (Qubits + Error Correction). Seven metric cards → four. Staircase chart rebuilt analytically (no sweep API calls) — parameterized by code distance, fills the full x-axis range, steps labeled `d=N`. Target Circuit Success Rate dropdown replaces hardcoded LER. Logo served correctly via `/static/` route in `serve.py`. Gap between cards and chart eliminated via layout restructure.

**Profile loading fixed.** `profile_loader.py` now handles partial modular loading (qubits + EC only) without raising on missing interconnect/module components. The qubit profile dropdown now actually affects estimation.

**QFT test circuit added.** `data/circuits/qft_5qubit.qasm` — Quantum Fourier Transform on 5 qubits, depth 11. A real algorithm (core subroutine of Shor's), meaningfully deeper than the existing test circuits.

### Files Changed Today

| File | Change |
|---|---|
| `src/qrem/analyzer.py` | Added `compute_circuit_depth()`, `circuit_depth` field in `AnalysisResult` |
| `src/qrem/estimator.py` | Single-module only; depth-derived LER; new fields in `EstimationResult` |
| `src/qrem/estimator_tier2_modular.py` | New file — Tier 2 functions preserved here |
| `src/qrem/profile_loader.py` | Partial modular loading (skip missing components) |
| `scripts/serve.py` | Partial modular path; `/static/` file serving |
| `scripts/qrem_ui.html` | Full UI overhaul — see above |
| `data/circuits/qft_5qubit.qasm` | New QFT circuit |
| `docs/quantum_resource_estimator_spec_v06.md` | Spec updated to v0.6 |

### What the Estimator Currently Does

```
QASM circuit
    ↓
Stage 1 — Parse (complete)
  gate list, qubit count, T gate count
    ↓
Stage 2 — Analyze (complete)
  circuit depth via critical path
  interaction graph, hub qubits, locality score
    ↓
Stage 3 — Single-module estimate (complete)
  depth + success rate → per-gate LER target
  gate fidelity → physical error rate
  → code distance d
  → physical qubits per logical qubit (2d²-1)
  → total physical qubits (compute + factory placeholder)
```

### What the Estimator Does NOT Yet Do

- **Coherence budget** — T1 and T2 from qubit profiles are loaded but not used. No breakdown of error budget by mechanism (TLS, quasiparticle, vortex motion, radiation).
- **Sensitivity analysis** — "if RRR improves, what happens to code distance?" Not yet wired.
- **Qubit profile effect** — the qubit dropdown loads the correct profile but only `two_qubit_fidelity_pct` is read from it. T1, T2, gate times are stored but unused.
- **T gate counting** — placeholder (0). Magic state factory costs underestimated for T-heavy circuits.

---

## Corpus Mining Pipeline — Current State

Operational end-to-end. Lives in `ingester/pipeline_mining.py`, runs as Stage 4 of the ingestion pipeline UI.

**Current results (April 28):** 41 correlations found → 11 out of scope, 16 corpus gaps, 13 hypotheses matched → 3 findings produced (all negative/inconclusive). Key insight: cross-material hypothesis testing is confounded by material identity. Per-material-class analysis is the architectural fix.

**Running:**
```bash
cd ingester
python3 pipeline_mining.py phase-a   # mechanical evidence extraction
python3 pipeline_mining.py phase-b   # AI reasoning
python3 pipeline_mining.py phase-c   # AI write-up + human-reviewable findings
```

---

## Schema Evolution — Current State

Three fields promoted to Block 3 in schema v0.7 (April 28): `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K`. These are confirmed ready as named SQLite columns — values already in `catchall_items.value` as clean numerics. **Promotion not yet implemented in `build_sqlite.py`** — this is the first Track A priority.

**Domain rule:** Only geometry-independent (intrinsic) properties are promotable. Sheet Lk yes, total Lk no. Jc-material yes, Ic no.

**Ic/Jc disambiguation** — two physically distinct quantities currently conflated in catchall. Needs `derived_material_Jc_A_m2` and `derived_junction_Jc_uA_um2` columns and extraction prompt fix. Flagged for future work.

---

## Hosted Infrastructure

| Service | URL | Auto-deploys from |
|---|---|---|
| Materials Explorer | https://c2qa-materials-explorer.onrender.com | GitHub main branch |
| Baby QREM | Local only (localhost:8000) | — |
| Ingestion + Mining Pipeline | Local only (localhost:8001/ingest_pipeline.html) | — |

Mining pipeline is intentionally local-only — requires API keys, database write access, long-running AI calls.

**Workflow:** Run mining locally → approve findings → git push → Explorer auto-redeploys.

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

# Backfill similarity profiles (if vocabulary changes)
python3 backfill_similarity_profiles.py --dry-run
python3 backfill_similarity_profiles.py
```

---

## Coding Priorities — Next Sessions

### Track A: Mining + Schema (ingester side)

**1. Schema promotion implementation** — add `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K` as named columns in `build_sqlite.py`, reading from `catchall_items.value`. Rebuild SQLite. Re-run Phase A — expect significantly more hypotheses with cross-sample evidence now that these fields are queryable.

**2. Per-material-class Phase A** — modify Phase A to build evidence tables stratified by material class (Ta, Ta-Hf, NbSe2, NbN) in addition to cross-corpus tables. The Bahrami Ta series (8 samples, wide mean free path range, vortex activation temperature measured) is particularly promising. This is the architectural fix Phase B identified.

**3. Stage 4 schema evolution UI** — surface the measurement frequency report in the ingestion pipeline for human approval of field promotions.

**4. Explorer Findings tab** — read-only view of approved `findings.jsonl` on the hosted Explorer, updating on git push.

### Track B: Baby QREM (next capabilities)

**5. Coherence budget output** — T1 loss attribution by mechanism: TLS, quasiparticle, vortex motion, radiation. Reads T1 and T2 from the qubit profile and computes fractional contributions. Makes the qubit profile dropdown meaningful beyond just gate fidelity. This is the next Baby QREM development priority.

**6. Sensitivity analysis** — "if T1 improves from 50µs to 100µs, what happens to code distance?" or "if RRR improves from 45 to 65, what changes?" Routes material property improvements through the coherence budget to physical qubit count. The most useful output for materials scientists. Depends on coherence budget being in place first.

**7. Qubit profile → gate fidelity connection** — currently only `two_qubit_fidelity_pct` is read from qubit profiles. T1 and T2 should constrain the achievable gate fidelity (T1-limited gate fidelity ≈ 1 - gate_time/T1). Wiring this makes corpus-derived profiles fully functional.

### Medium effort

**8. Ic/Jc disambiguation** — new `derive.py` functions, new schema columns, extraction prompt disambiguation.

**9. Mining config file** — extract domain-specific config (`FIELD_MAP`, `DEVICE_PHYSICS_TERMS`, system prompts) to `mining_config.yaml`. Same philosophy as QREM hardware profiles — configuration as data.

**10. Corpus expansion** — older literature ingestion; policy/priority question.

**11. Supplementary information linking** — SI files linked to companion papers via DOI-based naming convention.

### Larger effort

**12. Materials Predictor** — Gaussian process regression per material class.

**13. Tier 2 reconnection** — modular overhead, when Center-wide architecture research matures. Functions preserved in `estimator_tier2_modular.py`, `EstimationResult` fields already declared as `Optional`.

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — self-contained. Hardware profiles, similarity profiles, and mining findings are projections of records.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. Every mining finding requires human review before entering `findings.jsonl`.
- **Sparse extraction** — only fields actually reported in a paper are included. Absence = not reported, never zero.
- **Derived quantities live in SQLite, not JSONL** — computed at build time, no re-ingestion needed.
- **Configuration as data, not code** — hardware profiles, mining field maps, domain context are YAML/config files, not hardcoded logic.
- **Explicit assumptions in every output** — QREM documents all simplifying assumptions; mining pipeline documents all classification decisions.
- **Single-module first** — materials → single-module resource estimator is the primary Baby QREM deliverable. Modular overhead (Tier 2) is a separate Center-wide research problem.
- **Schema evolution is frequency-driven** — promotion candidates surface from measurement frequency across corpus, not per-paper AI judgment.
- **Geometry-independent properties only** — only intrinsic material properties promotable to named columns. Sheet Lk yes, total Lk no.
- **Circuit depth drives error correction** — the per-gate LER target is derived from circuit depth and circuit success rate, not hardcoded. Different circuits give different resource estimates.

---

## Data Provenance — Supplementary Files

Peer review is **inherited, not intrinsic**. SI files traceable to published papers inherit that paper's credibility. DOI-based naming convention `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf` — ingester recognizes pattern and ingests as one logical record. Not yet implemented.

| Source type | Confidence |
|---|---|
| Peer-reviewed paper (main text) | Highest |
| SI file linked via DOI | High |
| arXiv preprint | Medium-high |
| External database entry with traceable DOI | Medium |
| External database entry, no publication | Low |

---

## Longer-Term Vision

The PUK concept scales to a **federated knowledge graph for quantum computing research** built from public literature — continuously updated, AI-maintained, finding connections across centers and disciplines that no human would have bandwidth to make.

---

*Last updated: April 29, 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
