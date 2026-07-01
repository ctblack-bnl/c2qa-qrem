# Baby QREM — Quantum Resource Estimator

A materials-first, single-module quantum resource estimator for superconducting qubit systems.

**The question it answers:** *"I have a superconducting qubit with this T1 and T2. If I run this quantum circuit, how many physical qubits do I need — and how does that change as my materials improve?"*

Gate fidelity is derived from T1, T2, and gate time rather than taken as input. This makes the tool directly useful to materials scientists: vary T1, watch physical qubit count change. The T1 sensitivity curve shows exactly which T1 threshold gets you across each code distance step.

---

## Running Baby QREM

```bash
cd qrem/scripts
python3 serve.py
# Open http://localhost:8000/scripts/qrem_ui.html
```

The UI auto-runs on page load with default profile and circuit. No run button — estimation updates automatically when any control changes.

**Dependencies:**
```bash
pip install qiskit networkx pyyaml
```

The UI auto-runs on page load. Controls: circuit selector, qubit profile dropdown, T1/T2 sliders, target success rate. The T1 sensitivity staircase plots physical qubit count vs T1 on a log scale with code distance thresholds labeled.

---

## Pipeline architecture

```
OpenQASM circuit  +  Qubit profile YAML  +  QEC profile YAML
        |
   [Stage 1]  PARSE          parser.py
        |     OpenQASM → CircuitIR (gate list, qubit inventory, gate counts)
        |
   [Stage 2]  ANALYZE         analyzer.py
        |     Circuit depth (critical path), interaction graph, hub qubits
        |     Operates entirely in the logical world — no noise yet
        |
   [Stage 3]  ESTIMATE        estimator.py
        |     T1, T2 + gate_time → ε_T1, ε_T2, ε_ctrl → derived fidelity
        |     Circuit depth + success rate → per-gate LER target
        |     LER target + fidelity → code distance d
        |     d → physical qubits per logical (2d²-1) → total physical qubits
        |
   [Stage 4]  LOSS ATTRIBUTION    t1_decomposition.py
              T1 broken into: pad TLS / junction TLS / quasiparticle / radiation
              Shown in UI only when profile contains measured surface loss data
```

**Key design decision — materials-first:** Gate fidelity is an output, not an input.

```
ε_T1   = gate_time / T1        (energy relaxation — materials)
ε_T2   = gate_time / T2        (dephasing — materials + environment)
ε_ctrl = fixed from baseline   (pulse errors — engineering, not materials)
fidelity = 1 - ε_T1 - ε_T2 - ε_ctrl
```

`ε_ctrl` is always derived from `transmon_baseline_2026.yaml` and held fixed — it encodes the quality of the control system independently of which material is loaded.

---

## Hardware profiles

Platform parameters live in YAML files under `qrem/hardware_profiles/`. No code changes needed to add a new profile or run sensitivity analysis — just add a YAML and it appears in the UI dropdown.

```
hardware_profiles/
  qubits/
    transmon_baseline_2026.yaml        ← controls baseline (T1=200µs, T2=300µs, gate=50ns)
    {Material}_corpus_average.yaml     ← per-material corpus averages (auto-generated)
    {sample_display_name}.yaml         ← per-sample profiles from corpus records
  material_defaults/
    transmon_general_defaults.yaml     ← fallback defaults for t1_decomposition.py
    {Material}_material_defaults.yaml  ← per-material corpus-averaged defaults
  error_correction/
    surface_code_1e6.yaml              ← surface code threshold + target LER
```

**Tiered fallback — the estimator always estimates.** Every input follows a five-tier hierarchy so a number is always produced:

| Tier | Label | Source |
|---|---|---|
| 1 | `[MEASURED]` | Directly reported in the paper |
| 2 | `[DERIVED]` | Computed from measured quantities via physics |
| 3 | `[CORPUS AVERAGE — N samples]` | Mean across corpus for this material class |
| 4 | `[CLASS DEFAULT]` | Typical value for this material class |
| 5 | `[ASSUMED]` | Baseline profile default |

The UI shows which tier each input came from. A result built entirely on Tier 1 data is a measurement. A result built on Tier 4 is a benchmark. Both are useful but mean different things.

---

## Adding a circuit

Drop an OpenQASM 2.0 file in `data/circuits/` — it appears immediately in the UI circuit dropdown. The parser uses Qiskit and handles standard gate sets.

---

## Plugin points for contributors

Baby QREM is deliberately modular. The current implementation uses analytical approximations throughout — each component is designed to be replaced with a more accurate expert model. Here is where contributions are most needed:

### Error correction model (Stage 3) — `estimator.py`
**Current:** Analytical surface code approximation. Code distance computed from `(p/threshold)^((d+1)/2) <= target_LER`.

**Replacement target:** Full threshold simulation via [Stim](https://github.com/quantumlib/Stim) or the [HetArch](https://github.com/hetarch) heterogeneous architecture framework. A replacement just needs to accept `(physical_error_rate, target_LER)` and return a code distance.

### Noise model (Stage 3) — `estimator.py`
**Current:** First-order decoherence model (`ε = gate_time / T1`, `ε = gate_time / T2`). Valid when gate_time << T1, T2.

**Replacement target:** Full Lindblad master equation simulation, or a learned noise model from device characterization data. Interface: given T1, T2, gate_time, return total gate error rate.

### Modular overhead (Tier 2) — `estimator_tier2_modular.py`
**Current:** Functions written and preserved but not active. Single-module only.

**Replacement target:** Reconnect [Arquin](https://github.com/c2qa/arquin) modular overhead cost model when Center-wide architecture research matures. Adds inter-module link fidelity, purification rounds, and communication qubit counts to the resource estimate.

### Magic state factory (Stage 3) — `estimator.py`
**Current:** T gate count is a placeholder (0). Magic state factory costs are not modeled.

**Replacement target:** Full distillation cost model. T gate count is already tracked in `CircuitIR` — it just needs a factory cost function.

### Algorithm compilation (upstream of Stage 1)
**Current:** Accepts OpenQASM 2.0 directly — compilation is out of scope.

**Integration target:** [Qualtran](https://github.com/quantumlib/Qualtran) (Google) for algorithm-level resource estimation upstream of Stage 1. Qualtran can compile high-level quantum algorithms to gate counts that feed directly into Baby QREM.

### Bosonic qubits
**Current:** Transmon-only noise model and hardware profiles.

**Extension target:** Parser and analyzer are gate-set agnostic. The noise model and hardware profiles would need extension to support qumode operations and bosonic ISA.

---

## Key files

| File | Purpose |
|---|---|
| `parser.py` | Stage 1: OpenQASM → CircuitIR |
| `circuit_ir.py` | Internal circuit representation |
| `analyzer.py` | Stage 2: circuit depth, interaction graph |
| `estimator.py` | Stage 3: materials-first estimation |
| `t1_decomposition.py` | Stage 4: T1 loss channel breakdown |
| `profile_loader.py` | Loads qubit + QEC profile YAMLs |
| `estimator_tier2_modular.py` | Tier 2 modular functions (preserved, not active) |
| `scripts/serve.py` | HTTP server |
| `scripts/qrem_ui.html` | Browser UI |

---

## Known limitations

- Single-module only — SWAP routing overhead not modeled; physical qubit counts are lower bounds.
- Analytical surface code approximation — not full Stim simulation.
- T gate counting is a placeholder (0) — magic state factory costs are not modeled.
- Modular overhead not modeled — functions preserved in `estimator_tier2_modular.py`, not active.
- Loss mechanism attribution (Stage 4) shown only when the loaded profile contains measured surface loss data (tan_delta, Q_TLS,0). Hidden when sliders are moved from profile values.

---

