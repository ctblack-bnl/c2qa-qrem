# Quantum Resource Estimation — Baby QREM
## Pipeline Specification & Design Document

**Version:** 0.12 — Stage 4 UI integration complete (May 21)
**Date:** May 21, 2026
**Status:** Stages 1–4 complete; T1 loss channel breakdown panel operational; ε_ctrl fixed to controls baseline; material property sliders (Stage 5) planned
**Intended audience:** Device scientists, materials scientists, quantum architects
---

## Strategic Scope

Baby QREM is a **materials → single-module resource estimator**. It answers the question:

*"I have a superconducting qubit with this T1 and T2. If I run this quantum circuit, how many physical qubits do I need, and how does that change as my materials improve?"*

Gate fidelity is derived from T1, T2, and gate time — it is an output, not an input. This makes the tool directly useful to materials scientists: vary T1, watch physical qubit count change. The T1 sensitivity curve shows exactly which T1 threshold gets you across each code distance step.

The modular architecture question — how many modules, inter-module links, purification overhead — is a separate Center-wide research problem. Baby QREM deliberately stays out of that space.

---

## Key Design Decisions

**OpenQASM as input boundary.** The tool does not handle algorithm-to-circuit compilation. Accepting OpenQASM makes QREM compatible with any compiler that produces it.

**Strict separation of logical and physical worlds.** Stages 1–2 operate on the ideal, noiseless logical circuit. Error correction and hardware imperfections enter only in Stage 3.

**Circuit depth drives the error correction target.** The required logical error rate per gate is derived from circuit depth and a user-specified target circuit success rate:
```
target_LER_per_gate = 1 - success_rate ^ (1 / circuit_depth)
```
A shallow circuit (depth 8) can tolerate a much higher per-gate error rate than a deep circuit. This makes resource estimates honest and circuit-specific.

**Materials-first: T1/T2 → fidelity.** Gate fidelity is derived from material properties, not taken as input. The error decomposition model:
```
ε_T1    = gate_time / T1          (energy relaxation — materials)
ε_T2    = gate_time / T2          (dephasing — materials + environment)
ε_ctrl  = fixed from baseline     (pulse errors, leakage — engineering)
ε_total = ε_T1 + ε_T2 + ε_ctrl
fidelity = 1 - ε_total
```
Reference: standard first-order decoherence model, valid when gate_time << T1, T2.

**ε_ctrl is always derived from `transmon_baseline_2026` — the controls baseline.** ε_ctrl represents pulse engineering quality (pulse errors, leakage, calibration) — it is fixed by the control system, not by the material being studied. `transmon_baseline_2026` is explicitly the controls baseline: it encodes what the control system can achieve independently of which material sample is loaded. Corpus profiles (Wang, Bland, Joshi) contribute T1 and T2 only. ε_ctrl = 5.83e-4, always. This is essential — without this, loading a low-T2 corpus profile would corrupt ε_ctrl (clamping it to zero), blurring the code distance staircase and misrepresenting the error budget.

**T2 fallback.** If T2 is missing from a profile, T2 = 2×T1 (Bloch equation limit — optimistic, flagged as assumed). The estimator always estimates — it documents assumptions but never refuses to give a number.

**Hardware profiles as data, not code.** Platform parameters live in YAML files. Changing qubit profiles or running sensitivity analysis requires only editing or selecting a data file — no code changes.

**Corpus-derived qubit profiles.** Qubit profiles are generated from materials database records via the Hardware Profile Updater. Measured fields labeled `[MEASURED]`; missing fields use baseline defaults labeled `[ASSUMED]`. Sliders initialize to the loaded profile's actual T1/T2 values on page load.

**PUK as the eventual direct feed into QREM.** The current YAML workflow (Explorer sample → `generate_qubit_profile.py` → YAML file → QREM) is a transitional architecture. The target state is that QREM queries the materials database directly, reading PUKs in memory — no YAML export step, no separate Explorer-to-YAML conversion. PUKs already contain everything QREM needs (T1, T2, gate fidelity, provenance, confidence levels). The YAML files are a workaround for the current disconnection between the two systems, not a permanent interface.

**Honest uncertainty representation.** All simplifying assumptions are explicitly documented in every tool output.

**Tier 2 preserved, not active.** Modular overhead functions are preserved in `estimator_tier2_modular.py`. `EstimationResult` retains all Tier 2 fields as `Optional`, defaulting to `None`.

---

## System Architecture

```
Scientific Papers
      ↓
[Ingester] → Materials Database (PUKs)
      |
      |── Measured device performance (T1, T2)
      |   → Hardware Profile Updater → qubit profile YAML   ← current (transitional)
      |                                        ↓
      |   [target: QREM reads PUKs directly, no YAML step]
      |                                        ↓
      |                               [Baby QREM Pipeline]
      |                                        ↑
      └── Material properties (Tc, RRR, loss tangent)
          → Materials Predictor → Mapping Layer (planned)
```

The scientific question Baby QREM currently answers:
*"Given this qubit's T1 and T2 and this circuit, how many physical qubits are needed for the circuit to succeed with X% probability?"*

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
         |     → clean profile → ε_ctrl baseline (fixed)
         |     → T1, T2 (slider) + gate_time → ε_T1, ε_T2
         |     → ε_total → derived gate fidelity
         |     → depth + success rate → per-gate LER target
         |     → LER target + fidelity → code distance d
         |     → d → physical qubits per logical qubit (2d² - 1)
         |     → total physical qubits (computation + factory placeholder)
         |     → EstimationResult + explicit assumptions
         |
    [Stage 4]  LOSS MECHANISM ATTRIBUTION  (complete May 21)
               → T1 breakdown: TLS / quasiparticle / vortex motion / radiation
               → connects to materials properties (RRR → quasiparticle, Qi → TLS)
               → panel shown in UI when corpus profile loaded; hidden when sliders touched
```

---

## Implementation Status

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Parser + Analyzer (Stages 1–2) | ✅ Complete |
| **Phase 2** | Single-module estimator (Stage 3) + UI | ✅ Complete |
| **Phase 3** | Materials-first estimation: T1/T2 → fidelity, error attribution | ✅ Complete May 2026 |
| **Phase 3b** | UI declutter (Part A) | ✅ Complete May 9, 2026 |
| **Phase 4** | Loss mechanism attribution: T1 → TLS/QP/vortex breakdown | ✅ Complete May 21. `t1_decomposition.py` Stage B validated May 16. Stage C (UI integration) complete May 21. T1 loss channel breakdown panel in Error Attribution section. Panel shows when corpus profile loaded with measured tan_delta; hidden when sliders touched (`slidersMoved` flag). ε_ctrl fixed to controls baseline. T1 slider extended to 1000µs. |
| **Phase 4b** | Part B material deep dive drawer | Superseded by Stage 4 panel design. The collapsible "T1 Loss Channel Breakdown" panel in the Error Attribution section serves this role. No separate bottom drawer needed. |
| **Phase 5** | Material property sliders → T1 | Planned. Forward direction only: tan_delta, p_MS_pad, RRR sliders feed through `t1_decomposition.py` → predicted T1 → staircase. Inverse direction (slider T1 → material properties) is underdetermined and not attempted. Corpus-average PUKs per material class also planned (Tier 3 device averages buildable now; Tier 2 material averages require Stage 4). |
| **Phase 6** | Expert component replacement (HetArch, Stim) | Pending |

---

## Code Structure

```
src/qrem/
  parser.py                     — Stage 1: OpenQASM → CircuitIR
  circuit_ir.py                 — Internal circuit representation
  analyzer.py                   — Stage 2: interaction graph, circuit depth
  estimator.py                  — Stage 3: materials-first estimation (Tier 1)
    _derive_control_error_baseline()  — ε_ctrl from clean profile (fixed)
    _compute_coherence_budget()       — forward: T1, T2 → fidelity
    estimate()                        — accepts epsilon_control_baseline param
    run_estimation()                  — loads clean + override profiles
  estimator_tier2_modular.py    — Tier 2 functions: preserved, not active
  profile_loader.py             — Profile loader: partial modular (qubits + QEC)
  hardware_profiles/
    qubits/
      transmon_baseline_2026.yaml     — Baseline: T1=200µs, T2=300µs, gate=50ns, F=99.9%
      {sample_display_name}.yaml      — Corpus-derived profiles (Hardware Profile Updater)
    interconnects/                    — Preserved for Tier 2 reconnection
    modules/                          — Preserved for Tier 2 reconnection
    error_correction/
      surface_code_1e6.yaml           — threshold + target LER (target overridden by depth)
    superconducting.yaml              — Legacy monolithic profile (still supported)
    mapping_models/               — T1 decomposition model inputs
      transmon_analytical_defaults.yaml  — class defaults: p_MS_pad (Joshi 2026),
                                           tan_delta_effective_surface, junction TLS,
                                           QP non-equilibrium floor, vortex (disabled)
      example_material_record.yaml       — Joshi 2026 Qubit-2 (gold validation case)
      joshi_2026_qubit1.yaml             — validation: f=2.613 GHz, T1=397µs
      joshi_2026_qubit6.yaml             — validation: f=4.696 GHz, T1=236µs
      joshi_2026_qubit11.yaml            — validation: f=5.804 GHz, T1=40µs

  t1_decomposition.py           — Stage 4 backend: two-level T1 loss channel decomposition.
                                   Resonator as calibration (not loss channel). Per-channel
                                   provenance. Model validation against measured T1.
                                   CLI: python3 t1_decomposition.py <record.yaml> <defaults.yaml>

scripts/
  serve.py                      — HTTP server: Baby QREM UI + static files
    /api/profiles               — list available profile components
    /api/circuits               — list available .qasm files
    /api/profile_values         — T1/T2/gate_time for slider initialization
    /api/estimate               — run estimation
    /static/                    — static assets
  qrem_ui.html                  — Baby QREM browser UI

data/circuits/
  test_circuit.qasm             — 3-qubit repetition code syndrome (5 qubits, depth 8)  [default]
  test_circuit_02.qasm          — VQE ansatz layer (4 qubits)
  qft_5qubit.qasm               — Quantum Fourier Transform (5 qubits, depth 11)
```

---

## Running the Pipeline

```bash
# UI (recommended) — auto-runs on load with defaults
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

Operates entirely in the logical world.

**Circuit depth** — critical path length via single forward pass over ordered gate list. For each gate, `depth = max(depth of its qubits) + 1`. Measurements included (Qiskit convention). Circuit depth is the primary driver of the per-gate LER target.

**Interaction graph** — weighted qubit interaction graph. Hub qubits, locality score (0 = broadly distributed interactions, 1 = same pairs interact repeatedly).

---

## Stage 3 — Estimate

**Status: Complete** | `estimator.py`

### Error Decomposition Model

```python
# Step 0: derive ε_ctrl from transmon_baseline_2026 (controls baseline) — done once, held fixed
# transmon_baseline_2026 is the controls baseline — encodes pulse engineering quality,
# independent of which material profile is selected. Corpus profiles contribute T1/T2 only.
epsilon_control = (1 - fidelity_pct/100) - gate_time_us/T1_us - gate_time_us/T2_us
epsilon_control = max(0, epsilon_control)  # clamp — baseline is self-consistent

# Step 1: forward calculation from T1, T2 (slider values)
epsilon_T1    = gate_time_us / T1_us
epsilon_T2    = gate_time_us / T2_us
epsilon_total = epsilon_T1 + epsilon_T2 + epsilon_control  # ε_ctrl fixed
derived_fidelity = 1.0 - epsilon_total

# Step 2: code distance from derived fidelity
physical_error_rate = epsilon_total
target_LER = 1 - success_rate ^ (1 / circuit_depth)
code_distance = smallest odd d such that (p/threshold)^((d+1)/2) <= target_LER

# Step 3: physical qubit counts
physical_qubits_per_logical = 2 * d^2 - 1
total_physical_qubits = num_logical_qubits * physical_qubits_per_logical
```

### T2 Fallback

If T2 is absent from the profile: `T2 = 2 × T1` (Bloch equation limit — the best physically possible T2 given T1; actual T2 may be lower due to pure dephasing from flux noise, charge noise, TLS). Flagged as `[ASSUMED: 2×T1]` in the UI.

### Assumptions (reported in every output)

1. Gate fidelity derived from T1/T2/gate_time via first-order decoherence model. Valid when gate_time << T1, T2.
2. ε_ctrl fixed from baseline profile — not materials-dependent.
3. Perfect intra-module connectivity — no SWAP routing overhead. Physical qubit count is a lower bound.
4. Analytical surface code approximation — not full Stim simulation.
5. T gate count is placeholder (0) — magic state factory costs underestimated for T-heavy circuits.
6. Modular overhead (Tier 2) not modeled.

### Tier 2 — Preserved, Not Active

Module count, inter-module operations, communication qubits, and purification model functions preserved in `estimator_tier2_modular.py`. `EstimationResult` retains all Tier 2 fields as `Optional[type]` defaulting to `None`.

---

## Validated Results

Fidelity is now derived from T1/T2, so results are shown at the baseline profile values (T1=200µs, T2=300µs, gate_time=50ns → derived fidelity 99.900%):

| Circuit | Depth | T1 | Derived fidelity | Success rate | Code distance | Total qubits |
|---|---|---|---|---|---|---|
| test_circuit (5q) | 8 | 200µs | 99.900% | 99% | 5 | 245 |
| test_circuit (5q) | 8 | 50µs | 99.808% | 99% | 7 | 485 |
| qft_5qubit (5q) | 11 | 200µs | 99.900% | 99% | 5 | 245 |
| qft_5qubit (5q) | 11 | 50µs | 99.808% | 99% | 7 | 485 |

Key insight: a 4× improvement in T1 (50µs → 200µs) moves the circuit from code distance 7 to 5 — roughly halving the physical qubit count. The T1 sensitivity curve shows exactly where these thresholds are.

---

## Baby QREM UI

**Local:** `http://localhost:8000/scripts/qrem_ui.html`

The UI auto-runs on page load with default profile and circuit. No run button — estimation triggers automatically when any control changes.

### Left Panel (controls only)

**Circuit** — dropdown, defaults to `test_circuit.qasm`.

**Hardware Configuration** — collapsible. Two active dropdowns:
- *Qubits* — selects qubit profile YAML. Changing this re-initializes T1/T2 sliders from the profile's actual values.
- *Error Correction* — selects QEC profile YAML.

**Target Circuit Success Rate** — 90% / 99% / 99.9% / 99.99%. Default 99%.

**T1 slider** — 10–1000µs. Debounced 400ms. Shows [MEASURED] or [ASSUMED] from profile provenance. Extended to 1000µs May 21 to accommodate high-T1 corpus profiles (e.g. Bland_2025_Qubit_16 at 794µs).

**T2 slider** — 10–1000µs. "Link T2 = 2×T1" checkbox (Bloch limit). Shows [MEASURED], [ASSUMED], or [MANUAL].

**Gate Time (read-only)** — from profile. Shows [MEASURED] or [ASSUMED]. Fixed by gate implementation — not a material property.

**Simplifying Assumptions** — moved to `▸ Reference Details` collapsible at bottom of left panel. Hidden by default, accessible when needed.

**Circuit Analysis** — moved to `▸ Reference Details` collapsible alongside Simplifying Assumptions. Depth, single-qubit gates, two-qubit gates, measurements, locality score, hub qubits.

### Metric Cards (five, collapsible)

Derived Fidelity · Code Distance · Phys/Logical · Logical Qubits · Total Physical. Each card expands to show the derivation chain with substituted values.

### T1 Sensitivity Chart

T1 (µs) → Physical Qubit Count, log y-axis. Built analytically — no API sweep. Staircase steps labeled `d=N`. Current T1 position marked with stacked label showing T1 and qubit count. X-axis 10–1000µs; y-axis log scale (powers of 10) so all steps are visible across the full T1 range.

### Error Attribution Panel (full-width)

Gate Error Decomposition bar — ε_T1 / ε_T2 / ε_ctrl with fractions and stacked bar. Provenance line showing [MEASURED] vs [ASSUMED] fields.

**T1 Loss Channel Breakdown panel (Stage 4):** Collapsible section below the gate error decomposition. Shows T1 decomposed into physical loss channels when a corpus-derived profile with measured surface loss data is loaded:
- tan_delta with provenance tag
- Pad TLS, Junction TLS, Quasiparticle, Vortex, Radiation — each with T1 contribution and provenance
- T1 predicted vs T1 measured with ✓/✗ within 5× validation indicator

Panel visibility rules:
- Shown only when `tan_delta_provenance` is MEASURED or DERIVED (i.e. real surface loss data exists in the profile)
- Hidden immediately when either T1 or T2 slider is touched (`slidersMoved` flag) — decomposition is only valid at profile values, not hypothetical slider positions
- Hidden for baseline profile and profiles with no surface loss data (all CLASS_DEFAULT)

### Status Bar

Feasible/Not Feasible · physical error rate · logical error rate achieved.

### API Endpoints

- `GET /api/profiles` — available profile names for UI dropdowns
- `GET /api/circuits` — available `.qasm` files
- `GET /api/profile_values?qubits=<name>` — T1/T2/gate_time for slider initialization
- `GET /static/{filename}` — static assets
- `POST /api/estimate` — run estimation; `profile_overrides` accepts `coherence: {T1_us, T2_us}` and `target_circuit_success_rate`

---

## Hardware Profile Updater

**Status: Complete** | `ingester/generate_qubit_profile.py`

Generates a QREM qubit profile YAML from a materials database sample. Measured fields labeled `[MEASURED]`; missing fields use `transmon_baseline_2026.yaml` defaults labeled `[ASSUMED]`. Generated profiles appear immediately in the Baby QREM qubit dropdown and sliders initialize to their actual T1/T2 values.

Most materials papers measure T1 and T2 but not gate fidelity. Profiles from such papers have measured coherence, assumed gate parameters, and assumed ε_ctrl — the T1/T2 sliders are the primary sensitivity analysis tool for these profiles.

---

## Tiered Fallback Hierarchy — Core Design Principle

**The estimator always estimates.** For any given corpus record, some quantities will be directly measured, some can be derived from what was measured, and some must be assumed. The estimator handles all cases gracefully, always produces a number, and always documents exactly what it assumed.

Every input to Baby QREM follows a five-tier fallback:

| Tier | Source | Label | Example |
|---|---|---|---|
| 1 | Directly measured in the paper | `[MEASURED]` | T1 = 85µs from time-domain measurement |
| 2 | Derived from measured quantities via physics formulas | `[DERIVED]` | T1 estimated from Qi: `T1 ≈ Qi / (2πf)` |
| 3 | Corpus-computed average for this material class | `[CORPUS AVERAGE — N samples]` | Ta mean T1 = 312µs ± 95µs across 12 corpus samples |
| 4 | Static value for this material class | `[CLASS DEFAULT]` | Ta films typically achieve T1 ~100µs |
| 5 | Baseline profile assumption | `[ASSUMED]` | `transmon_baseline_2026.yaml` default |

Tier 3 (corpus average) is planned — not yet implemented. See continuity doc for design details.

The UI always shows which tier each input came from, so a scientist can immediately see how much of the result is real data vs assumptions. A result built entirely on Tier 1 data is a measurement. A result built on Tier 4 data is a benchmark. Both are useful — but they mean different things.

**This is the intended use case:** for a given paper ingested into the corpus, pull out all available materials information, map it to QREM inputs using the best available tier, and estimate. A paper reporting T1 and T2 directly gets a Tier 1 result. A paper reporting only Qi gets a Tier 2 result. A film-only paper with no device measurements gets a Tier 3 or 4 result — still useful as a benchmark showing what the material *could* achieve.

**Tier 2 derivation formulas (to be implemented in Stage 4):**

| QREM input | If not measured, derive from | Formula |
|---|---|---|
| T1 (TLS contribution) | Q_TLS,0, p_MS_resonator, p_MS_pad, f_qubit | Two-step Joshi inversion: tan_delta = 1/(Q_TLS,0 × p_MS_resonator), then T1_pad_TLS = 1/(p_MS_pad × tan_delta × 2πf). Both participation ratios required — gap in p_MS_resonator alone gives 6x uncertainty in tan_delta. See `loss_channel_model_v2-5.md` and `t1_decomposition.py`. |
| T1 (quasiparticle contribution) | RRR, Tc, operating temperature | Standard QP density model |
| T1 (vortex contribution) | Mean free path, vortex activation temperature | Loss model from clean/dirty limit |
| T2 | T1 (if T2 not measured) | `T2 = 2×T1` (Bloch limit, optimistic) |
| Gate fidelity | T1, T2, gate_time | `F = 1 - ε_T1 - ε_T2 - ε_ctrl` (already implemented) |

Note: Tier 2 formulas use well-established physics and can be implemented immediately — they do not require corpus mining findings. Corpus mining findings will eventually *validate and refine* these formulas, but are not a prerequisite for building the capability.

---

## Materials-to-Device Mapping Layer

**Status: Stage 4 backend validated (`t1_decomposition.py`); not yet integrated into estimator. First approved findings in `findings.jsonl` as of May 2026.**

Bridges material properties to device parameters for samples without direct device measurements. Provides the Tier 2 and Tier 3 fallback values described above.

| Noise channel | Material predictors | QREM parameter |
|---|---|---|
| Quasiparticle | RRR, T/Tc ratio | T1 contribution |
| TLS dielectric | Loss tangent, surface oxide thickness | T1, T2 contribution |
| Vortex motion | Mean free path, vortex activation temperature | T1 contribution |
| 1/f flux noise | Surface spin density, crystal phase | T2 contribution |

Initial mapping functions use standard analytical formulas (see Tier 2 table above). Corpus mining findings will validate and refine these as the corpus grows.

---

## Stage 4 — Loss Mechanism Attribution (Complete May 21)

Break T1 into contributions by physical mechanism: TLS substrate loss, TLS interface loss, quasiparticle loss, vortex motion, radiation. Each mechanism connects directly to a material property or fabrication parameter.

**Stage B (backend) — complete May 16.** `t1_decomposition.py` rewritten. Resonator excluded from Level 1 sum; junction uses single effective loss tangent; units fix (GHz → cycles/µs); QP uses non-equilibrium floor. Validated against 4 Joshi 2026 qubits — all pass 5x threshold with correct frequency scaling (T1_pad_TLS ∝ 1/f). Key defaults: p_MS_pad=1.3e-4, tan_delta=1.6e-3 (β-Ta), T1_junction_TLS~1000µs, T1_QP=1000µs (non-equilibrium), T1_radiation=5000µs.

**Stage C (UI integration) — complete May 21.** `t1_decomposition.py` wired into `run_estimation()`. Decomposition result flows through `EstimationResult.t1_decomposition` → `to_dict()` → JSON → browser. T1 Loss Channel Breakdown panel added to Error Attribution section in `qrem_ui.html`. `slidersMoved` flag controls panel visibility. `profileRawT1` tracks actual profile T1 before slider clamping.

**ε_ctrl bug fixed May 21.** ε_ctrl was previously derived from the selected corpus profile, producing ε_ctrl=0 for low-T2 profiles (e.g. Wang_2026_Transmon_2, T2=51µs). Fixed: ε_ctrl always derived from `transmon_baseline_2026` via `load_profile(profiles_dir=profiles_dir, qubits='transmon_baseline_2026')` in `run_estimation()`.

**Panel visibility criterion:** Panel shown only when `tan_delta_provenance` is MEASURED or DERIVED. Hidden when all inputs are CLASS_DEFAULT — showing class defaults as if they were predictions about a specific sample is misleading. In practice: Joshi profiles show (tan_delta_effective_surface measured from 71 resonators); Bland and Wang hide (no surface loss data).

**Stage 5 (planned):** Add forward-direction material property sliders (tan_delta, p_MS_pad, RRR) that feed through `t1_decomposition.py` → predicted T1 → staircase. Forward direction is well-determined; inverse (slider T1 → material properties) is underdetermined and not attempted.

---

## Pluggable Components

| Component | Location | Status | Expert replacement |
|---|---|---|---|
| Circuit parser | `parser.py` | Complete | — |
| Circuit depth | `analyzer.py` | Complete | — |
| Error decomposition model | `estimator.py` | First-order analytical | Full Lindblad simulation |
| Error correction model | `estimator.py` | Analytical approximation | HetArch, Stim |
| Magic state factory | `estimator.py` | Placeholder (T gates = 0) | Full distillation model |
| Modular overhead | `estimator_tier2_modular.py` | Preserved, not active | Arquin |
| Qubit profiles | `hardware_profiles/qubits/` | Baseline + corpus-derived | Device measurements |
| Materials-to-device mappings | Mapping layer | Not yet implemented | Corpus mining findings |

---

## Open Research Questions

- How should T1 loss be partitioned among TLS, quasiparticle, vortex, and radiation mechanisms from available material measurements?
- How should uncertainty in materials-to-device mappings propagate through to physical qubit count uncertainty?
- What is the correct magic state factory count as a function of T gate rate and circuit depth?
- How does SWAP routing overhead scale with circuit interaction graph density?
- Are there circuit classes for which one hardware platform is categorically superior?
- What graph partitioning objective best minimizes modular overhead? (Tier 2 question)

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

*End of Specification Document v0.12*
*Updated May 21, 2026.*
*This document is intended to evolve with the research.*
