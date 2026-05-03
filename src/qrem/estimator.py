# estimator.py
# Stage 3 of the QREM pipeline: Translate logical circuit analysis into
# physical resource requirements for a given hardware platform.
#
# Takes:
#   - AnalysisResult from Stage 2 (the interaction graph and circuit metrics)
#   - A hardware profile (loaded from a yaml file)
#
# Produces (Tier 1 — single-module baseline):
#   - Physical error rate derived from two-qubit gate fidelity
#   - Code distance (how large the surface code needs to be)
#   - Physical qubits per logical qubit  (= 2d² - 1)
#   - Total physical qubit count (computation + factory)
#   - T gate / magic state factory estimate
#   - Feasibility assessment
#
# NOT produced (Tier 2 — modular overhead — preserved in estimator_tier2_modular.py):
#   - Module count, inter-module operations, inter-module link cost,
#     communication qubit overhead, purification rounds.
#   Tier 2 is a Center-wide research problem. When it matures, the functions
#   in estimator_tier2_modular.py reconnect here as Steps 4-6.
#
# Key simplifying assumptions (documented honestly):
#   1. Perfect intra-module connectivity assumed (no SWAP routing overhead).
#      Physical qubit count is a lower bound.
#   2. Simplified surface code analytical formula (not full Stim simulation).
#   3. Magic state factory cost uses standard distillation overhead estimate.
#   4. Modular overhead (Tier 2) not modeled — single-module estimator only.
#
# Usage (programmatic — e.g. from serve.py):
#   from qrem.estimator import run_estimation
#   result = run_estimation("data/circuits/test_circuit.qasm",
#                           "src/qrem/hardware_profiles/superconducting.yaml",
#                           profile_overrides={"gates": {"two_qubit_fidelity_pct": 99.9}})
#   data = result.to_dict()
#
# Usage (CLI):
#   python3 estimator.py <circuit.qasm> <hardware_profile.yaml>

import math
import yaml
import dataclasses
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from analyzer import AnalysisResult
from profile_loader import load_profile, list_profiles


@dataclass
class EstimationResult:
    """
    The output of Stage 3 estimation.
    Contains physical resource requirements for one hardware platform.

    Tier 1 fields (active) are populated on every run.
    Tier 2 fields (modular overhead) are declared here but set to None —
    they will be populated when estimator_tier2_modular.py is reconnected.
    """
    # --- Provenance ---
    source_file: str
    platform: str

    # --- Circuit depth and target derivation ---
    circuit_depth: int                      # critical path length from Stage 2
    target_circuit_success_rate: float      # e.g. 0.99 — user-specified
    target_logical_error_rate: float        # derived: 1 - (1-success)^(1/depth)

    # --- Error correction (Tier 1) ---
    physical_error_rate: float          # derived from two-qubit gate fidelity
    code_distance: int                  # smallest odd d achieving target logical error rate
    logical_error_rate_achieved: float  # what logical error rate we actually achieve

    # --- Physical qubit counts (Tier 1) ---
    num_logical_qubits: int             # from the circuit
    physical_qubits_per_logical: int    # = 2d² - 1
    computation_qubits: int             # logical qubits * physical_qubits_per_logical

    # --- T gate / magic state factories (Tier 1) ---
    num_t_gates: int
    num_factories_needed: int
    factory_qubits: int
    qubits_per_factory: int

    # --- Total physical qubits (Tier 1 — computation + factory only) ---
    total_physical_qubits: int

    # --- Tier 2 fields — modular overhead (not yet active, preserved for future) ---
    # These are set to None in the current single-module estimator.
    # When estimator_tier2_modular.py is reconnected, these will be populated.
    physical_qubits_per_module: Optional[int] = None    # from module profile
    num_modules: Optional[int] = None                   # ceil(total / qubits_per_module)
    num_intermodule_operations: Optional[int] = None    # two-qubit gates crossing module boundaries
    intermodule_fraction: Optional[float] = None        # fraction of two-qubit gates inter-module
    purification_rounds: Optional[int] = None           # rounds of entanglement purification
    fidelity_after_purification_pct: Optional[float] = None
    effective_gate_time_us: Optional[float] = None
    inter_module_slowdown_factor: Optional[int] = None
    comm_qubits_per_link: Optional[int] = None
    comm_qubits_total: Optional[int] = None

    # --- Coherence budget ---
    # T1-limited fidelity ceiling: the maximum gate fidelity physically achievable
    # given T1 and gate time. If profile fidelity exceeds this, it is inconsistent.
    t1_limited_fidelity_pct: Optional[float] = None   # 1 - t_gate/T1, as a percentage
    effective_two_qubit_fidelity_pct: Optional[float] = None  # min(profile, T1 ceiling)

    # Error decomposition — fractional contributions to total gate error.
    # Based on standard first-order decoherence model (valid when t_gate << T1, T2).
    # coherence_budget keys: 'epsilon_T1', 'epsilon_T2', 'epsilon_control',
    #                         'total_error', 'T1_us', 'T2_us', 'gate_time_ns',
    #                         'T1_fraction_pct', 'T2_fraction_pct', 'control_fraction_pct',
    #                         'measured_fields', 'assumed_fields'
    coherence_budget: Optional[dict] = None

    # --- Feasibility ---
    feasible: bool = True
    feasibility_notes: List[str] = field(default_factory=list)

    # --- Circuit analysis (from Stage 2) ---
    num_single_qubit_gates: int = 0
    num_two_qubit_gates_circuit: int = 0
    num_measurements: int = 0
    locality_score: float = 0.0
    hub_qubits: List[str] = field(default_factory=list)

    # --- Assumptions ---
    assumptions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """
        Serialize to a plain dict suitable for JSON serialization.
        Optional fields that are None are included as null.
        """
        return dataclasses.asdict(self)

    def summary(self) -> str:
        lines = []
        lines.append(f"Resource Estimation: {self.source_file}")
        lines.append(f"Platform: {self.platform}")
        lines.append("")
        lines.append(f"--- Circuit ---")
        lines.append(f"  Circuit depth            : {self.circuit_depth}")
        lines.append(f"  Target success rate      : {self.target_circuit_success_rate*100:.1f}%")
        lines.append(f"  Target LER per gate      : {self.target_logical_error_rate:.2e}")
        lines.append("")
        lines.append("--- Error Correction ---")
        lines.append(f"  Physical error rate      : {self.physical_error_rate:.4f} ({self.physical_error_rate*100:.2f}%)")
        lines.append(f"  Code distance (d)        : {self.code_distance}")
        lines.append(f"  Physical qubits/logical  : {self.physical_qubits_per_logical} (= 2d² - 1)")
        lines.append(f"  Logical error rate       : {self.logical_error_rate_achieved:.2e}")
        lines.append("")
        lines.append("--- Qubit Counts ---")
        lines.append(f"  Logical qubits           : {self.num_logical_qubits}")
        lines.append(f"  Computation qubits       : {self.computation_qubits}")
        lines.append(f"  T gates in circuit       : {self.num_t_gates}")
        lines.append(f"  Magic state factories    : {self.num_factories_needed}")
        lines.append(f"  Factory qubits           : {self.factory_qubits}")
        lines.append(f"  TOTAL physical qubits    : {self.total_physical_qubits}")
        lines.append("")
        lines.append("--- Feasibility ---")
        lines.append(f"  Feasible                 : {'YES' if self.feasible else 'NO'}")
        for note in self.feasibility_notes:
            lines.append(f"  Note: {note}")
        lines.append("")
        lines.append("--- Assumptions ---")
        for assumption in self.assumptions:
            lines.append(f"  * {assumption}")
        return "\n".join(lines)


def _compute_code_distance(physical_error_rate: float,
                           target_logical_error_rate: float,
                           threshold: float) -> Tuple[int, float]:
    """
    Compute the minimum surface code distance d needed to achieve
    the target logical error rate given the physical error rate.
    Uses the standard surface code approximation:
        logical_error_rate ≈ (physical_error_rate / threshold) ^ ((d+1)/2)
    Returns (code_distance, logical_error_rate_achieved)
    Code distance is always an odd integer (surface code requirement).
    """
    if physical_error_rate >= threshold:
        return 1, physical_error_rate
    for d in range(3, 100, 2):
        ratio = physical_error_rate / threshold
        logical_error_rate = ratio ** ((d + 1) / 2)
        if logical_error_rate <= target_logical_error_rate:
            return d, logical_error_rate
    return 99, float('inf')


def _estimate_magic_state_factories(num_t_gates: int,
                                    profile: dict) -> Tuple[int, int, int]:
    """
    Estimate the number of magic state factories needed and their qubit cost.
    Returns (num_factories, qubits_per_factory, total_factory_qubits)
    """
    if num_t_gates == 0:
        return 0, 0, 0
    qubits_per_factory = profile.get('magic_state_factory', {}).get(
        'qubits_per_factory', 1000
    )
    num_factories = 1
    return num_factories, qubits_per_factory, num_factories * qubits_per_factory


def _derive_control_error_baseline(profile: dict) -> float:
    """
    Derive ε_control from the baseline profile's stated fidelity and T1/T2/gate_time.

    This anchors the control error to what the baseline profile implies, rather
    than picking an arbitrary number. For corpus-derived profiles where fidelity
    is assumed (not measured), this gives a self-consistent baseline.

    ε_control = (1 - fidelity) - gate_time/T1 - gate_time/T2
    Clamped to 0 if negative (coherence-limited regime).

    Called once at estimation time to fix ε_control for the forward calculation.
    """
    coherence    = profile.get('coherence', {})
    gates        = profile.get('gates', {})
    T1_us        = coherence.get('T1_us', 200.0)
    T2_us        = coherence.get('T2_us', 300.0)
    gate_time_ns = gates.get('two_qubit_gate_time_ns', 50.0)
    fidelity_pct = gates.get('two_qubit_fidelity_pct', 99.9)

    gate_time_us    = gate_time_ns / 1000.0
    epsilon_total   = 1.0 - (fidelity_pct / 100.0)
    epsilon_T1      = gate_time_us / T1_us
    epsilon_T2      = gate_time_us / T2_us
    epsilon_control = max(0.0, epsilon_total - epsilon_T1 - epsilon_T2)
    return epsilon_control


def _compute_coherence_budget(profile: dict,
                               epsilon_control_baseline: float) -> dict:
    """
    Forward calculation: derive gate fidelity from T1, T2, gate_time, and a
    fixed control error baseline.

    Mode 1 — materials-first:
        Inputs:  T1, T2 (material properties), gate_time (device parameter),
                 epsilon_control_baseline (fixed, derived from baseline profile)
        Outputs: epsilon_T1, epsilon_T2, epsilon_total, derived_fidelity_pct

    This is the reverse of the old approach. Fidelity is now an OUTPUT,
    not an input. The researcher varies T1 and T2; everything else follows.

    T2 fallback: if T2 is not present in the profile, use T2 = 2*T1
    (theoretical Bloch equation limit — optimistic, flagged as assumed).

    Reference: standard first-order decoherence model, valid when t_gate << T1, T2.
    Control error baseline derived from profile's stated fidelity (Option 2).
    """
    coherence  = profile.get('coherence', {})
    gates      = profile.get('gates', {})
    provenance = profile.get('provenance', {})

    T1_us        = coherence.get('T1_us')
    T2_us_raw    = coherence.get('T2_us')
    gate_time_ns = gates.get('two_qubit_gate_time_ns')

    measured_fields = list(provenance.get('measured_fields', []))
    assumed_fields  = list(provenance.get('assumed_fields', []))
    assumptions     = []

    # Cannot compute without T1 and gate_time — use profile defaults
    if T1_us is None:
        T1_us = 200.0
        assumed_fields.append('T1_us')
        assumptions.append("T1 not in profile — using default 200 µs.")

    if gate_time_ns is None:
        gate_time_ns = 50.0
        assumed_fields.append('two_qubit_gate_time_ns')
        assumptions.append("Gate time not in profile — using default 50 ns.")

    # T2 fallback: use T2 = 2*T1 (Bloch equation limit) if not measured
    t2_assumed = False
    if T2_us_raw is None:
        T2_us = 2.0 * T1_us
        t2_assumed = True
        assumed_fields.append('T2_us')
        assumptions.append(
            f"T2 not measured — using T2 = 2×T1 = {T2_us:.0f} µs "
            f"(Bloch equation limit, optimistic; actual T2 may be lower due to pure dephasing)."
        )
    else:
        T2_us = T2_us_raw

    gate_time_us = gate_time_ns / 1000.0

    # Forward calculation: T1, T2, gate_time → error contributions → fidelity
    epsilon_T1      = gate_time_us / T1_us
    epsilon_T2      = gate_time_us / T2_us
    epsilon_total   = epsilon_T1 + epsilon_T2 + epsilon_control_baseline
    # Clamp: total error can't exceed 1.0
    epsilon_total   = min(epsilon_total, 1.0)
    derived_fidelity_pct = (1.0 - epsilon_total) * 100.0

    # T1-limited ceiling: best possible fidelity from T1 alone (T2, control = 0)
    t1_limited_fidelity_pct = (1.0 - epsilon_T1) * 100.0

    # Fractional breakdown — always meaningful in forward mode since
    # epsilon_total is constructed from the three components
    if epsilon_total > 0:
        T1_fraction_pct      = (epsilon_T1                / epsilon_total) * 100.0
        T2_fraction_pct      = (epsilon_T2                / epsilon_total) * 100.0
        control_fraction_pct = (epsilon_control_baseline  / epsilon_total) * 100.0
        fractions_meaningful = True
    else:
        T1_fraction_pct = T2_fraction_pct = control_fraction_pct = 0.0
        fractions_meaningful = False

    return {
        'computable': True,
        'T1_us': T1_us,
        'T2_us': T2_us,
        't2_assumed': t2_assumed,
        'gate_time_ns': gate_time_ns,
        'gate_time_us': gate_time_us,
        'epsilon_T1': epsilon_T1,
        'epsilon_T2': epsilon_T2,
        'epsilon_control': epsilon_control_baseline,
        'epsilon_total': epsilon_total,
        'derived_fidelity_pct': derived_fidelity_pct,
        't1_limited_fidelity_pct': t1_limited_fidelity_pct,
        'fractions_meaningful': fractions_meaningful,
        'T1_fraction_pct': T1_fraction_pct,
        'T2_fraction_pct': T2_fraction_pct,
        'control_fraction_pct': control_fraction_pct,
        'measured_fields': measured_fields,
        'assumed_fields': assumed_fields,
        'assumptions': assumptions,
    }


def estimate(analysis: AnalysisResult,
             profile_path: str = None,
             profile_overrides: Optional[dict] = None,
             verbose: bool = True,
             ir=None,
             profile: Optional[dict] = None,
             epsilon_control_baseline: Optional[float] = None) -> EstimationResult:
    """
    Run Stage 3 estimation: translate logical analysis into physical resources.

    This is the single-module (Tier 1) estimator. It computes:
      - Code distance from gate fidelity
      - Physical qubits per logical qubit (2d² - 1)
      - Total physical qubit count (computation + factory)

    Modular overhead (Tier 2) is not computed here.
    See estimator_tier2_modular.py for the preserved Tier 2 functions.
    """
    if verbose:
        print(f"Estimating resources for: {analysis.source_file}")
        print(f"Hardware profile: {profile_path}")

    # --- Load hardware profile ---
    if profile is None:
        profile = load_profile(legacy_path=profile_path, overrides=profile_overrides)

    # --- Step 0: Derive control error baseline from profile ---
    # ε_control must be derived from the UNMODIFIED profile (before T1/T2 slider overrides).
    # If run_estimation pre-computed it from the clean profile, use that value.
    # Otherwise fall back to deriving it from whatever profile we have.
    if epsilon_control_baseline is None:
        epsilon_control_baseline = _derive_control_error_baseline(profile)

    # --- Compute coherence budget (forward: T1, T2 → fidelity) ---
    # T1 and T2 are the primary material inputs. Gate fidelity is derived.
    # T2 = 2*T1 fallback applied automatically if T2 missing from profile.
    coherence_budget = _compute_coherence_budget(profile, epsilon_control_baseline)

    # --- Extract key parameters from profile ---
    # Fidelity is now DERIVED from T1/T2/gate_time, not taken from profile directly.
    derived_fidelity_pct = coherence_budget['derived_fidelity_pct']
    t1_limited_fidelity_pct = coherence_budget['t1_limited_fidelity_pct']

    two_qubit_fidelity  = derived_fidelity_pct / 100.0
    physical_error_rate = 1.0 - two_qubit_fidelity
    threshold = profile['error_correction']['threshold']

    # --- Derive per-gate target logical error rate from circuit depth ---
    # A circuit of depth D succeeds with probability (1 - LER_per_gate)^D ≥ success_rate
    # → LER_per_gate ≤ 1 - success_rate^(1/D)
    # Falls back to profile target if depth is 0 or 1 (degenerate cases)
    target_circuit_success_rate = profile.get('target_circuit_success_rate', 0.99)
    circuit_depth = analysis.circuit_depth
    if circuit_depth > 1:
        target_logical_error_rate = 1.0 - (target_circuit_success_rate ** (1.0 / circuit_depth))
    else:
        # Depth 0 or 1 — fall back to profile value
        target_logical_error_rate = profile['error_correction']['target_logical_error_rate']

    # --- Step 1: Compute code distance ---
    code_distance, logical_error_rate_achieved = _compute_code_distance(
        physical_error_rate,
        target_logical_error_rate,
        threshold
    )
    physical_qubits_per_logical = 2 * (code_distance ** 2) - 1

    # --- Step 2: Compute computation qubit count ---
    num_logical_qubits = analysis.graph.number_of_nodes()
    computation_qubits = num_logical_qubits * physical_qubits_per_logical

    # --- Step 3: Count T gates and estimate magic state factories ---
    num_t_gates = 0  # TODO: wire T gate count through from parser/analyzer
    num_factories, qubits_per_factory, factory_qubits = _estimate_magic_state_factories(
        num_t_gates, profile
    )

    # --- Step 4-6: Modular overhead (Tier 2) — not computed in this estimator ---
    # Module count, inter-module operations, communication qubits, purification rounds
    # are set to None. See estimator_tier2_modular.py for the preserved functions.
    # To reconnect: import and call assign_modules_greedy, count_intermodule_operations,
    # extract_interconnect_params from estimator_tier2_modular, then populate the
    # Optional fields in EstimationResult below.

    # --- Step 7: Total physical qubits (Tier 1: computation + factory only) ---
    total_physical_qubits = computation_qubits + factory_qubits

    # --- Step 8: Feasibility check ---
    feasibility_notes = []
    feasible = True

    if physical_error_rate >= threshold:
        feasible = False
        feasibility_notes.append(
            f"Physical error rate ({physical_error_rate:.3f}) exceeds "
            f"surface code threshold ({threshold}). Error correction cannot help."
        )

    if feasible and not feasibility_notes:
        feasibility_notes.append("Physical error rate within correctable regime.")

    # Propagate any coherence budget assumptions into feasibility notes
    for note in coherence_budget.get('assumptions', []):
        feasibility_notes.append(note)

    # --- Assumptions ---
    assumptions = [
        f"Gate fidelity derived from materials: T1={coherence_budget['T1_us']:.0f} µs, "
        f"T2={coherence_budget['T2_us']:.0f} µs, gate_time={coherence_budget['gate_time_ns']:.0f} ns "
        f"→ derived fidelity {derived_fidelity_pct:.3f}%.",
        f"Control error baseline ε_ctrl={epsilon_control_baseline*100:.4f}% fixed from profile "
        f"(pulse errors, leakage, calibration — not materials-dependent).",
        "Perfect intra-module connectivity assumed (no SWAP routing overhead). "
        "Physical qubit count is a lower bound on total system size.",
        "Surface code analytical approximation used (not full Stim simulation).",
        "T gate count is placeholder (0) — magic state factory costs will be "
        "underestimated for T-gate-heavy circuits.",
        "Modular overhead (Tier 2) not modeled — single-module estimator only.",
    ]

    result = EstimationResult(
        source_file=analysis.source_file,
        platform=profile['platform'],
        circuit_depth=circuit_depth,
        target_circuit_success_rate=target_circuit_success_rate,
        target_logical_error_rate=target_logical_error_rate,
        physical_error_rate=physical_error_rate,
        code_distance=code_distance,
        logical_error_rate_achieved=logical_error_rate_achieved,
        num_logical_qubits=num_logical_qubits,
        physical_qubits_per_logical=physical_qubits_per_logical,
        computation_qubits=computation_qubits,
        num_t_gates=num_t_gates,
        num_factories_needed=num_factories,
        factory_qubits=factory_qubits,
        qubits_per_factory=qubits_per_factory,
        total_physical_qubits=total_physical_qubits,
        # Coherence budget (forward: T1/T2 → fidelity)
        t1_limited_fidelity_pct=t1_limited_fidelity_pct,
        effective_two_qubit_fidelity_pct=derived_fidelity_pct,
        coherence_budget=coherence_budget,
        # Tier 2 fields — not yet active
        physical_qubits_per_module=None,
        num_modules=None,
        num_intermodule_operations=None,
        intermodule_fraction=None,
        purification_rounds=None,
        fidelity_after_purification_pct=None,
        effective_gate_time_us=None,
        inter_module_slowdown_factor=None,
        comm_qubits_per_link=None,
        comm_qubits_total=None,
        feasible=feasible,
        feasibility_notes=feasibility_notes,
        assumptions=assumptions,
        num_single_qubit_gates=ir.num_single_qubit_gates if ir else 0,
        num_two_qubit_gates_circuit=ir.num_two_qubit_gates if ir else 0,
        num_measurements=ir.num_measurements if ir else 0,
        locality_score=analysis.locality_score,
        hub_qubits=analysis.hub_qubits,
    )

    if verbose:
        print("Done.")
        print()
        print(result.summary())
    return result


def run_estimation(
    circuit_path: str,
    profile_path: str = None,
    profile_overrides: Optional[dict] = None,
    verbose: bool = False,
    profiles_dir: str = None,
    qubits: str = None,
    interconnect: str = None,
    module: str = None,
    error_correction: str = None,
) -> EstimationResult:
    """
    Convenience wrapper: run the full pipeline (parse → analyze → estimate)
    from file paths alone. This is the primary entry point for serve.py.

    Two calling modes:

    Legacy (single yaml — CLI and backward compatibility):
        result = run_estimation(
            "data/circuits/test_circuit.qasm",
            "src/qrem/hardware_profiles/superconducting.yaml",
        )

    Modular (component profiles — currently only qubits + error_correction active;
    interconnect and module are accepted for forward compatibility but not used):
        result = run_estimation(
            "data/circuits/test_circuit.qasm",
            profiles_dir="src/qrem/hardware_profiles",
            qubits="transmon_baseline_2026",
            error_correction="surface_code_1e6",
        )
    """
    from parser import parse_qasm
    from analyzer import analyze

    if profile_path:
        # Load clean profile (no overrides) to derive stable ε_ctrl baseline
        clean_profile = load_profile(legacy_path=profile_path)
        profile = load_profile(legacy_path=profile_path, overrides=profile_overrides)
    elif profiles_dir:
        # Load clean profile (no overrides) to derive stable ε_ctrl baseline
        clean_profile = load_profile(
            profiles_dir=profiles_dir,
            qubits=qubits,
            interconnect=interconnect,
            module=module,
            error_correction=error_correction,
        )
        profile = load_profile(
            profiles_dir=profiles_dir,
            qubits=qubits,
            interconnect=interconnect,
            module=module,
            error_correction=error_correction,
            overrides=profile_overrides,
        )
    else:
        raise ValueError("Must provide either profile_path or profiles_dir + component names")

    ir = parse_qasm(circuit_path)
    analysis = analyze(ir)
    return estimate(analysis, profile_path=None, profile=profile,
                    verbose=verbose, ir=ir,
                    epsilon_control_baseline=_derive_control_error_baseline(clean_profile))


# --- Allow running this file directly as a quick test ---
if __name__ == "__main__":
    import sys
    from parser import parse_qasm
    from analyzer import analyze

    if len(sys.argv) < 3:
        print("Usage: python3 estimator.py <circuit.qasm> <hardware_profile.yaml>")
        sys.exit(1)

    ir = parse_qasm(sys.argv[1])
    print()
    analysis = analyze(ir)
    print()
    result = estimate(analysis, sys.argv[2])
