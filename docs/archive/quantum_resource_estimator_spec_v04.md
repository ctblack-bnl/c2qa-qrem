# Modular Quantum Computing Resource Estimation Framework
## Pipeline Specification & Design Document

**Version:** 0.4 — Streamlined; Materials pipeline connection documented
**Date:** April 25, 2026
**Status:** Phases 1–2 complete; Phase 3 pending; Materials pipeline operational in parallel
**Intended audience:** Computer scientists, quantum architects, device scientists, materials scientists

---

## Key Design Decisions

**OpenQASM as input boundary.** The tool does not handle algorithm-to-circuit compilation — that is handled by existing tools (Qiskit, Cirq, etc.). Accepting OpenQASM makes QREM compatible with any compiler that produces it.

**Strict separation of logical and physical worlds.** Stages 1–2 operate on the ideal, noiseless logical circuit. Error correction and hardware imperfections enter only in Stage 3. This allows resource costs to be attributed separately to algorithmic complexity vs hardware overhead.

**Differential error correction for local vs inter-module gates.** Inter-module gates are noisier and slower than local operations — they require higher code distance. This distinction is one of the most novel aspects of the tool; existing tools do not handle it.

**Hardware profiles as data, not code.** Platform parameters (superconducting, neutral atom) are YAML files. Adding a new platform requires only a new data file, not new pipeline logic.

**Pluggability above all.** Every major component has a defined interface and can be replaced independently. Expert contributors can improve individual components without touching the rest of the pipeline.

**Honest uncertainty representation.** All simplifying assumptions are explicitly documented in every tool output. The catalog of unknowns is itself a scientific contribution.

**Magic state factories accounted for explicitly.** T gates require dedicated distillation factory circuits consuming ~1,000 physical qubits each. A circuit with many T gates may require more factory qubits than computation qubits.

---

## Alignment with DOE QREM Goals

| Goal | Description | Status |
|---|---|---|
| **1.2.1** | Establish QREM as a Center-wide framework; define architecture and fault-tolerant abstract machine model | Specification complete. Phases 1–2 implemented. |
| **1.2.2** | Define quantitative baseline for modular atomic quantum processors | Experimental outputs will feed neutral atom hardware profile (pending). |
| **1.2.3** | Define quantitative baseline for superconducting modular systems | Superconducting baseline profile implemented with current state-of-the-art parameters. |

---

## System Architecture

QREM is one of five components in the C2QA materials-to-resource pipeline:

```
Scientific Papers
      ↓
[Ingester] Publications ingester → Materials Database
      |
      |── Measured device performance (T1, T2, gate fidelity, Qi)  ─────────┐
      |   → direct to QREM hardware profile                                 ↓
      |                                                              [QREM Pipeline]
      |── Measured inter-module properties ──────────────────────►          ↑
      |   (link fidelity, entanglement rate, transduction efficiency)        |
      |   → direct to QREM hardware profile                                  |
      |                                                                      |
      └── Material properties only (Tc, RRR, resistivity, loss tangent)     |
          → Materials Predictor → Mapping Layer ──────────────────────────────┘
```

**The scientific question the full pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and use it in a modular architecture to run this quantum algorithm, how many modules would I need?"*

---

## Pipeline Architecture

```
OpenQASM Circuit  +  Hardware Profile  +  Target Error Rate
         |
    [Stage 1]  PARSE
         |          → CircuitIR (gate list, qubit inventory, gate counts)
    [Stage 2]  ANALYZE  (Logical World)
         |          → AnalysisResult (interaction graph, hub qubits, locality score)
    [Stage 3]  MODEL + ESTIMATE  (Physical World)
         |              Error Correction Layer
         |              Magic State Factory Estimation
         |              Inter-Module Cost Model
         |          → EstimationResult (physical qubits, modules, feasibility, assumptions)
    [Stage 4]  COMPARE & REPORT  (not yet implemented)
         |
  Resource Report  +  Sensitivity Analysis  +  Device Target Specification
```

---

## Implementation Status

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Parser + Analyzer (Stages 1–2) | ✅ Complete |
| **Phase 2** | Superconducting estimator (Stage 3) | ✅ Complete |
| **Phase 3** | Cross-platform comparison; neutral atom profile | Pending |
| **Phase 4** | Sensitivity analysis; threshold detection; device target specs | Pending |
| **Phase 5** | Materials-to-Device Mapping Layer | In parallel development |
| **Phase 6** | Expert component replacement (Arquin, HetArch, Stim) | Pending |

### Running the Pipeline

```bash
cd src/qrem
python3 parser.py ../../data/circuits/test_circuit.qasm
python3 analyzer.py ../../data/circuits/test_circuit.qasm
python3 estimator.py ../../data/circuits/test_circuit.qasm hardware_profiles/superconducting.yaml
```

### Validated Results

| Circuit | Fidelity | Code distance | Phys qubits/logical | Modules |
|---|---|---|---|---|
| test_circuit (5 qubits) | 99.5% | 39 | 3,041 | 16 |
| test_circuit (5 qubits) | 99.9% | 11 | 241 | 2 |
| test_circuit_02 (4 qubits) | 99.5% | 39 | 3,041 | 13 |
| test_circuit_02 (4 qubits) | 99.9% | 11 | 241 | 1 |

A 0.4% improvement in two-qubit gate fidelity (99.5% → 99.9%) reduces module count from 16 to 2 for the syndrome measurement circuit. This is the core quantitative insight the tool is designed to surface.

### Code Structure

```
src/qrem/
  parser.py                   — Stage 1: OpenQASM → CircuitIR
  circuit_ir.py               — Internal circuit representation
  analyzer.py                 — Stage 2: interaction graph + metrics
  estimator.py                — Stages 3–4: physical resource estimation
  hardware_profiles/
    superconducting.yaml      — Superconducting baseline profile
    neutral_atom.yaml         — Placeholder (not yet implemented)
```

---

## Stage 1 — Parse

**Status: Complete** | `src/qrem/parser.py`

Reads an OpenQASM file and produces a CircuitIR: qubit inventory, ordered gate list, and gate count summary (single-qubit, two-qubit, measurements, T gates tracked separately).

| Gate type | Examples | Significance |
|---|---|---|
| `single_qubit` | H, X, Y, Z, S, T, Rz | No inter-qubit interaction |
| `two_qubit` | CNOT, CZ, SWAP | Creates edges in interaction graph |
| `measurement` | measure | Contributes to readout overhead |

**Note on T gates:** Classified as single-qubit but tracked separately — they require magic state distillation in fault-tolerant computing. See Error Correction Layer.

---

## Stage 2 — Analyze

**Status: Complete** | `src/qrem/analyzer.py`

Operates entirely in the logical world. Builds a weighted qubit interaction graph and extracts structural metrics.

**Outputs:**
- Weighted interaction graph (nodes = qubits, edges = two-qubit gate pairs, weights = interaction frequency)
- Hub qubits — above-average interaction count; most expensive to place across module boundaries
- Locality score — 0.0 = interactions spread broadly, 1.0 = same pairs interact repeatedly. High locality is favorable for modular architectures.
- Module partitioning via greedy heuristic (hub-first, fill-then-advance)

**Not yet implemented:** Circuit depth and critical path (needed for runtime estimation).

---

## Error Correction Layer

**Status: Analytical approximation implemented**

Sits at the boundary between logical and physical worlds, invoked within Stage 3.

### Surface Code Model

```
logical_error_rate ≈ (physical_error_rate / threshold) ^ ((d+1)/2)
physical_qubits_per_logical = 2d² - 1
```

Minimum odd `d` satisfying the target logical error rate is selected as code distance.

**Example:** At 99.5% two-qubit fidelity, d=39, giving 3,041 physical qubits/logical. At 99.9%, d=11, giving 241 — a 12.6× reduction from a 0.4% fidelity improvement.

### Magic State Factories

T gates require dedicated factory circuits (~1,000 physical qubits each). Current implementation assumes 0 factories for T-gate-free circuits; 1 factory if T gates are present. Factory count scaling with T gate rate is a planned refinement.

### Simplifying Assumptions (reported in every output)

1. Analytical surface code approximation — not full Stim simulation
2. Uniform code distance — inter-module gates may require higher distance in practice
3. Simplified factory model — production rate vs demand rate not yet modeled

---

## Stage 3 — Model

**Status: Implemented for superconducting platform** | `src/qrem/estimator.py`

Translates logical circuit analysis into physical resource requirements for a specific hardware platform.

**Outputs:** physical error rate, code distance, physical qubits/logical (2d²-1), computation qubits, factory qubits, total physical qubits, module count, inter-module operation count and fraction, feasibility assessment, explicit assumption list.

### Superconducting Hardware Profile

`src/qrem/hardware_profiles/superconducting.yaml`

| Category | Parameter | Value | Notes |
|---|---|---|---|
| Coherence | T1 | 200 µs | Current best: 100–500 µs |
| | T2 | 300 µs | Typically ≤ 2×T1 |
| Gates | Single-qubit fidelity | 99.9% | |
| | Single-qubit gate time | 20 ns | |
| | Two-qubit fidelity | 99.9% | 99.5% also tested |
| | Two-qubit gate time | 200 ns | |
| | Readout fidelity | 99.5% | |
| | Readout time | 500 ns | |
| Module | Qubits per module | 1,000 | Near-term representative |
| | Connectivity | nearest_neighbor | |
| Inter-module | Link type | microwave_photonic | |
| | Link fidelity | 85% | Conservative baseline |
| | Entanglement rate | 1,000 Hz | |
| | Link latency | 10 µs | |
| | Transduction efficiency | 50% | Optimistic near-term |
| Error correction | Code | surface_code | |
| | Target logical error rate | 1×10⁻⁶ | |
| | Threshold | 1% | |

**Inter-module link fidelity tiers for sensitivity analysis:** 85% (conservative baseline), 92% (near-term target), 99% (aspirational).

### Module Count

```
num_modules = ceil(total_physical_qubits / physical_qubits_per_module)
```

### Simplifying Assumptions (reported in every output)

1. **Perfect intra-module connectivity** — no SWAP routing overhead modeled. Physical qubit estimates are lower bounds.
2. Analytical surface code approximation
3. Greedy module assignment
4. T gate count placeholder (0 for current test circuits)
5. Inter-module cost modeled as operation count only — latency and purification overhead not yet included

---

## Stage 4 — Compare & Report

**Status: Not yet implemented**

### Planned Outputs by Audience

**Computer scientists / quantum architects:** Side-by-side resource comparison across platforms; attribution of resource cost to algorithmic structure vs hardware overhead.

**Device engineers:** Sensitivity analysis; threshold identification; device target specification (given a resource budget, what are the minimum device parameters required?).

**Materials scientists:** Materials parameter sensitivity routed through the Mapping Layer; research priority guidance — which material improvements have the largest system-level impact?

---

## Materials-to-Device Mapping Layer

**Status: Design phase; being populated from materials database**

Bridges material properties (what materials scientists measure) to device parameters (what QREM needs).

### Direct Paths — No Mapping Needed

Some database fields map directly to QREM hardware profile parameters:
- Measured T1, T2, gate fidelity, Qi → straight to hardware profile
- Inter-module link fidelity, entanglement rate, transduction efficiency → straight to hardware profile

### Indirect Paths — Require Modeling

Material properties require physics-based noise modeling to reach QREM parameters:

| Noise channel | Material predictors | QREM output |
|---|---|---|
| Quasiparticle | T/Tc ratio, Rn | T1 |
| TLS dielectric | Loss tangent, surface oxide thickness | T1, T2, Qi |
| Vortex motion | Coherence length, mean free path | Qi, T1 |
| 1/f flux noise | Surface spin density, crystal phase | T2 |

### Layer Structure

Each mapping entry carries:

| Field | Description |
|---|---|
| `input` | Material parameter |
| `output` | Device parameter |
| `model` | Mapping function |
| `source` | Literature reference |
| `uncertainty` | Confidence bounds |
| `status` | `well_known` / `approximate` / `open_research` |

### Populating the Layer

The near-term strategy:
1. Mine the publications ingester catchall corpus (~31 author-stated correlations) for materials-to-device connections
2. Rank by how many papers support each connection
3. Implement best-supported connections as the initial mapping layer
4. Use structured database measurements (Tc, RRR, resistivity) to parameterize mapping functions

### Hardware Profile Updater (planned)

A script that reads measured device performance from the materials database and auto-generates a QREM hardware profile YAML. This is the most immediate missing connector — it enables the direct path from database to QREM that is already possible with today's corpus.

---

## Sensitivity Analysis and What-If Engine

**Status: Not yet implemented**

For each output metric (module count, physical qubits, runtime), compute how it responds to variation in each input parameter. The tool explicitly identifies threshold values where discrete improvements become achievable:

```
Two-qubit fidelity 99.5%  →  code distance 39  →  16 modules
Two-qubit fidelity 99.9%  →  code distance 11  →   2 modules
```

The ultimate goal is a what-if engine that answers: *"If I improve RRR from 45 to 65, how much does module count change?"* — routing material property improvements through the full pipeline to system-level resource impact.

---

## Software Architecture

### Pluggable Components

| Component | Location | Status | Expert Domain |
|---|---|---|---|
| Circuit parser | `src/qrem/parser.py` | Complete | Compiler / language design |
| Graph partitioning | `src/qrem/analyzer.py` | Greedy placeholder | Combinatorial optimization |
| Error correction model | `src/qrem/estimator.py` | Analytical placeholder | Quantum error correction |
| Magic state factory model | `src/qrem/estimator.py` | Simplified placeholder | Quantum error correction |
| Inter-module cost model | `src/qrem/estimator.py` | Simplified placeholder | Quantum networking |
| Hardware platform profiles | `src/qrem/hardware_profiles/` | SC complete; neutral atom pending | Device physics |
| Materials-to-device mappings | `materials/mapping_layer/` | Not yet implemented | Materials science |

### Dependencies

```
qiskit      — OpenQASM parsing
networkx    — Graph construction and analysis
pyyaml      — Hardware profile loading
```

### Known Deferred Items

**SWAP routing overhead:** Perfect intra-module connectivity is assumed. Physical qubit estimates are lower bounds. Neutral atom platforms are less affected since atoms can be physically rearranged.

**Circuit depth and critical path:** Needed for runtime estimation in Stage 4.

**T gate counting:** Currently a placeholder — needs wiring through from parser to estimator.

---

## C2QA Prior Art and Ecosystem Integration

### C2QA Tools

| Tool | Plugs into | Nature of fit |
|---|---|---|
| **Arquin** | Inter-module cost model | Direct replacement of simplified placeholder |
| **HetArch** | Error correction layer | Direct replacement of analytical approximation |
| **Bosonic ISA** | Requires pipeline extension | Parser/analyzer/model extensions needed for qumodes |

### Ecosystem Tools

| Tool | Role | Location in pipeline |
|---|---|---|
| **Qualtran** (Google) | Algorithm-level resource estimation | Upstream of Stage 1 |
| **Qiskit** (IBM) | Circuit compilation, OpenQASM generation | Upstream of Stage 1 (currently used for parsing) |
| **Stim** | High-performance QEC simulation | Error correction layer replacement |
| **Azure QRE** (Microsoft) | Industry resource estimator | Validation baseline |

---

## Open Research Questions

- What is the correct cost model for inter-module entanglement generation across different photonic link architectures?
- How does classical communication latency for error syndrome propagation scale with module count and topology?
- What are the precise quantitative relationships between specific material properties and device parameters?
- How do neutral atom reconfiguration costs scale with circuit size and module topology?
- What graph partitioning objectives best predict actual resource costs on real modular hardware?
- How should uncertainty in materials-to-device mappings propagate through the full pipeline?
- Are there circuit classes for which one platform is categorically superior regardless of hardware parameter values?
- What is the correct magic state factory count as a function of T gate rate and circuit depth?
- How does SWAP routing overhead scale with module size and circuit interaction graph density?

---

*End of Specification Document v0.4*
*Original document produced April 2026. Streamlined and updated April 25, 2026.*
*This document is intended to evolve with the research.*
