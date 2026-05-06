# Modular Quantum Computing Resource Estimation Framework
## Pipeline Specification & Design Document

**Version:** 0.5 — Modular profile system, inter-module cost model, two-tier estimation framework
**Date:** April 26, 2026
**Status:** Stages 1–3 complete; UI operational; Materials pipeline connected
**Intended audience:** Computer scientists, quantum architects, device scientists, materials scientists

---

## Key Design Decisions

**OpenQASM as input boundary.** The tool does not handle algorithm-to-circuit compilation — that is handled by existing tools (Qiskit, Cirq, etc.). Accepting OpenQASM makes QREM compatible with any compiler that produces it.

**Strict separation of logical and physical worlds.** Stages 1–2 operate on the ideal, noiseless logical circuit. Error correction and hardware imperfections enter only in Stage 3.

**Two-tier estimation architecture.** Resource costs separate naturally into two tiers with different scientific grounding:
- **Tier 1 — Single-module baseline:** code distance and physical qubits per logical qubit, driven entirely by qubit fidelity and surface code theory. Well-grounded analytically. Independent of any inter-module assumptions.
- **Tier 2 — Modular overhead:** module count, inter-module operations, communication qubit cost, runtime slowdown from lattice surgery. Driven by module and interconnect profiles. More assumptions, active research area, explicitly flagged as such.

This separation is intentional. Tier 1 answers "what does this algorithm fundamentally cost in qubits, given this qubit quality?" Tier 2 answers "what does distributing across modules add on top?" A materials scientist improving qubit T1 moves Tier 1; a hardware engineer improving link fidelity moves Tier 2.

**Modular hardware profiles.** Platform parameters are split across four independent YAML files — qubits, interconnects, modules, error correction — that can be mixed and matched in the UI. The monolithic profile approach has been retired.

**Honest uncertainty representation.** All simplifying assumptions are explicitly documented in every tool output. The catalog of unknowns is itself a scientific contribution.

**Hardware profiles as Portable Units of Knowledge (PUKs).** Qubit profiles generated from corpus records carry full provenance — which sample, which fields were measured vs assumed. The near-term architecture uses YAML files; the target architecture has QREM querying the materials database directly, generating profiles in memory.

---

## Alignment with DOE QREM Goals

| Goal | Description | Status |
|---|---|---|
| **1.2.1** | Establish QREM as Center-wide framework; fault-tolerant abstract machine model | Specification complete. Stages 1–3 implemented. |
| **1.2.2** | Quantitative baseline for modular atomic quantum processors | Neutral atom profile pending. |
| **1.2.3** | Quantitative baseline for superconducting modular systems | Superconducting profiles implemented. Corpus-derived qubit profiles operational. |

---

## System Architecture

QREM is one component in the C2QA materials-to-resource pipeline:

```
Scientific Papers
      ↓
[Ingester] → Materials Database (PUKs)
      |
      |── Measured device performance (T1, T2, gate fidelity) ────────────────┐
      |   → Hardware Profile Updater → qubit profile YAML                     ↓
      |                                                               [QREM Pipeline]
      |── Measured inter-module properties ──────────────────────────────►    ↑
      |   (link fidelity, entanglement rate, transduction efficiency)          |
      |   → interconnect profile YAML                                          |
      |                                                                        |
      └── Material properties only (Tc, RRR, resistivity, loss tangent)       |
          → Materials Predictor → Mapping Layer (planned) ────────────────────┘
```

**The scientific question the full pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and use it in a modular architecture to run this quantum algorithm, how many modules would I need?"*

---

## Pipeline Architecture

```
OpenQASM Circuit  +  Hardware Profiles (qubit + interconnect + module + QEC)
         |
    [Stage 1]  PARSE
         |          → CircuitIR (gate list, qubit inventory, gate counts)
    [Stage 2]  ANALYZE  (Logical World)
         |          → AnalysisResult (interaction graph, hub qubits, locality score)
    [Stage 3]  MODEL + ESTIMATE  (Physical World)
         |         Tier 1: Error Correction Layer → code distance, phys qubits/logical
         |         Tier 2: Inter-Module Cost Model → modules, slowdown, comm qubits
         |         Magic State Factory Estimation
         |          → EstimationResult (full resource breakdown + explicit assumptions)
    [Stage 4]  COMPARE & REPORT  (not yet implemented)
         |
  Resource Report  +  Sensitivity Analysis  +  Device Target Specification
```

---

## Implementation Status

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Parser + Analyzer (Stages 1–2) | ✅ Complete |
| **Phase 2** | Superconducting estimator (Stage 3) + UI | ✅ Complete |
| **Phase 3** | Cross-platform comparison; neutral atom profile | Pending |
| **Phase 4** | Sensitivity analysis; threshold detection; device target specs | Pending |
| **Phase 5** | Materials-to-Device Mapping Layer | In parallel development |
| **Phase 6** | Expert component replacement (Arquin, HetArch, Stim) | Pending |

### Code Structure

```
src/qrem/
  parser.py                     — Stage 1: OpenQASM → CircuitIR
  circuit_ir.py                 — Internal circuit representation
  analyzer.py                   — Stage 2: interaction graph + metrics
  estimator.py                  — Stage 3: physical resource estimation
  profile_loader.py             — Modular profile loader (merges four YAMLs)
  hardware_profiles/
    qubits/
      transmon_baseline_2026.yaml     — Hand-tuned superconducting baseline
      {sample_display_name}.yaml      — Corpus-derived profiles (generated by Hardware Profile Updater)
    interconnects/
      microwave_photonic_85pct.yaml   — Conservative baseline (2 purification rounds)
      microwave_photonic_92pct.yaml   — Near-term target (1 purification round)
      microwave_photonic_99pct.yaml   — Aspirational (no purification needed)
    modules/
      module_1000q_nearest_neighbor.yaml
    error_correction/
      surface_code_1e6.yaml
    superconducting.yaml              — Legacy monolithic profile (still supported)

scripts/
  serve.py                      — HTTP server for Baby QREM UI
  qrem_ui.html                  — Baby QREM browser UI
```

### Running the Pipeline

```bash
# CLI
cd src/qrem
python3 estimator.py ../../data/circuits/test_circuit.qasm hardware_profiles/superconducting.yaml

# UI
python3 scripts/serve.py
# Open http://localhost:8000/scripts/qrem_ui.html
```

### Validated Results

| Circuit | Fidelity | Code distance | Phys qubits/logical | Modules |
|---|---|---|---|---|
| test_circuit (5 qubits) | 99.5% | 39 | 3,041 | 16 |
| test_circuit (5 qubits) | 99.9% | 11 | 241 | 2 |
| test_circuit_02 (4 qubits) | 99.5% | 39 | 3,041 | 13 |
| test_circuit_02 (4 qubits) | 99.9% | 11 | 241 | 1 |

A 0.4% improvement in two-qubit gate fidelity (99.5% → 99.9%) reduces module count from 16 to 2. This is the core quantitative insight the tool is designed to surface.

---

## Stage 1 — Parse

**Status: Complete** | `parser.py`

Reads OpenQASM and produces CircuitIR: qubit inventory, ordered gate list, gate count summary. T gates tracked separately for magic state factory estimation.

---

## Stage 2 — Analyze

**Status: Complete** | `analyzer.py`

Operates entirely in the logical world. Builds a weighted qubit interaction graph.

**Outputs:** interaction graph, hub qubits (most expensive to place across module boundaries), locality score (0.0 = spread broadly, 1.0 = same pairs interact repeatedly), greedy module partitioning.

**Not yet implemented:** Circuit depth and critical path (needed for runtime estimation in Stage 4).

---

## Stage 3 — Model

**Status: Complete for superconducting platform** | `estimator.py`

### Tier 1 — Single-Module Baseline

The well-grounded core. Driven entirely by qubit fidelity and surface code theory.

```
physical_error_rate = 1 - two_qubit_fidelity_pct / 100
logical_error_rate ≈ (physical_error_rate / threshold) ^ ((d+1)/2)
physical_qubits_per_logical = 2d² - 1
```

Minimum odd d satisfying the target logical error rate is selected as code distance.

**Currently used from qubit profile:** `two_qubit_fidelity_pct` only.

**Stored but not yet used:** T1, T2, single-qubit fidelity, readout fidelity, gate times. These become relevant in Stage 4 for runtime estimation and coherence budget analysis.

### Tier 2 — Modular Overhead

The shakier ground — active research area, explicitly flagged. Driven by interconnect and module profiles.

**Inter-module cost model (lattice surgery framing):**
- Logical qubits are assumed to fit entirely within one module — QEC does not cross module boundaries
- Inter-module logical operations are performed via lattice surgery, consuming purified Bell pairs
- Raw Bell pair fidelity below the surface code threshold (~99%) requires entanglement purification before use

**Purification model (DEJMPS protocol, idealized):**

| Interconnect tier | Raw fidelity | Purification rounds | Effective gate time | Slowdown factor |
|---|---|---|---|---|
| microwave_photonic_85pct | 85% | 2 | 1,040 µs | 5,200× |
| microwave_photonic_92pct | 92% | 1 | 220 µs | 1,100× |
| microwave_photonic_99pct | 99% | 0 | 110 µs | 550× |

The slowdown factor is the runtime cost of one inter-module logical gate relative to a local two-qubit gate. Even the aspirational 99% tier has a 550× slowdown due to fundamental Bell pair generation latency — this floor cannot be eliminated with the current photonic approach.

The jump from 85% to 92% (eliminating one purification round) is more impactful than 92% to 99%. Each purification round boundary is a threshold: crossing it roughly halves the slowdown factor.

**Communication qubit overhead:** Physical qubits reserved at module boundaries for purification operations. Small (~8 qubits per link at 85%) but real.

**Module count:**
```
num_modules = ceil(total_physical_qubits / physical_qubits_per_module)
total_physical_qubits = computation_qubits + factory_qubits + communication_qubits
```

### Assumptions (reported in every output)

1. Perfect intra-module connectivity — no SWAP routing overhead. Physical qubit counts are lower bounds.
2. Analytical surface code approximation — not full Stim simulation.
3. Greedy module assignment — not optimal graph partitioning. Optimal partitioning should minimize inter-module operations since each carries large runtime cost.
4. Logical qubits fit entirely within one module. QEC does not cross module boundaries.
5. Inter-module operations modeled as runtime cost only. Full circuit runtime impact requires depth analysis (Stage 4).
6. Purification model is idealized — real fidelity after purification will be somewhat lower.
7. Communication qubit count assumes chain topology (num_modules - 1 links).
8. T gate count placeholder (0) — magic state factory costs underestimated for T-gate-heavy circuits.

### Hardware Profile System

Four independent YAML files, mixed and matched via UI dropdowns:

**Qubit profiles** (`hardware_profiles/qubits/`) — coherence and gate parameters. Generated from corpus records by the Hardware Profile Updater, or hand-tuned. Each profile carries a provenance block: which corpus sample, which fields were measured vs assumed.

**Interconnect profiles** (`hardware_profiles/interconnects/`) — raw link fidelity, entanglement rate, purification model, effective parameters. Three tiers provided for sensitivity analysis.

**Module profiles** (`hardware_profiles/modules/`) — qubits per module, connectivity.

**Error correction profiles** (`hardware_profiles/error_correction/`) — QEC code, target logical error rate, threshold.

`profile_loader.py` merges the four files into one dict. Legacy monolithic `superconducting.yaml` still supported.

---

## Baby QREM UI

**Local:** `http://localhost:8000/scripts/qrem_ui.html`

**Controls:** Circuit dropdown, four hardware profile dropdowns (qubit/interconnect/module/error correction), two-qubit gate fidelity slider (overrides qubit profile gate fidelity for sensitivity analysis), Run Estimation button.

**Metric cards (seven):** Code Distance, Phys/Logical, Logical Qubits, Total Physical, Modules, Inter-Module fraction, Link Slowdown. Each card has a `›` expand affordance showing the calculation and substituted values — progressive disclosure for non-experts.

**Staircase chart:** Fidelity → Module Count curve with current position marked. Shows threshold effects — points where a small fidelity improvement drops you to the next step.

**Status bar:** Feasible/Not Feasible, error rate, logical error rate, platform.

**API endpoints (served by `scripts/serve.py`):**
- `GET /api/profiles` — available profile names for each component (populates dropdowns)
- `GET /api/circuits` — available .qasm files
- `POST /api/estimate` — run estimation with modular profile selection

---

## Hardware Profile Updater

**Status: Complete** | `ingester/generate_qubit_profile.py`

Generates a QREM qubit profile YAML from a materials database sample record. Triggered via the "⚙ Generate Qubit Profile" button in the Materials Explorer detail panel.

- Measured fields (T1, T2, gate fidelity, readout fidelity, gate times) → used directly, labeled `[MEASURED]`
- Unmeasured fields → defaults from `transmon_baseline_2026.yaml`, labeled `[ASSUMED]`
- Full provenance block in the generated YAML

Generated profiles appear immediately in the Baby QREM qubit dropdown via `list_profiles()`.

**Note:** Most materials papers measure T1 and T2 but not gate fidelity — gate performance requires two coupled qubits and randomized benchmarking, which is beyond the scope of most materials characterization papers. Profiles from such papers will have measured coherence but assumed gate parameters.

**Architecture note:** The current YAML approach is transitional. The target architecture has QREM querying the database directly, generating profiles in memory. The record (PUK) remains the source of truth.

---

## Materials-to-Device Mapping Layer

**Status: Design phase; being populated from materials database**

Bridges material properties to device parameters for samples without direct device measurements.

### Direct Paths (no mapping needed)
- T1, T2, gate fidelity → qubit profile (via Hardware Profile Updater)
- Link fidelity, entanglement rate, transduction efficiency → interconnect profile

### Indirect Paths (require modeling)

| Noise channel | Material predictors | QREM output |
|---|---|---|
| Quasiparticle | T/Tc ratio, RRR | T1 |
| TLS dielectric | Loss tangent, surface oxide thickness | T1, T2, Qi |
| Vortex motion | Coherence length, mean free path | Qi, T1 |
| 1/f flux noise | Surface spin density, crystal phase | T2 |

### Populating the Layer

Near-term strategy: mine the ~31 author-stated correlations in the catchall corpus, rank by number of supporting papers, implement best-supported connections as initial mapping functions. This is Phase 3 of the ingester development.

---

## Stage 4 — Compare & Report

**Status: Not yet implemented**

**For quantum architects:** Cross-platform comparison; resource cost attribution (algorithmic complexity vs hardware overhead).

**For device engineers:** Sensitivity analysis; threshold identification; device target specification.

**For materials scientists:** What-if engine — "if I improve RRR from 45 to 65, how much does module count change?" Routes material property improvements through the full pipeline to system-level impact.

Stage 4 is also where T1 and T2 from corpus records become fully meaningful — circuit runtime estimation requires coherence budget analysis, which needs these fields.

---

## Pluggable Components

| Component | Location | Status | Expert replacement |
|---|---|---|---|
| Circuit parser | `parser.py` | Complete | — |
| Graph partitioning | `analyzer.py` | Greedy placeholder | Arquin, combinatorial optimization |
| Error correction model | `estimator.py` | Analytical placeholder | HetArch, Stim |
| Magic state factory model | `estimator.py` | Simplified placeholder | Full distillation model |
| Inter-module cost model | `estimator.py` | Purification placeholder | Arquin |
| Qubit profiles | `hardware_profiles/qubits/` | Baseline + corpus-derived | Device physics measurements |
| Interconnect profiles | `hardware_profiles/interconnects/` | Three tiers | Experimental link characterization |
| Materials-to-device mappings | `materials/mapping_layer/` | Not yet implemented | Materials science |

---

## Open Research Questions

The inter-module interface is where the hardest open questions live — it is the current frontier of modular quantum computing:

- What is the correct cost model for inter-module entanglement generation? The purification model implemented is idealized (perfect local gates, DEJMPS protocol).
- How does QEC work across module boundaries in practice? Lattice surgery is the leading approach but full protocols for modular surface codes are still being developed.
- What graph partitioning objective best minimizes actual resource cost? Minimizing inter-module gate count is a proxy — the true objective involves gate scheduling, critical path, and purification latency.
- How does classical communication latency for error syndrome propagation scale with module count and topology?
- What is the correct magic state factory count as a function of T gate rate and circuit depth?
- How should uncertainty in materials-to-device mappings propagate through the full pipeline?
- Are there circuit classes for which one platform is categorically superior regardless of hardware parameters?
- How does SWAP routing overhead scale with module size and circuit interaction graph density?

---

## C2QA Ecosystem Integration

| Tool | Role | Location in pipeline |
|---|---|---|
| **Arquin** | Inter-module cost model | Replaces simplified placeholder in Stage 3 |
| **HetArch** | Error correction layer | Replaces analytical approximation |
| **Bosonic ISA** | Qumode support | Requires parser/analyzer/model extensions |
| **Qualtran** (Google) | Algorithm-level resource estimation | Upstream of Stage 1 |
| **Stim** | High-performance QEC simulation | Error correction layer replacement |
| **Azure QRE** (Microsoft) | Industry resource estimator | Validation baseline |

---

*End of Specification Document v0.5*
*Updated April 26, 2026.*
*This document is intended to evolve with the research.*
