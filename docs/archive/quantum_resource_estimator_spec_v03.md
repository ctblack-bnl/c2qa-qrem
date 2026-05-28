# Modular Quantum Computing Resource Estimation Framework
## Pipeline Specification & Design Document

**Version:** 0.3 — Implementation Update: Phases 1 and 2 Complete
**Date:** April 22, 2026
**Status:** In Development — Phases 1 and 2 Complete, Phase 3 Pending
**Intended audience:** Computer scientists, quantum architects, device scientists, materials scientists

---

## Foundational Conversation Summary & Key Decisions

> **Note for project continuity:** This section captures the reasoning, decisions, and context from the initial design conversation that produced this specification. It is intended to give future collaborators — human or AI — full context on *why* things were designed the way they were, not just *what* was decided.

---

### Context

This specification emerged from an extended design conversation between the center director and Claude (Anthropic). The director had working knowledge of the center's research goals and DOE reporting obligations but was approaching the QREM tool design from first principles, without deep prior familiarity with quantum circuit concepts or software architecture terminology. The conversation therefore covered both conceptual foundations and design decisions simultaneously.

Implementation began in April 2026 in a subsequent working session between the same parties. Phases 1 and 2 of the development sequence are now complete with working, validated code. This document has been updated to reflect implementation decisions made during that session.

---

### Key Conceptual Decisions

**Decision: Take OpenQASM as the input boundary**

The tool deliberately does not handle the algorithm-to-circuit compilation step. That step is handled by existing tools (Qiskit, Cirq, etc.). By accepting OpenQASM as input, the tool is compatible with any compiler that produces it, which is effectively all of them. This keeps the tool focused on the resource estimation problem and avoids reimplementing compiler functionality.

*Rationale discussed:* The distinction between algorithm and circuit was worked through carefully. An algorithm is the high-level mathematical recipe; a circuit is the specific implementation of that recipe in terms of gates on qubits. The compiler sits between them. QREM starts after the compiler has done its work.

**Decision: Strict separation of logical and physical worlds**

Stages 1 and 2 operate entirely on the ideal, noiseless logical circuit. Error correction and hardware imperfections are introduced only in Stage 3. This separation is not just conceptually clean — it enables the tool to separately attribute resource costs to algorithmic complexity vs hardware overhead, which is scientifically valuable.

*Rationale discussed:* The director articulated this insight directly: "the first steps our tool will do is to basically analyze the circuit as if the components were ideal and an architecture and resources to make the circuit go with ideal, and then starting at step three to start considering that the components aren't ideal." This framing was confirmed as exactly correct and became a core design principle.

**Decision: Separate error correction overhead for local vs inter-module gates**

This was identified as one of the most novel aspects of the tool. Inter-module gates require entanglement generation across a link, which is noisier and slower than local operations, and error syndrome propagation across boundaries introduces latency. Therefore inter-module gates need a higher code distance than local gates. Existing tools do not handle this distinction.

*Rationale discussed:* The director noticed that error correction was missing from the initial pipeline sketch and asked where it would enter. Working through this together led to the insight that it must be hardware-dependent and must distinguish local from inter-module operations — a non-obvious but important design point.

**Decision: Inter-module communication cost model as a separately pluggable component**

The inter-module cost model is pluggable independently from the error correction model. This is because quantum networking theory — which governs entanglement generation rates, purification overhead, and repeater requirements — is a distinct expert domain from quantum error correction theory. Separating them allows contributions from quantum networking specialists without requiring them to touch the error correction code, and vice versa.

**Decision: Hardware profiles as data structures, not code**

Hardware platform profiles (superconducting, neutral atom) are structured parameter sets — data — not code. Adding a new platform requires only defining a new profile, not writing new pipeline logic. Platform-specific behavior is handled within cost model plugins.

*Implementation note:* The superconducting baseline profile has been implemented as `src/qrem/hardware_profiles/superconducting.yaml`. See Section 8 for the full parameter structure.

**Decision: Materials-to-Device Mapping Layer as a novel aspirational component**

The director raised the insight that materials scientists speak a different language from device engineers — they think in terms of dielectric loss tangent and junction transparency, not gate fidelity and coherence time. Adding a mapping layer between these languages was identified as potentially the most novel contribution of the entire tool.

*Rationale discussed:* This was explicitly acknowledged as sitting at an open research frontier — many of the mappings are not fully known. The design response was a three-tier approach: empirical lookup tables for known mappings, parameterized models with uncertainty for approximate mappings, and explicit open research hooks for unknown mappings. The honest representation of uncertainty was emphasized as scientifically important.

**Decision: Magic state factories must be accounted for explicitly**

During implementation it became clear that T gate overhead — specifically the physical qubit cost of magic state distillation factories — is a significant and non-negligible resource cost that must be tracked separately from the computation qubit count. This was not in the original spec and has been added to the implementation and documented here.

*Rationale:* In fault-tolerant quantum computing, T gates cannot be implemented directly — they require magic states produced by dedicated factory circuits consuming hundreds to thousands of physical qubits each. A circuit with many T gates may require more factory qubits than computation qubits. Ignoring this would produce systematically optimistic resource estimates.

---

### Key Design Principles Established

**Pluggability above all.** Every major component has a defined interface and can be replaced independently. This was explicitly discussed as the property that makes the tool credible to experts — they can see where their expertise slots in and contribute without needing to understand the whole system.

**Framework over implementation.** The tool's primary contribution at this stage is the architecture — the abstraction layers, the interface contracts, the pipeline structure. Simplified initial implementations are acceptable and expected. The structure must be right; the implementations can be improved iteratively.

**Honest uncertainty representation.** Particularly in the materials layer, the tool must represent what is known, approximately known, and unknown. This is both scientifically honest and itself a research contribution — the catalog of unknowns is valuable. Simplifying assumptions are always documented explicitly in the tool's output.

**Serve multiple audiences with differentiated outputs.** Computer scientists, device engineers, and materials scientists need different things from the tool. The reporting layer must produce outputs appropriate to each audience, including the novel "device target specification" output that works backwards from a resource budget to required device parameters.

---

### Alignment with DOE QREM Goals

Three QREM-related goals were identified in the center's monthly DOE dashboard:

| Goal | Description | Relationship to This Spec |
|---|---|---|
| **1.2.1** | Establish QREM as a Center-wide framework; define architecture assumptions and fault-tolerant abstract machine model; establish interfaces for device, noise, module, and algorithm inputs | This specification document is the primary conceptual deliverable for 1.2.1. Phases 1 and 2 of implementation are complete. |
| **1.2.2** | Define quantitative baseline for modular atomic quantum processors; measure inter-module entanglement rate and fidelity | The experimental outputs of 1.2.2 are the primary inputs to the neutral atom hardware profile and the inter-module communication cost model in Stage 3. |
| **1.2.3** | Define quantitative baseline for superconducting modular systems; characterize coherence-gate-speed regimes, transduction efficiency, connectivity tradeoffs | The experimental outputs of 1.2.3 are the primary inputs to the superconducting hardware profile in Stage 3. The baseline superconducting profile has been implemented with current state-of-the-art parameters. |

---

### What Was Not Yet Decided (Original) / Status Update

| Item | Original Status | Current Status |
|---|---|---|
| Hardware profile parameter schemas | Deferred | Superconducting profile implemented. Neutral atom pending. |
| Graph partitioning algorithm | Greedy heuristic planned | Greedy heuristic implemented. Sophisticated replacement deferred. |
| Surface code implementation details | Simplified threshold model planned | Implemented with analytical approximation + correct 2d²-1 formula. |
| Magic state factory accounting | Not discussed | Identified as necessary during implementation. T gate counting placeholder in place. |
| SWAP routing overhead | Not discussed | Identified during implementation. Deferred with explicit documentation. |
| UI/visualization design | Not discussed | Not yet discussed. |
| Data storage for hardware profiles | Not discussed | YAML files in src/qrem/hardware_profiles/. |

---

*Original design conversation summary generated April 2026. Implementation update added April 22, 2026.*

---

## Implementation Status (Added v0.3)

This section documents what has been built as of April 22, 2026.

### Phases Complete

**Phase 1 — Core Pipeline (Complete)**
Stage 1 (parser) and Stage 2 (analyzer) are implemented and validated against two test circuits.

**Phase 2 — Single Platform Estimation (Complete)**
Stage 3 (model/estimator) is implemented for the superconducting platform with simplified surface code error correction. End-to-end resource estimates are produced and validated.

### Code Structure

```
2026-04 c2qa_qrem/
  src/qrem/
    parser.py              — Stage 1: OpenQASM → CircuitIR
    circuit_ir.py          — Internal representation data structures
    analyzer.py            — Stage 2: CircuitIR → AnalysisResult
    estimator.py           — Stages 3-4: AnalysisResult → EstimationResult
    hardware_profiles/
      superconducting.yaml — Superconducting baseline hardware profile
      neutral_atom.yaml    — Placeholder (not yet implemented)
  data/
    circuits/              — Test circuit files (.qasm)
  scripts/                 — Pipeline entry points (in development)
  materials/               — Materials characterization subpackage
  ingester/                — Publications ingester subpackage
```

### Validated Test Circuits

Two test circuits have been created and validated:

| Circuit | Description | Qubits | Two-qubit gates |
|---|---|---|---|
| `test_circuit.qasm` | 3-qubit repetition code syndrome measurement | 5 | 6 |
| `test_circuit_02.qasm` | VQE ansatz layer | 4 | 9 |

### Validated Estimation Results

The following results have been manually verified for correctness:

| Circuit | Fidelity | Code distance | Physical qubits/logical | Total physical qubits | Modules |
|---|---|---|---|---|---|
| test_circuit_01 | 99.5% | 39 | 3,041 | 15,205 | 16 |
| test_circuit_01 | 99.9% | 11 | 241 | 1,205 | 2 |
| test_circuit_02 | 99.5% | 39 | 3,041 | 12,164 | 13 |
| test_circuit_02 | 99.9% | 11 | 241 | 964 | 1 |

These results demonstrate the dramatic sensitivity of module count to gate fidelity — a 0.4% improvement in two-qubit gate fidelity (99.5% → 99.9%) reduces module count from 16 to 2 for the syndrome measurement circuit. This is the core scientific insight the tool is designed to surface.

### Running the Pipeline

```bash
cd src/qrem
python3 parser.py ../../data/circuits/test_circuit.qasm
python3 analyzer.py ../../data/circuits/test_circuit.qasm
python3 estimator.py ../../data/circuits/test_circuit.qasm hardware_profiles/superconducting.yaml
```

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Motivation and Research Context](#2-motivation-and-research-context)
3. [Conceptual Framework](#3-conceptual-framework)
4. [Pipeline Architecture Overview](#4-pipeline-architecture-overview)
5. [Stage 1 — Parse](#5-stage-1--parse)
6. [Stage 2 — Analyze](#6-stage-2--analyze)
7. [Error Correction Layer](#7-error-correction-layer)
8. [Stage 3 — Model](#8-stage-3--model)
9. [Stage 4 — Estimate](#9-stage-4--estimate)
10. [Stage 5 — Compare & Report](#10-stage-5--compare--report)
11. [Materials-to-Device Mapping Layer](#11-materials-to-device-mapping-layer)
12. [Sensitivity Analysis and Pareto Frontier](#12-sensitivity-analysis-and-pareto-frontier)
13. [Software Architecture Principles](#13-software-architecture-principles)
14. [C2QA Prior Art and Ecosystem Integration](#14-c2qa-prior-art-and-ecosystem-integration)
15. [Open Research Questions](#15-open-research-questions)
16. [Suggested Development Sequence](#16-suggested-development-sequence)

---

## 1. Executive Summary

This document specifies the architecture and pipeline design for a cross-platform quantum resource estimation tool targeting modular quantum computing architectures. The tool is intended to serve a multi-disciplinary research center encompassing computer scientists, quantum architects, device engineers, and materials scientists.

The central motivation is to provide a quantitative bridge across the full knowledge chain — from physical material properties, through device characteristics, through circuit-level analysis, to system-level resource requirements. No existing tool addresses this complete chain.

The tool takes as input a quantum circuit expressed in OpenQASM format and one or more hardware profile specifications. It produces comparative resource estimates across hardware platforms — initially superconducting qubit systems and neutral atom systems — with particular attention to the costs unique to modular architectures, especially inter-module communication.

As of April 2026, Phases 1 and 2 of development are complete. The tool successfully parses OpenQASM circuits, builds qubit interaction graphs, computes surface code error correction overhead, estimates physical qubit counts and module requirements, and produces resource estimation reports with explicit documentation of all simplifying assumptions.

A key design principle is that the tool is built for extensibility. Every major component — the circuit analyzer, the error correction model, the inter-module cost model, and the materials-to-device mapping layer — is designed as a pluggable, replaceable module with a well-defined interface. Expert contributors can replace simplified initial implementations with rigorous models without disturbing the rest of the pipeline.

---

## 2. Motivation and Research Context

### 2.1 The Modular Architecture Challenge

Modular quantum computing architectures connect multiple smaller quantum processing units (modules) via inter-module communication links, typically photonic. This approach offers a practical path to scaling qubit counts beyond what a single device can support. However, it introduces resource costs that single-device estimation tools do not capture:

- Inter-module communication events consume additional physical qubits for entanglement links
- Communication links have lower fidelity than local gate operations, requiring additional error correction overhead
- The topology of module connectivity becomes a first-class design parameter
- Error syndrome propagation across module boundaries introduces latency that can increase effective error rates

### 2.2 The Cross-Platform Comparison Gap

Superconducting and neutral atom platforms have complementary strengths that make different algorithms more naturally suited to one or the other. Currently, no tool allows a researcher to evaluate the same circuit against both platforms in a unified framework. This tool fills that gap.

### 2.3 The Materials Science Connection

A distinctive and novel aspect of this tool is the aspiration to connect system-level resource requirements all the way back to physical material properties. Device scientists and materials scientists currently lack a quantitative way to understand which material improvements translate into system-level gains such as reduced module count. This tool provides that connection — initially with simplified models and explicit uncertainty bounds, with hooks for more rigorous models as the research matures.

The validated results from Phase 2 already demonstrate this connection concretely: a 0.4% improvement in two-qubit gate fidelity reduces module count from 16 to 2 for a representative circuit. This quantitative relationship — from material property to system-level resource — is the core scientific contribution of the tool.

---

## 3. Conceptual Framework

### 3.1 The Two Worlds

The pipeline operates across two distinct conceptual worlds. Understanding this distinction is fundamental to the tool's design.

| | Logical World | Physical World |
|---|---|---|
| **Components** | Ideal, perfect | Real, noisy |
| **Qubits** | Logical qubits | Physical qubits (many per logical) |
| **Gates** | Ideal operations | Gates with error rates |
| **Overhead** | None | Error correction, inter-module costs, magic state factories |
| **Pipeline stages** | Stages 1 & 2 | Stages 3, 4 & 5 |

The transition between these worlds is governed by error correction theory and hardware-specific parameters. Keeping them clearly separated allows the tool to attribute resource costs to two distinct sources: algorithmic complexity (inherent to the circuit) and hardware cost (introduced by physical imperfections).

### 3.2 Abstract Machine Models

In formal computer science terms, each hardware profile in this tool constitutes an **Abstract Machine Model** — a simplified, idealized representation of a computing system that captures enough detail to reason about computational cost without modeling every physical element. The tool defines a new class of abstract machine model specifically for modular quantum architectures.

### 3.3 Co-Design Principle

The tool is designed to support **co-design** — the simultaneous optimization of algorithms, architectures, and device characteristics. Rather than the traditional sequential workflow (devices first, then architecture, then algorithms), the tool enables circular and iterative reasoning: algorithm requirements inform architecture choices, architecture choices inform device priorities, and device improvements feed back into what algorithms become feasible.

---

## 4. Pipeline Architecture Overview

The pipeline consists of five stages plus a cross-cutting error correction layer. Each stage is designed as an independently replaceable module with a well-defined input/output contract.

```
OpenQASM Circuit  +  Hardware Profile(s)  +  Target Error Rate
         |
    [Stage 1]  PARSE
         |          → CircuitIR (gate list, qubit inventory, gate counts)
    [Stage 2]  ANALYZE  (Logical World)
         |          → AnalysisResult (interaction graph, hub qubits, locality score)
    [Stage 3]  MODEL    (Physical World — per hardware platform)
         |              includes: Error Correction Layer
         |                        Magic State Factory Estimation
         |                        Inter-Module Cost Model
         |          → EstimationResult (physical qubits, modules, feasibility)
    [Stage 4]  ESTIMATE
         |          → Resource summary with explicit assumptions
    [Stage 5]  COMPARE & REPORT
         |
  Resource Report  +  Sensitivity Analysis  +  Device Target Specification
```

Each stage boundary is an explicit interface contract. The tool accepts OpenQASM as its input boundary, meaning it is agnostic to how the circuit was produced.

---

## 5. Stage 1 — Parse

**Status: Complete**

**OpenQASM → CircuitIR**

### Purpose

Read the OpenQASM circuit file and transform it into a structured internal data representation (CircuitIR) that the pipeline can analyze.

### Implementation

Implemented in `src/qrem/parser.py` using Qiskit's `QuantumCircuit.from_qasm_file()`. The CircuitIR data structure is defined in `src/qrem/circuit_ir.py`.

### Interface

| Inputs | Outputs |
|---|---|
| OpenQASM circuit file (.qasm) | CircuitIR containing: |
| | — ordered gate list with gate type classification |
| | — qubit register inventory |
| | — gate count summary (single-qubit, two-qubit, multi-qubit, measurements) |

### Gate Classification

Gates are classified into four types:

| Type | Examples | Resource significance |
|---|---|---|
| `single_qubit` | H, X, Y, Z, S, T, Rz | Cheap on all platforms; no inter-qubit interaction |
| `two_qubit` | CNOT, CZ, SWAP | Expensive; create edges in interaction graph |
| `multi_qubit` | CCX, multi-controlled | Platform-dependent cost |
| `measurement` | measure | Contributes to readout overhead |

**Note on T gates:** T gates are classified as single-qubit gates at the circuit level. However, in fault-tolerant computing they require magic state distillation and carry a special physical resource overhead. T gate counting is tracked separately and fed into the magic state factory estimation in Stage 3. See Section 7.3.

---

## 6. Stage 2 — Analyze

**Status: Complete**

**Circuit Structure Analysis (Logical World)**

### Purpose

Extract meaningful structural information from the parsed circuit. This stage operates entirely in the logical world — it characterizes the circuit as if all components were ideal.

### Implementation

Implemented in `src/qrem/analyzer.py` using the NetworkX graph library.

### Interface

| Inputs | Outputs |
|---|---|
| CircuitIR (from Stage 1) | AnalysisResult containing: |
| | — weighted qubit interaction graph |
| | — interaction pair list (sorted by frequency) |
| | — per-qubit interaction counts |
| | — hub qubits (above-average interaction count) |
| | — locality score (0.0 = maximally spread, 1.0 = highly concentrated) |

### Sub-stage 2a — Gate Classification Summary

Count gates by type from the CircuitIR. Single-qubit gates are free from a connectivity standpoint. Only two-qubit and multi-qubit gates create edges in the interaction graph.

### Sub-stage 2b — Qubit Interaction Graph Construction

For every two-qubit gate, draw a weighted edge between the two participating qubits. Edge weight = number of interactions between that pair across the full circuit.

- **Nodes:** logical qubits
- **Edges:** pairs of qubits that interact via two-qubit gates
- **Edge weights:** interaction frequency

This weighted interaction graph is the primary artifact produced by the pipeline. Edges that cross module boundaries become inter-module communication events.

### Sub-stage 2c — Graph Structure Analysis

- **Locality score:** ratio of repeated interactions to unique pairs. High locality (close to 1.0) means the same pairs interact repeatedly — favorable for modular architectures because qubits can be co-located on the same module.
- **Hub qubits:** qubits with above-average total interaction counts. Hub qubits are the most expensive to place across module boundaries and are prioritized in module assignment.

### Sub-stage 2d — Circuit Depth and Critical Path

Not yet implemented. Planned for Phase 3.

### Sub-stage 2e — Module Partitioning

A greedy heuristic is implemented: hub qubits are processed first, then remaining qubits are packed into modules in interaction-count order. This is explicitly a placeholder — see Section 13 on pluggability.

---

## 7. Error Correction Layer

**Status: Partially implemented (analytical approximation)**

The Error Correction Layer sits at the boundary between the logical and physical worlds. It is invoked within Stage 3, separately for each hardware platform.

### 7.1 Role

Given the noise characteristics of a specific hardware platform, determine how many physical qubits and physical gates are required to implement each logical qubit and logical gate with acceptable reliability.

### 7.2 Surface Code Model — Implementation Details

The initial implementation uses an analytical approximation of the surface code threshold theorem:

```
logical_error_rate ≈ (physical_error_rate / threshold) ^ ((d+1)/2)
```

The minimum odd integer `d` satisfying the target logical error rate is selected as the code distance.

**Physical qubit count per logical qubit:**

The correct formula for a distance-`d` surface code is:

```
physical_qubits_per_logical = 2d² - 1
```

This accounts for `d²` data qubits plus `d²-1` ancilla qubits required for syndrome measurements. Note that an earlier formulation using `d²` was incorrect and has been fixed in the implementation.

**Threshold behavior:** Because `d` must be an odd integer, resource requirements are not smooth functions of hardware parameters. Small improvements in physical gate fidelity can cause discrete jumps in code distance, producing large step-changes in physical qubit requirements. The tool explicitly reports these thresholds.

**Example:** At 99.5% two-qubit gate fidelity (0.5% error rate, 50% of the 1% threshold), code distance 39 is required, giving 3,041 physical qubits per logical qubit. At 99.9% fidelity (0.1% error rate, 10% of threshold), code distance 11 suffices, giving 241 physical qubits per logical qubit — a 12.6× reduction from a 0.4% fidelity improvement.

### 7.3 Magic State Factories

T gates cannot be implemented directly in a fault-tolerant surface code — they require **magic states** produced by dedicated distillation factory circuits. This is a significant and non-negligible physical resource cost.

**Factory qubit overhead:**
- Each magic state factory consumes approximately 1,000 physical qubits (standard distillation protocol)
- The number of factories needed depends on the T gate rate vs factory production rate
- For small circuits: 1 factory is assumed if T gates are present, 0 if not
- For larger circuits: factory count should scale with T gate density (future refinement)

**T gate counting:** T gates are tracked in the CircuitIR and fed into factory estimation in Stage 3. The current implementation uses 0 as a placeholder for test circuits (which contain no T gates). T gate counting will be wired through from the parser in a future phase.

**Total physical qubit count:**
```
total_physical_qubits = computation_qubits + factory_qubits
                      = (num_logical_qubits × physical_qubits_per_logical)
                      + (num_factories × qubits_per_factory)
```

### 7.4 Inter-Module Gate Overhead

Logical gates that cross module boundaries require a fundamentally different error correction treatment than local gates. The current implementation tracks inter-module operation counts but does not yet apply differential code distance — this is a planned enhancement. See Section 15 (Open Research Questions).

The tool currently flags when inter-module link error rates exceed the surface code threshold, warning that inter-module operations may not be correctable without additional overhead.

### 7.5 Simplifying Assumptions — Error Correction Layer

The following assumptions are explicitly documented and reported in every estimation output:

1. **Analytical approximation:** The surface code threshold formula is an approximation. Full Stim simulation would give more accurate logical error rates but is not yet integrated.
2. **Uniform code distance:** A single code distance is applied to all logical operations. In practice, inter-module gates may require higher code distance than local gates.
3. **Simplified factory model:** Magic state factory count is 0 or 1 based on T gate presence only. Production rate vs demand rate is not yet modeled.

---

## 8. Stage 3 — Model

**Status: Implemented for superconducting platform**

**Hardware-Specific Physical Modeling**

### Purpose

Apply hardware-specific models to translate the logical circuit analysis into physical resource requirements.

### Implementation

Implemented in `src/qrem/estimator.py`.

### Interface

| Inputs | Outputs |
|---|---|
| AnalysisResult (from Stage 2) | EstimationResult containing: |
| Hardware profile (.yaml) | — physical error rate |
| | — code distance |
| | — physical qubits per logical qubit (2d²-1) |
| | — computation qubit count |
| | — T gate count and factory qubit count |
| | — total physical qubit count |
| | — module count |
| | — inter-module operation count and fraction |
| | — feasibility assessment |
| | — explicit assumption list |

### Superconducting Hardware Profile

The baseline superconducting profile is implemented in `src/qrem/hardware_profiles/superconducting.yaml`. Key parameters and their current values:

**Coherence:**
| Parameter | Value | Notes |
|---|---|---|
| T1 | 200 µs | Current best labs: 100-500 µs |
| T2 | 300 µs | Typically T2 ≤ 2×T1 |

**Gates:**
| Parameter | Value | Notes |
|---|---|---|
| Single-qubit fidelity | 99.9% | 1 error per 1,000 gates |
| Single-qubit gate time | 20 ns | Typical range: 10-50 ns |
| Two-qubit fidelity | 99.9% | Baseline; 99.5% also tested |
| Two-qubit gate time | 200 ns | Typical range: 100-500 ns |
| Readout fidelity | 99.5% | Critical for syndrome measurement |
| Readout time | 500 ns | Significant contributor to EC cycle time |

**Module architecture:**
| Parameter | Value | Notes |
|---|---|---|
| Physical qubits per module | 1,000 | Representative near-term device size |
| Connectivity | nearest_neighbor | Grid topology typical for superconducting chips |

**Inter-module links:**
| Parameter | Value | Notes |
|---|---|---|
| Link type | microwave_photonic | Typical for SC systems |
| Link fidelity | 85% | Conservative baseline — current demonstrated performance |
| Entanglement rate | 1,000 Hz | Current demonstrated range: 100-10,000 Hz |
| Link latency | 10 µs | Signal travel + processing overhead |
| Transduction efficiency | 50% | Optimistic near-term for MW-to-optical conversion |

**Inter-module link fidelity tiers (for sensitivity analysis):**
- 85% — conservative baseline (current demonstrated)
- 92% — near-term target (optimistic, 2-3 year horizon)
- 99% — aspirational (required for practical advantage)

**Error correction:**
| Parameter | Value | Notes |
|---|---|---|
| Code | surface_code | Leading candidate for SC qubits |
| Target logical error rate | 1×10⁻⁶ | Standard fault-tolerant target |
| Threshold | 1% (0.01) | Surface code theoretical threshold |

### Module Assignment

Module count is computed as:

```
num_modules = ceil(total_physical_qubits / physical_qubits_per_module)
```

This is the authoritative calculation. The greedy qubit assignment algorithm (hub-first, fill-then-advance) is used separately to determine which qubits share modules for inter-module operation counting.

### Simplifying Assumptions — Stage 3

The following assumptions are explicitly reported in every estimation output:

1. **Perfect intra-module connectivity:** No SWAP routing overhead is modeled within modules. In reality, superconducting qubits sit on a grid and can only interact with neighbors — routing interactions between non-adjacent qubits requires SWAP gates, adding time and errors. This assumption means our physical qubit estimates are a lower bound — actual counts will be somewhat higher due to routing overhead. Neutral atom platforms are less affected by this assumption since atoms can be physically rearranged.

2. **Analytical surface code approximation:** Not full Stim simulation.

3. **Greedy module assignment:** Not optimal graph partitioning.

4. **T gate count placeholder:** Currently 0 for test circuits. Will be wired through from parser.

5. **Inter-module cost:** Modeled as operation count only. Latency and purification overhead not yet included.

---

## 9. Stage 4 — Estimate

**Status: Implemented (integrated into estimator.py)**

**Resource Calculation**

### Purpose

Aggregate physical modeling outputs into concrete, comparable resource estimates.

### Key Metrics Produced

| Metric | Description |
|---|---|
| Physical qubit count | Computation qubits + factory qubits |
| Module count | ceil(total physical qubits / qubits per module) |
| Inter-module operation count | Two-qubit gates crossing module boundaries |
| Inter-module fraction | Fraction of two-qubit gates that are inter-module |
| Feasibility | Whether physical/inter-module error rates are in correctable regime |
| Assumption list | Explicit documentation of all simplifications made |

---

## 10. Stage 5 — Compare & Report

**Status: Not yet implemented**

### Purpose

Present resource estimates side by side across hardware platforms, identify why one platform performs better for a particular circuit, and produce outputs tailored to different audiences.

### Planned Outputs by Audience

**For computer scientists and quantum architects:**
- Side-by-side resource comparison table across platforms
- Attribution of resource cost to algorithmic structure vs hardware overhead
- Identification of which circuit properties drive platform preference

**For device engineers:**
- Sensitivity analysis — how does each resource metric respond to variation in each device parameter?
- Threshold identification — at what parameter values do discrete improvements become achievable?
- Device target specification — given a resource budget, what are the minimum device parameters required?

**For materials scientists:**
- Materials parameter sensitivity routed through the Materials-to-Device Mapping Layer
- Research priority guidance — which material improvements have the largest system-level impact?
- Uncertainty-aware estimates with explicit confidence levels

---

## 11. Materials-to-Device Mapping Layer

**Status: Not yet implemented — design phase**

### 11.1 Motivation

Device engineers think in terms of gate fidelity, coherence time, and error rates. Materials scientists think in terms of dielectric loss tangent, junction transparency, surface oxide quality, and resistivity. This layer bridges those languages quantitatively, enabling a materials scientist to ask: if I improve this material property by this amount, what happens to the number of modules needed to run this algorithm?

### 11.2 Connection to Materials Database

The C2QA materials characterization database and publications ingester (separate components of this project) are being developed in parallel to populate this layer. The ingester extracts structured materials data from publications, and the AI review process identifies author-stated connections between material properties and device performance. These connections, once validated, become entries in the mapping layer.

The near-term strategy for populating the mapping layer:
1. Mine the publications ingester catchall corpus for explicit author-stated materials-to-device connections
2. Rank connections by how many papers support each one
3. Implement the best-supported connections as the well-known tier of the mapping layer
4. Use the materials database structured measurements (Tc, RRR, surface oxide thickness, etc.) to parameterize the mapping functions

### 11.3 Layer Structure

The layer is implemented as a Materials Model Registry — a collection of mapping functions with explicit metadata:

| Field | Description |
|---|---|
| `input` | Material parameter (what the scientist measures) |
| `output` | Device parameter (what feeds into the hardware profile) |
| `model` | The mapping function |
| `source` | Literature reference or experimental data |
| `uncertainty` | Confidence bounds |
| `status` | `well_known` / `approximate` / `open_research` |

### 11.4 Known Mappings (Superconducting)

| Material Property | Device Parameter | Status |
|---|---|---|
| Dielectric loss tangent | T1 coherence time | well_known |
| Josephson junction transparency | Two-qubit gate fidelity | approximate |
| Surface oxide quality / TLS density | T2 dephasing time | approximate |
| RRR (residual resistivity ratio) | Quasiparticle loss → T1 | approximate |
| Substrate purity and defect density | Overall coherence | open_research |

### 11.5 Handling Unknown Mappings

1. **Empirical lookup tables** for well-characterized relationships
2. **Parameterized models with uncertainty ranges** for approximately known relationships
3. **Open research hooks** — explicitly marked unknown mappings where users can plug in their own models

---

## 12. Sensitivity Analysis and Pareto Frontier

**Status: Not yet implemented**

### 12.1 Sensitivity Analysis

For each output metric (module count, physical qubit count, runtime), compute how that metric responds to variation in each input parameter. Parameters with high sensitivity are those worth optimizing.

### 12.2 Threshold Detection

The tool explicitly identifies threshold values — parameter values at which a discrete improvement in resource requirements becomes achievable. Example from validated results:

```
Two-qubit fidelity 99.5%  →  code distance 39  →  16 modules
Two-qubit fidelity 99.9%  →  code distance 11  →   2 modules
```

The 99.9% threshold is where a discrete jump occurs. This is the most actionable output for device scientists — it defines a precise target that unlocks the next level of performance.

### 12.3 Pareto Frontier

For multi-parameter optimization, the tool will map the Pareto frontier — the set of parameter combinations where improving one metric requires accepting a worse outcome on another.

---

## 13. Software Architecture Principles

### 13.1 Modularity and Loose Coupling

Every major component is independently replaceable. Pipeline stages communicate only through well-defined data contracts. No stage has knowledge of another stage's internal implementation.

### 13.2 Pluggable Components Summary

| Component | Location | Status | Expert Domain |
|---|---|---|---|
| Circuit parser | `src/qrem/parser.py` | Complete | Compiler / language design |
| Graph partitioning algorithm | `src/qrem/analyzer.py` | Greedy placeholder | Combinatorial optimization |
| Error correction model | `src/qrem/estimator.py` | Analytical placeholder | Quantum error correction |
| Magic state factory model | `src/qrem/estimator.py` | Simplified placeholder | Quantum error correction |
| Inter-module communication cost model | `src/qrem/estimator.py` | Simplified placeholder | Quantum networking |
| Hardware platform profiles | `src/qrem/hardware_profiles/` | SC baseline complete | Device physics |
| Materials-to-device mappings | `materials/mapping_layer/` | Not yet implemented | Materials science |

### 13.3 Implementation Language and Dependencies

Python 3.9+ (3.10+ recommended). Key dependencies:

```
qiskit          — OpenQASM parsing
networkx        — Graph construction and analysis
pyyaml          — Hardware profile loading
```

### 13.4 Known Deferred Items

The following items were explicitly identified during implementation as deliberate deferrals — not oversights:

**SWAP routing overhead:** Within a module, superconducting qubits sit on a grid and can only interact with neighbors. Routing interactions between non-adjacent qubits requires SWAP gates. This overhead is not yet modeled. The current assumption of perfect intra-module connectivity means our physical qubit estimates are lower bounds. Neutral atom platforms are less affected by this because atoms can be physically rearranged (reconfiguration), achieving something closer to the all-to-all connectivity we assume. This distinction will be an important differentiator when the neutral atom hardware profile is implemented.

**Circuit depth and critical path:** Sub-stage 2d is not yet implemented. This is needed for runtime estimation in Stage 4.

**T gate counting:** T gates are classified as single-qubit gates in the parser. A separate T gate counter needs to be wired through from the parser to the estimator for magic state factory calculations.

---

## 14. C2QA Prior Art and Ecosystem Integration

### 14.1 C2QA Prior Art — Plug-in Mapping

**Arquin (Multi-node Superconducting Qubit System)**
- **Plugs into:** Inter-Module Communication Cost Model
- **Nature of fit:** Clean, direct replacement of the simplified inter-module placeholder
- **Integration effort:** Moderate — wrap Arquin outputs to conform to interface contract

**HetArch (Heterogeneous Architecture + Standard Cell QEC)**
- **Plugs into:** Error Correction Layer
- **Nature of fit:** Direct replacement of analytical surface code approximation
- **Integration effort:** Moderate — express HetArch overhead factors in terms of interface contract

**Bosonic ISA (Hybrid Oscillator-Qubit Architecture)**
- **Plugs into:** Requires planned pipeline extension — no current slot
- **Status:** Deliberate future opening. Requires parser, analyzer, and model extensions to handle qumodes alongside qubits.

### 14.2 Ecosystem Tool Integration

| Tool | Role | Pipeline Location | Integration Type |
|---|---|---|---|
| **Qualtran** (Google) | Algorithm-level resource estimation | Upstream of Stage 1 | Alternative input format adapter |
| **Qiskit** (IBM) | Circuit compilation, OpenQASM generation | Upstream of Stage 1 | Currently used for parsing |
| **Stim** | High-performance QEC simulation | Error Correction Layer | Simulation backend to replace analytical formula |
| **QREChem** | Quantum resource estimation for chemistry | Upstream of Stage 1 | Domain-specific circuit source |
| **Azure QRE** (Microsoft) | Industry resource estimator | Reference / validation | Validation baseline for benchmark circuits |

---

## 15. Open Research Questions

- What is the correct cost model for inter-module entanglement generation across different photonic link architectures?
- How does classical communication latency for error syndrome propagation scale with module count and topology?
- What are the precise relationships between specific material properties and device parameters for superconducting qubits at scale?
- How do neutral atom reconfiguration costs scale with circuit size and module topology?
- What graph partitioning objectives best predict actual resource costs on real modular hardware?
- How should uncertainty in materials-to-device mappings be propagated through the full pipeline to produce uncertainty bounds on resource estimates?
- Are there circuit classes for which one platform is categorically superior regardless of hardware parameter values?
- What is the correct magic state factory count as a function of T gate rate and circuit depth?
- How does SWAP routing overhead scale with module size and circuit interaction graph density?
- At what physical qubit count does the greedy module assignment produce meaningfully suboptimal results compared to rigorous graph partitioning?

---

## 16. Suggested Development Sequence

| Phase | Focus | Status | Deliverable |
|---|---|---|---|
| **Phase 1** | Core pipeline | ✅ Complete | Stage 1 (parser) + Stage 2 (analyzer). Validated on two test circuits. |
| **Phase 2** | Single platform estimation | ✅ Complete | Stage 3 + 4 for superconducting. End-to-end resource estimates validated. |
| **Phase 3** | Cross-platform comparison | Pending | Neutral atom hardware profile and platform-specific cost models. Side-by-side comparison output. |
| **Phase 4** | Sensitivity analysis | Pending | Sensitivity analysis and threshold detection. Device target specifications. |
| **Phase 5** | Materials layer | In parallel development | Materials-to-Device Mapping Layer. Initial mappings from publications ingester catchall corpus. |
| **Phase 6** | Expert component replacement | Pending | Replace simplified implementations with rigorous models. Arquin and HetArch integration highest priority. |

**Note on Phase 5:** The Materials-to-Device Mapping Layer is being developed in parallel with the core pipeline rather than sequentially, because the publications ingester and materials characterization database are being built simultaneously. The ingester's catchall corpus — which captures author-stated connections between material properties and device performance — is the primary data source for populating the mapping layer.

---

*End of Specification Document v0.3*
*Original document produced April 2026. Updated April 22, 2026 to reflect Phase 1 and 2 implementation.*
*This document is intended to evolve with the research.*
