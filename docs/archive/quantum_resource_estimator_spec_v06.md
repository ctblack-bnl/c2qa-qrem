# Quantum Resource Estimation — Baby QREM
## Pipeline Specification & Design Document

**Version:** 0.6 — Single-module rescoping, circuit depth, depth-derived LER target
**Date:** April 29, 2026
**Status:** Stages 1–3 complete; UI operational; materials pipeline connected
**Intended audience:** Device scientists, materials scientists, quantum architects

---

## Strategic Scope — April 2026

Baby QREM is a **materials → single-module resource estimator**. It answers the question:

*"I have a superconducting qubit with this gate fidelity. If I run this quantum circuit, how many physical qubits do I need, and how does that change as my materials improve?"*

The modular architecture question — how many modules, how do inter-module links work, what is the purification overhead — is a separate Center-wide research problem involving computer scientists, algorithms researchers, and error correction theorists. Materials and devices feed into it, but it is not a materials challenge. Baby QREM deliberately stays out of that space.

This is a sharpening, not a limitation. A clean single-module estimator that takes real materials inputs and produces honest physical qubit counts is genuinely useful to materials scientists right now.

---

## Key Design Decisions

**OpenQASM as input boundary.** The tool does not handle algorithm-to-circuit compilation — that is handled by existing tools (Qiskit, Cirq, etc.). Accepting OpenQASM makes QREM compatible with any compiler that produces it.

**Strict separation of logical and physical worlds.** Stages 1–2 operate on the ideal, noiseless logical circuit. Error correction and hardware imperfections enter only in Stage 3.

**Circuit depth drives the error correction target.** The required logical error rate per gate is derived from circuit depth and a user-specified target circuit success rate — not hardcoded. A shallow circuit (depth 8) can tolerate a much higher per-gate error rate than a deep circuit (depth 10,000). This makes resource estimates honest and circuit-specific.

**Hardware profiles as data, not code.** Platform parameters live in YAML files, not code. Changing qubit profiles or error correction targets requires only editing or selecting a data file — no code changes.

**Corpus-derived qubit profiles.** Qubit profiles are generated directly from materials database records via the Hardware Profile Updater. Measured fields (T1, T2, gate fidelity) are labeled `[MEASURED]`; missing fields use baseline defaults labeled `[ASSUMED]`. Full provenance is preserved.

**Honest uncertainty representation.** All simplifying assumptions are explicitly documented in every tool output. The catalog of unknowns is itself a scientific contribution.

**Tier 2 preserved, not active.** Modular overhead functions (module assignment, inter-module operations, purification model, communication qubits) are preserved intact in `estimator_tier2_modular.py` and will be reconnected when the Center-wide modular architecture research matures. The `EstimationResult` dataclass retains all Tier 2 fields as `Optional`, defaulting to `None`.

---

## System Architecture

Baby QREM is one component in the C2QA materials-to-resource pipeline:

```
Scientific Papers
      ↓
[Ingester] → Materials Database (PUKs)
      |
      |── Measured device performance (T1, T2, gate fidelity)
      |   → Hardware Profile Updater → qubit profile YAML
      |                                        ↓
      |                               [Baby QREM Pipeline]
      |                                        ↑
      └── Material properties (Tc, RRR, loss tangent)
          → Materials Predictor → Mapping Layer (planned)
```

The scientific question Baby QREM currently answers:
*"Given this qubit's gate fidelity and this circuit, how many physical qubits are needed for the circuit to succeed with X% probability?"*

The broader question — how does this scale across modules? — is Tier 2, currently out of scope.

---

## Pipeline Architecture

```
OpenQASM Circuit  +  Qubit Profile YAML  +  QEC Profile YAML
         |
    [Stage 1]  PARSE
         |     → CircuitIR: gate list, qubit inventory, gate counts
         |
    [Stage 2]  ANALYZE  (Logical World)
         |     → AnalysisResult: circuit depth (critical path),
         |       interaction graph, hub qubits, locality score
         |
    [Stage 3]  ESTIMATE  (Physical World — Tier 1)
         |     → depth + success rate → per-gate LER target
         |     → LER target + gate fidelity → code distance d
         |     → d → physical qubits per logical qubit (2d² - 1)
         |     → total physical qubits (computation + factory)
         |     → EstimationResult + explicit assumptions
         |
    [Stage 4]  COMPARE & REPORT  (planned)
               → sensitivity analysis, coherence budget, device targets
```

---

## Implementation Status

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Parser + Analyzer (Stages 1–2) | ✅ Complete — circuit depth added April 2026 |
| **Phase 2** | Superconducting estimator (Stage 3) + UI | ✅ Complete — rescoped to single-module April 2026 |
| **Phase 3** | Coherence budget breakdown | Next — T1 loss attribution by mechanism |
| **Phase 4** | Sensitivity analysis | Planned — material property → code distance change |
| **Phase 5** | Materials-to-Device Mapping Layer | In parallel development via corpus mining |
| **Phase 6** | Expert component replacement (HetArch, Stim) | Pending |

---

## Code Structure

```
src/qrem/
  parser.py                     — Stage 1: OpenQASM → CircuitIR
  circuit_ir.py                 — Internal circuit representation
  analyzer.py                   — Stage 2: interaction graph, circuit depth
  estimator.py                  — Stage 3: single-module resource estimation (Tier 1)
  estimator_tier2_modular.py    — Tier 2 functions: preserved, not active
  profile_loader.py             — Profile loader: partial modular (qubits + QEC)
  hardware_profiles/
    qubits/
      transmon_baseline_2026.yaml     — Hand-tuned superconducting baseline
      {sample_display_name}.yaml      — Corpus-derived profiles (Hardware Profile Updater)
    interconnects/                    — Preserved for Tier 2 reconnection
      microwave_photonic_85pct.yaml
      microwave_photonic_92pct.yaml
      microwave_photonic_99pct.yaml
    modules/                          — Preserved for Tier 2 reconnection
      module_1000q_nearest_neighbor.yaml
    error_correction/
      surface_code_1e6.yaml           — threshold + target LER (target overridden by UI)
    superconducting.yaml              — Legacy monolithic profile (still supported)

scripts/
  serve.py                      — HTTP server: Baby QREM UI + static files
  qrem_ui.html                  — Baby QREM browser UI

data/circuits/
  test_circuit.qasm             — 3-qubit repetition code syndrome (5 qubits, depth 8)
  test_circuit_02.qasm          — VQE ansatz layer (4 qubits)
  qft_5qubit.qasm               — Quantum Fourier Transform (5 qubits, depth 11)
```

---

## Running the Pipeline

```bash
# UI (recommended)
cd 2026-04\ c2qa_qrem
python3 scripts/serve.py
# Open http://localhost:8000/scripts/qrem_ui.html

# CLI
cd src/qrem
python3 estimator.py ../../data/circuits/test_circuit.qasm hardware_profiles/superconducting.yaml
```

---

## Stage 1 — Parse

**Status: Complete** | `parser.py`

Reads OpenQASM via Qiskit and produces a `CircuitIR`: qubit inventory, ordered gate list, gate counts (single-qubit, two-qubit, measurements). T gates tracked separately for future magic state factory estimation.

---

## Stage 2 — Analyze

**Status: Complete** | `analyzer.py`

Operates entirely in the logical world. Two outputs:

**Circuit depth** — length of the critical path through the gate dependency graph. Computed via a single forward pass over the ordered gate list: for each gate, `depth = max(depth of its qubits) + 1`. Measurements are included (they are real time-consuming operations — consistent with Qiskit convention). Circuit depth is the primary driver of the per-gate LER target in Stage 3.

**Interaction graph** — weighted qubit interaction graph. Hub qubits (most connected), locality score (0 = interactions spread broadly, 1 = same pairs interact repeatedly). Used for circuit analysis display; will feed module partitioning when Tier 2 is reconnected.

---

## Stage 3 — Estimate

**Status: Complete for superconducting platform** | `estimator.py`

### Depth-Derived LER Target

The key innovation in v0.6. Rather than using a hardcoded target logical error rate, the per-gate LER target is derived from circuit depth and a user-specified circuit success rate:

```
target_LER_per_gate = 1 - success_rate ^ (1 / circuit_depth)
```

This means a shallow circuit (depth 8, success rate 99%) tolerates a per-gate LER of ~1.26e-3, while a deep circuit (depth 10,000) requires ~1e-6. Resource estimates are now honest and circuit-specific — a different circuit gives a genuinely different answer.

The QEC yaml provides the surface code `threshold` (~1% for surface code) and a fallback `target_logical_error_rate` for degenerate cases (depth ≤ 1). The depth-derived target overrides the yaml value in all normal cases.

### Tier 1 — Single-Module Baseline

```python
physical_error_rate = 1 - two_qubit_fidelity_pct / 100
target_LER = 1 - success_rate ^ (1 / circuit_depth)

# Minimum odd d such that:
# (physical_error_rate / threshold) ^ ((d+1)/2) <= target_LER
code_distance = smallest odd d satisfying above

physical_qubits_per_logical = 2 * d^2 - 1
computation_qubits = num_logical_qubits * physical_qubits_per_logical
total_physical_qubits = computation_qubits + factory_qubits
```

### Assumptions (reported in every output)

1. Perfect intra-module connectivity — no SWAP routing overhead. Physical qubit count is a lower bound on total system size.
2. Analytical surface code approximation — not full Stim simulation.
3. T gate count is placeholder (0) — magic state factory costs underestimated for T-gate-heavy circuits.
4. Modular overhead (Tier 2) not modeled — single-module estimator only. See `estimator_tier2_modular.py`.

### Tier 2 — Preserved, Not Active

Module count, inter-module operations, communication qubits, and purification model functions are preserved in `estimator_tier2_modular.py`. The `EstimationResult` dataclass retains all Tier 2 fields as `Optional[type]` defaulting to `None`. Reconnecting Tier 2 requires importing and calling those functions in `estimate()` Steps 4–6 and populating the Optional fields.

---

## Validated Results

Resource estimates are now circuit-specific through depth-derived LER targeting. The key insight is that shallow circuits need much less error correction than the old hardcoded 1e-6 target implied.

| Circuit | Depth | Fidelity | Success rate | Code distance | Phys/logical | Total qubits |
|---|---|---|---|---|---|---|
| test_circuit (5q) | 8 | 99.9% | 99% | 5 | 49 | 245 |
| test_circuit (5q) | 8 | 99.5% | 99% | 7 | 97 | 485 |
| qft_5qubit (5q) | 11 | 99.9% | 99% | 5 | 49 | 245 |
| qft_5qubit (5q) | 11 | 99.5% | 99% | 7 | 97 | 485 |

The old hardcoded 1e-6 target implicitly assumed circuits of depth ~100,000. For shallow test circuits it was over-engineering error correction by orders of magnitude, producing code distances of 11–39 where 5–7 is sufficient.

---

## Baby QREM UI

**Local:** `http://localhost:8000/scripts/qrem_ui.html`

### Controls (left panel, top to bottom)

**Circuit** — dropdown of available `.qasm` files from `data/circuits/`.

**Hardware Configuration** — collapsible profile selector. Two active dropdowns:
- *Qubits* — selects the qubit profile YAML (baseline or corpus-derived)
- *Error Correction* — selects the QEC profile YAML (sets threshold; target LER is overridden by depth)

Interconnect and module profile files are preserved in `hardware_profiles/` but not active in the single-module estimator.

**Target Circuit Success Rate** — dropdown: 90% / 99% / 99.9% / 99.99%. Sets the circuit-level success probability from which the per-gate LER target is derived. Default 99%.

**Two-Qubit Gate Fidelity** — slider 99.0% – 99.99%, overriding the qubit profile value. Primary sensitivity analysis control.

**Run Estimation** — executes the pipeline and renders all outputs.

### Metric Cards (four)

Code Distance · Phys/Logical · Logical Qubits · Total Physical. Each card has an expand affordance (`›`) showing the full calculation with substituted values. The Code Distance expand panel shows the complete derivation chain: `depth + success rate → LER target → d`.

### Staircase Chart

Fidelity → Physical Qubit Count. Built analytically from the single estimation result — no sweep API calls. Parameterized by code distance: one step per odd d value from 3 to 49. Each step appears at the exact fidelity threshold where that d becomes achievable. Steps are labeled `d=N` where space permits. Current position marked with a dot and label. X-axis scales automatically to the data range.

### Circuit Analysis Panel

Circuit depth · Single-qubit gates · Two-qubit gates · Measurements · Locality score · Hub qubits.

### Status Bar

Feasible/Not Feasible · physical error rate · logical error rate achieved · platform.

### API Endpoints

- `GET /api/profiles` — available profile names for UI dropdowns
- `GET /api/circuits` — available `.qasm` files
- `GET /static/{filename}` — static assets (C2QA logo, etc.)
- `POST /api/estimate` — run estimation; accepts `profile_overrides` including `target_circuit_success_rate`

---

## Hardware Profile Updater

**Status: Complete** | `ingester/generate_qubit_profile.py`

Generates a QREM qubit profile YAML from a materials database sample. Triggered via the "⚙ Generate Qubit Profile" button in the Materials Explorer detail panel. Measured fields labeled `[MEASURED]`; missing fields use `transmon_baseline_2026.yaml` defaults labeled `[ASSUMED]`. Generated profiles appear immediately in the Baby QREM qubit dropdown.

Note: most materials papers measure T1 and T2 but not gate fidelity. Profiles from such papers will have measured coherence but assumed gate parameters — the slider in the UI is the primary way to explore fidelity sensitivity.

---

## Materials-to-Device Mapping Layer

**Status: Design phase; first findings produced April 2026 via corpus mining**

Bridges material properties to device parameters for samples without direct device measurements.

| Noise channel | Material predictors | QREM parameter |
|---|---|---|
| Quasiparticle | RRR, T/Tc ratio | T1 |
| TLS dielectric | Loss tangent, surface oxide thickness | T1, T2, Qi |
| Vortex motion | Mean free path, vortex activation temperature | Qi, T1 |
| 1/f flux noise | Surface spin density, crystal phase | T2 |

The corpus mining pipeline (Phase A→B→C) extracts author-stated correlations from the materials database and produces structured findings. Approved findings will populate the mapping layer as the first implemented mapping functions.

---

## Stage 4 — Compare & Report (Planned)

**For materials scientists:** Sensitivity analysis — "if RRR improves from 45 to 65, what happens to code distance?" Routes material property improvements through the full pipeline to physical qubit count impact. This is the primary planned output for materials scientists.

**Coherence budget breakdown** — T1 loss attribution by mechanism (TLS, quasiparticle, vortex motion, radiation). Makes the qubit profile's T1 and T2 values meaningful in the estimator output.

**For device engineers:** Threshold identification — at what fidelity does a circuit become feasible? Device target specification — what T1 or gate fidelity is needed to reach a given code distance?

---

## Pluggable Components

| Component | Location | Status | Expert replacement |
|---|---|---|---|
| Circuit parser | `parser.py` | Complete | — |
| Circuit depth | `analyzer.py` | Complete | — |
| Error correction model | `estimator.py` | Analytical approximation | HetArch, Stim |
| Magic state factory | `estimator.py` | Placeholder (T gates = 0) | Full distillation model |
| Modular overhead | `estimator_tier2_modular.py` | Preserved, not active | Arquin |
| Qubit profiles | `hardware_profiles/qubits/` | Baseline + corpus-derived | Device measurements |
| Materials-to-device mappings | Mapping layer | Not yet implemented | Corpus mining findings |

---

## Open Research Questions

- What is the correct magic state factory count as a function of T gate rate and circuit depth?
- How should uncertainty in materials-to-device mappings propagate through the pipeline?
- How does SWAP routing overhead scale with circuit interaction graph density?
- Are there circuit classes for which one hardware platform is categorically superior?
- What graph partitioning objective best minimizes modular overhead? (Tier 2 question)
- How does QEC work across module boundaries in practice? (Tier 2 question)

---

## C2QA Ecosystem Integration

| Tool | Role | Location in pipeline |
|---|---|---|
| **Arquin** | Modular overhead cost model | Tier 2 — reconnect when ready |
| **HetArch** | Error correction layer | Replaces analytical approximation |
| **Stim** | High-performance QEC simulation | Error correction layer replacement |
| **Qualtran** (Google) | Algorithm-level resource estimation | Upstream of Stage 1 |
| **Azure QRE** (Microsoft) | Industry resource estimator | Validation baseline |
| **Bosonic ISA** | Qumode support | Requires parser/analyzer/model extensions |

---

*End of Specification Document v0.6*
*Updated April 29, 2026.*
*This document is intended to evolve with the research.*
