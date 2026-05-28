# C2QA QREM — Project Architecture & Next Steps
## Continuity Document — April 26, 2026

---

## The Five Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | Stages 1-3 complete. Modular profile system operational. UI live. Stage 4 (sensitivity analysis) pending. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | Operational. 91 papers, 134 samples, ~1,200 catchall items. Hardware Profile Updater integrated. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | Working. Strip plot, scatter, ranked list, data table, catchall, slide-in detail panel, Generate Profile button. Hosted at https://c2qa-materials-explorer.onrender.com |
| 4 | **Materials Predictor** | Not yet built. Similarity search is the first step. |
| 5 | **Materials-to-Device Mapping Layer** | Designed, not built. Connects materials side to QREM side. |

---

## How They Connect

```
Scientific Papers
      ↓
[2] Publications Ingester
      ↓
[3] Materials Database
    (Tc, RRR, Qi, T1, derived quantities, catchall)
      |
      |── Measured device performance (T1, T2, gate fidelity) ─────────────┐
      |   → Hardware Profile Updater → qubit profile YAML                  ↓
      |                                                            [1] Baby QREM
      |── Measured inter-module properties ─────────────────────►          ↑
      |   (link fidelity, entanglement rate, transduction efficiency)       |
      |   → interconnect profile YAML                                       |
      |                                                                     |
      └── Material properties only (Tc, RRR, resistivity, loss tangent)    |
          → [4] Materials Predictor                                         |
               → [5] Mapping Layer ─────────────────────────────────────────┘
```

**Key design point:** Measured device performance goes straight to QREM via the Hardware Profile Updater — no predictor needed. The predictor is only needed for samples where only material properties were measured, which is the majority of the corpus (T1 coverage is only 12%).

**The scientific question the full pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and use it in a modular architecture to run this quantum algorithm, how many modules would I need?"*

---

## Two-Tier Estimation Architecture

A key conceptual clarification made this session: QREM resource costs separate into two tiers with very different scientific grounding.

**Tier 1 — Single-module baseline:**
- Code distance and physical qubits per logical qubit
- Driven entirely by `two_qubit_fidelity_pct` and surface code theory
- Well-grounded analytically, independent of any inter-module assumptions
- This is what the staircase chart shows

**Tier 2 — Modular overhead:**
- Module count, inter-module operations, communication qubit cost, runtime slowdown
- Driven by interconnect and module profiles
- Active research area — more assumptions, explicitly flagged
- Lattice surgery framing: inter-module operations consume purified Bell pairs; QEC never crosses module boundaries

The separation matters: a materials scientist improving qubit coherence moves Tier 1. A hardware engineer improving link fidelity moves Tier 2. The UI redesign task should surface these as distinct sections.

---

## Inter-Module Link Model (new this session)

The inter-module cost model now includes a purification model grounded in real physics (DEJMPS protocol):

| Interconnect tier | Raw fidelity | Purification rounds | Effective gate time | Slowdown factor |
|---|---|---|---|---|
| microwave_photonic_85pct | 85% | 2 | 1,040 µs | 5,200× |
| microwave_photonic_92pct | 92% | 1 | 220 µs | 1,100× |
| microwave_photonic_99pct | 99% | 0 | 110 µs | 550× |

Key insight: the jump from 85% to 92% (eliminating one purification round) is 5× more impactful than 92% to 99%. Each purification round boundary is a threshold.

The slowdown factor is a runtime cost, not a qubit survival issue — idle qubits are protected by continuous QEC. The cost is circuit runtime and space-time volume, which modestly increases logical error probability for long circuits but is second-order for small circuits.

---

## PUK Architecture

Records in the materials database are **Portable Units of Knowledge (PUKs)** — self-contained, everything about a sample in one place. Hardware profile YAMLs are projections of PUKs, not independent sources of truth.

**Current (transitional):** Hardware Profile Updater generates YAML files from PUKs. QREM reads YAMLs.

**Target architecture:** QREM queries the database directly, generates profiles in memory, never saves YAMLs. No sync problem, always fresh. The "Generate Profile" button remains useful for manual inspection.

The Block 4 write-back path — QREM computing device performance implications and storing them back in the PUK — is the intended long-term flow.

---

## Hardware Profile System (new this session)

Monolithic `superconducting.yaml` retired in favor of four independent YAML files:

```
hardware_profiles/
  qubits/
    transmon_baseline_2026.yaml     — hand-tuned baseline
    Wang_2026_Transmon_1.yaml       — generated from corpus (T1=297µs, T2=459µs measured)
    Wang_2026_Transmon_2.yaml       — generated from corpus
  interconnects/
    microwave_photonic_85pct.yaml   — conservative baseline
    microwave_photonic_92pct.yaml   — near-term target
    microwave_photonic_99pct.yaml   — aspirational
  modules/
    module_1000q_nearest_neighbor.yaml
  error_correction/
    surface_code_1e6.yaml
```

`profile_loader.py` merges four files into one dict. Legacy `superconducting.yaml` still supported.

Baby QREM UI has four independent dropdowns — mix and match profiles for sensitivity analysis.

---

## What QREM Currently Uses vs Stores

**Currently used in estimation:**
- `two_qubit_fidelity_pct` → drives all of Tier 1 (code distance, physical qubits)
- Interconnect effective parameters → Tier 2 (slowdown, comm qubits, runtime note)

**Stored but not yet used:**
- T1, T2 — relevant for Stage 4 runtime estimation and coherence budget
- Single-qubit fidelity, readout fidelity, gate times — Stage 4
- Transduction efficiency — affects entanglement rate, not yet modeled

T1 and T2 set a ceiling on gate fidelity (decoherence-limited upper bound) but actual gate fidelity depends heavily on control errors — most materials papers don't measure gate fidelity because it requires two coupled qubits and randomized benchmarking.

---

## Hosted Infrastructure

| Service | URL | Auto-deploys from |
|---|---|---|
| Materials Explorer | https://c2qa-materials-explorer.onrender.com | GitHub main branch |
| Baby QREM | Local only (localhost:8000) | — |

Render free tier spins down on inactivity — first load after idle period takes ~50 seconds.

To update hosted Explorer: `git push` → Render rebuilds automatically in ~2 minutes.

---

## Coding Priorities — Next Sessions

**Medium effort (one session each):**

1. **Similarity search** — given a material description, find N most similar corpus samples. Pure SQL + distance metric over structured fields. First concrete step toward the Materials Predictor. Immediately useful on its own.

2. **Catchall mining** — run Claude over the ~31 author-stated correlations and ~750 additional measurements to extract and rank materials-to-device connections. These become the initial entries in the QREM mapping layer.

3. **QREM UI redesign with progressive disclosure** — rethink the layout: compact staircase strip with threshold callout, expandable calculation cards showing math at each stage, two-tier output structure (Tier 1 baseline separate from Tier 2 modular overhead). Groundwork laid (expand cards exist), bigger layout rethink still needed.

4. **Automatic profile generation at ingestion** — when a paper with T1/T2 data is ingested, automatically generate a qubit profile YAML. Currently requires manual button click in Explorer.

**Larger effort (multiple sessions):**

5. **Materials Predictor** — similarity search + Gaussian process regression per material class. Gives predicted T1/Qi/gate fidelity + uncertainty bounds + grounding in specific corpus samples. Builds on similarity search.

6. **Materials-to-Device Mapping Layer** — physics-based bridge from material properties to device parameters. Feeds QREM when direct measurement isn't available.

7. **QREM Stage 4** — sensitivity analysis, threshold detection, device target specification, cross-platform comparison. What-if engine: "if I improve RRR from 45 to 65, how much does module count change?"

8. **Neutral atom hardware profile** — just a data file following existing YAML structure. Enables cross-platform comparison for Stage 4.

---

## Repository & Running

**GitHub:** `https://github.com/ctblack-bnl/c2qa-qrem`

```bash
# Standard commit workflow
git add .
git commit -m "description"
git push   # also triggers Render redeploy of Materials Explorer
```

```bash
# Run Materials Explorer (port 8001)
cd ingester && python3 serve_materials.py

# Run Baby QREM (port 8000)
cd 2026-04\ c2qa_qrem && python3 scripts/serve.py
```

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — each record is self-contained. Hardware profiles are projections of records, not independent sources of truth.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. `human_reviewed: false` until reviewed.
- **Sparse extraction** — only fields actually reported in a paper are included. Absence = not reported, never zero.
- **Derived quantities live in SQLite, not JSONL** — computed at build time, no re-ingestion needed.
- **Hardware profiles as YAML data, not code** — changing platforms requires only editing a data file.
- **Explicit assumptions in every output** — QREM documents all simplifying assumptions; the catalog of unknowns is itself a scientific contribution.
- **Two-tier separation** — Tier 1 (qubit physics, solid ground) always separated from Tier 2 (modular overhead, shakier ground).

---

*Last updated: April 26, 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
