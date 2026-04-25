# estimator.py
# Stage 3 of the QREM pipeline: Translate logical circuit analysis into
# physical resource requirements for a given hardware platform.
#
# Takes:
#   - AnalysisResult from Stage 2 (the interaction graph and circuit metrics)
#   - A hardware profile (loaded from a yaml file)
#
# Produces:
#   - Physical qubit count (including error correction overhead)
#   - Code distance (how large the surface code needs to be)
#   - Module count (how many modules are needed)
#   - Inter-module operation count (how many cross-module interactions)
#   - Inter-module runtime cost (slowdown factor, effective gate time)
#   - Communication qubit overhead (physical qubits reserved for purification)
#   - T gate / magic state factory estimate
#   - Feasibility assessment
#
# Key simplifying assumptions (documented honestly):
#   1. Perfect intra-module connectivity assumed (no SWAP routing overhead)
#   2. Simplified surface code analytical formula (not full Stim simulation)
#   3. Simple greedy module assignment (not optimal partitioning)
#   4. Magic state factory cost uses standard distillation overhead estimate
#   5. Logical qubits are assumed to fit entirely within one module
#   6. Inter-module operations modeled as runtime cost only (lattice surgery
#      framing — QEC does not cross module boundaries)
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
    """
    # --- Provenance ---
    source_file: str
    platform: str

    # --- Error correction ---
    physical_error_rate: float          # derived from two-qubit gate fidelity
    code_distance: int                  # smallest odd d achieving target logical error rate
    logical_error_rate_achieved: float  # what logical error rate we actually achieve

    # --- Physical qubit counts ---
    num_logical_qubits: int             # from the circuit
    physical_qubits_per_logical: int    # = 2d² - 1
    computation_qubits: int             # logical qubits * physical_qubits_per_logical

    # --- T gate / magic state factories ---
    num_t_gates: int                    # T gates in the circuit (from analyzer)
    num_factories_needed: int           # how many magic state factories required
    factory_qubits: int                 # physical qubits consumed by factories
    qubits_per_factory: int             # physical qubits per factory (from profile)

    # --- Total physical qubits ---
    total_physical_qubits: int          # computation + factory + communication qubits

    # --- Module assignment ---
    physical_qubits_per_module: int     # from hardware profile
    num_modules: int                    # ceil(total_physical_qubits / qubits_per_module)

    # --- Inter-module operations ---
    num_intermodule_operations: int     # two-qubit gates that cross module boundaries
    intermodule_fraction: float         # fraction of two-qubit gates that are inter-module

    # --- Inter-module link characteristics (new) ---
    # These come from the interconnect profile effective parameters.
    # They reflect post-purification values — what the QEC layer actually sees.
    purification_rounds: int            # rounds of entanglement purification required
    fidelity_after_purification_pct: float  # effective link fidelity after purification
    effective_gate_time_us: float       # effective inter-module gate time after purification
    inter_module_slowdown_factor: int   # effective_gate_time / local_gate_time
                                        # = runtime cost of one inter-module gate
                                        # in units of local two-qubit gates
    comm_qubits_per_link: int           # physical qubits reserved per link for purification
    comm_qubits_total: int              # total communication qubits across all links

    # --- Feasibility ---
    feasible: bool                      # can the computation run within coherence budget?
    feasibility_notes: List[str]        # human-readable explanation of any issues

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
        All fields are basic Python types (int, float, bool, str, list)
        so dataclasses.asdict() handles this directly.
        """
        return dataclasses.asdict(self)

    def summary(self) -> str:
        lines = []
        lines.append(f"Resource Estimation: {self.source_file}")
        lines.append(f"Platform: {self.platform}")
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
        lines.append(f"  Communication qubits     : {self.comm_qubits_total} ({self.comm_qubits_per_link}/link × {self.num_modules - 1} links)")
        lines.append(f"  T gates in circuit       : {self.num_t_gates}")
        lines.append(f"  Magic state factories    : {self.num_factories_needed}")
        lines.append(f"  Factory qubits           : {self.factory_qubits}")
        lines.append(f"  TOTAL physical qubits    : {self.total_physical_qubits}")
        lines.append("")
        lines.append("--- Module Architecture ---")
        lines.append(f"  Qubits per module        : {self.physical_qubits_per_module}")
        lines.append(f"  Modules needed           : {self.num_modules}")
        lines.append(f"  Inter-module operations  : {self.num_intermodule_operations} ({self.intermodule_fraction*100:.1f}% of two-qubit gates)")
        lines.append("")
        lines.append("--- Inter-Module Link ---")
        lines.append(f"  Purification rounds      : {self.purification_rounds}")
        lines.append(f"  Fidelity after purif.    : {self.fidelity_after_purification_pct:.1f}%")
        lines.append(f"  Effective gate time      : {self.effective_gate_time_us:.0f} µs")
        lines.append(f"  Slowdown factor          : {self.inter_module_slowdown_factor:,}×  (vs local 2q gate)")
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


def _assign_modules_greedy(analysis: AnalysisResult,
                           physical_qubits_per_logical: int,
                           physical_qubits_per_module: int) -> Dict[str, int]:
    """
    Assign logical qubits to modules using a simple greedy algorithm.
    Strategy: fill modules one at a time. When a module is full, start the next one.
    Tries to keep highly-interacting qubits together by processing hubs first.
    Returns a dict mapping qubit_name -> module_index.

    NOTE: This is a placeholder greedy heuristic. A more sophisticated
    graph partitioning algorithm will replace this in a future phase.
    The partitioner objective should minimize inter-module logical operations
    since each one carries a large runtime cost (slowdown factor).
    """
    logical_qubits_per_module = physical_qubits_per_module // physical_qubits_per_logical

    ordered_qubits = analysis.hub_qubits.copy()
    for q in analysis.graph.nodes():
        if q not in ordered_qubits:
            ordered_qubits.append(q)

    assignment = {}
    current_module = 0
    if logical_qubits_per_module == 0:
        for qubit in ordered_qubits:
            assignment[qubit] = current_module
            current_module += 1
    else:
        count_in_current_module = 0
        for qubit in ordered_qubits:
            assignment[qubit] = current_module
            count_in_current_module += 1
            if count_in_current_module >= logical_qubits_per_module:
                current_module += 1
                count_in_current_module = 0
    return assignment


def _count_intermodule_operations(analysis: AnalysisResult,
                                  module_assignment: Dict[str, int]) -> int:
    """
    Count how many two-qubit interactions cross module boundaries.
    Uses the interaction graph edge weights.
    """
    intermodule_count = 0
    for a, b, data in analysis.graph.edges(data=True):
        if module_assignment.get(a) != module_assignment.get(b):
            intermodule_count += data['weight']
    return intermodule_count


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


def _extract_interconnect_params(profile: dict, local_gate_time_ns: float) -> dict:
    """
    Extract and derive interconnect parameters from the profile.
    Falls back to safe defaults if fields are missing (e.g. legacy profiles).

    Returns a dict with all interconnect values the estimator needs.
    """
    imc = profile.get('intermodule', {})

    # Raw link parameters
    link_fidelity_pct = imc.get('link_fidelity_pct', 85.0)
    entanglement_rate_hz = imc.get('entanglement_rate_Hz', 1000)

    # Purification model — use profile values if present, else derive
    purification_rounds = imc.get('purification_rounds', 0)
    purification_pairs_consumed = imc.get('purification_pairs_consumed', 1)
    fidelity_after_purification_pct = imc.get(
        'fidelity_after_purification_pct', link_fidelity_pct
    )
    purification_latency_us = imc.get('purification_latency_us', 0)

    # Effective parameters — use profile values if present, else derive
    # Derivation:
    #   effective_gate_time = (1,000,000 / raw_rate) + purification_latency
    #   slowdown = effective_gate_time_us / (local_gate_time_ns / 1000)
    bell_pair_time_us = 1_000_000.0 / entanglement_rate_hz
    derived_gate_time_us = bell_pair_time_us + purification_latency_us
    local_gate_time_us = local_gate_time_ns / 1000.0
    derived_slowdown = int(round(derived_gate_time_us / local_gate_time_us))

    effective_gate_time_us = imc.get('effective_gate_time_us', derived_gate_time_us)
    inter_module_slowdown_factor = imc.get('inter_module_slowdown_factor', derived_slowdown)

    # Communication qubit overhead
    comm_qubits_per_link = imc.get('communication_qubits_per_link', 0)

    return {
        'link_fidelity_pct':              link_fidelity_pct,
        'purification_rounds':            purification_rounds,
        'fidelity_after_purification_pct': fidelity_after_purification_pct,
        'effective_gate_time_us':         effective_gate_time_us,
        'inter_module_slowdown_factor':   inter_module_slowdown_factor,
        'comm_qubits_per_link':           comm_qubits_per_link,
    }


def estimate(analysis: AnalysisResult,
             profile_path: str = None,
             profile_overrides: Optional[dict] = None,
             verbose: bool = True,
             ir=None,
             profile: Optional[dict] = None) -> EstimationResult:
    """
    Run Stage 3 estimation: translate logical analysis into physical resources.
    """
    if verbose:
        print(f"Estimating resources for: {analysis.source_file}")
        print(f"Hardware profile: {profile_path}")

    # --- Load hardware profile ---
    if profile is None:
        profile = load_profile(legacy_path=profile_path, overrides=profile_overrides)

    # --- Extract key parameters from profile ---
    two_qubit_fidelity = profile['gates']['two_qubit_fidelity_pct'] / 100.0
    physical_error_rate = 1.0 - two_qubit_fidelity
    target_logical_error_rate = profile['error_correction']['target_logical_error_rate']
    threshold = profile['error_correction']['threshold']
    physical_qubits_per_module = profile['module']['physical_qubits_per_module']
    local_gate_time_ns = profile['gates'].get('two_qubit_gate_time_ns', 200)

    # --- Extract interconnect parameters ---
    ic = _extract_interconnect_params(profile, local_gate_time_ns)

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
    num_t_gates = 0  # TODO: pass T gate count through from parser/analyzer
    num_factories, qubits_per_factory, factory_qubits = _estimate_magic_state_factories(
        num_t_gates, profile
    )

    # --- Step 4: Module assignment and count ---
    # Note: we compute modules before communication qubits because
    # num_links = num_modules - 1
    module_assignment = _assign_modules_greedy(
        analysis,
        physical_qubits_per_logical,
        physical_qubits_per_module
    )

    # --- Step 5: Count inter-module operations ---
    num_intermodule = _count_intermodule_operations(analysis, module_assignment)
    total_two_qubit = sum(
        data['weight'] for _, _, data in analysis.graph.edges(data=True)
    )
    intermodule_fraction = num_intermodule / total_two_qubit if total_two_qubit > 0 else 0.0

    # --- Step 6: Communication qubit overhead ---
    # Physical qubits reserved at module boundaries for entanglement purification.
    # Assumes a simple chain topology: num_links = num_modules - 1.
    # Small cost but real — these qubits come out of the module compute budget.
    num_modules_initial = math.ceil(
        (computation_qubits + factory_qubits) / physical_qubits_per_module
    )
    num_links = max(0, num_modules_initial - 1)
    comm_qubits_per_link = ic['comm_qubits_per_link']
    comm_qubits_total = num_links * comm_qubits_per_link

    # --- Step 7: Total physical qubits (now includes communication qubits) ---
    total_physical_qubits = computation_qubits + factory_qubits + comm_qubits_total

    # Recompute module count with communication qubits included
    num_modules = math.ceil(total_physical_qubits / physical_qubits_per_module)

    # --- Step 8: Feasibility check ---
    feasibility_notes = []
    feasible = True

    # Check 1: are we above the QEC threshold?
    if physical_error_rate >= threshold:
        feasible = False
        feasibility_notes.append(
            f"Physical error rate ({physical_error_rate:.3f}) exceeds "
            f"surface code threshold ({threshold}). Error correction cannot help."
        )

    # Check 2: inter-module slowdown — runtime cost warning
    # Note: this is NOT a hard feasibility wall. Qubits are protected by
    # continuous QEC. The cost is circuit runtime, not qubit survival.
    slowdown = ic['inter_module_slowdown_factor']
    if num_intermodule > 0:
        if slowdown >= 1000:
            feasibility_notes.append(
                f"Inter-module gates are {slowdown:,}× slower than local gates "
                f"(effective gate time: {ic['effective_gate_time_us']:.0f} µs, "
                f"{ic['purification_rounds']} purification round(s) required). "
                f"Circuit runtime dominated by inter-module operations. "
                f"Minimize inter-module gates in critical path."
            )
        elif slowdown >= 100:
            feasibility_notes.append(
                f"Inter-module gates are {slowdown:,}× slower than local gates "
                f"(effective gate time: {ic['effective_gate_time_us']:.0f} µs). "
                f"Runtime impact moderate."
            )

    if feasible and not feasibility_notes:
        feasibility_notes.append("All parameters within correctable regime.")

    # --- Assumptions ---
    assumptions = [
        "Perfect intra-module connectivity assumed (no SWAP routing overhead).",
        "Surface code analytical approximation used (not full Stim simulation).",
        "Greedy module assignment used (not optimal graph partitioning). "
        "Optimal partitioning should minimize inter-module operations, "
        "which carry large runtime cost (slowdown factor).",
        "Logical qubits assumed to fit entirely within one module. "
        "QEC does not cross module boundaries.",
        "Inter-module operations modeled as runtime cost only (lattice surgery framing). "
        "Each inter-module gate consumes purified Bell pairs and adds latency. "
        "Full circuit runtime impact requires depth analysis (Stage 4 — not yet implemented).",
        "Purification model is idealized (DEJMPS protocol, perfect local gates). "
        "Real fidelity after purification will be somewhat lower.",
        "Communication qubit count assumes chain topology (num_modules - 1 links). "
        "Real topologies may require more links.",
        "T gate count is placeholder (0) — will be wired through from parser in next phase.",
        "Magic state factory cost uses standard 1000-qubit-per-factory estimate.",
        "Transduction efficiency is stored in the hardware profile but not yet "
        "used in any calculation — affects effective entanglement rate.",
    ]

    result = EstimationResult(
        source_file=analysis.source_file,
        platform=profile['platform'],
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
        physical_qubits_per_module=physical_qubits_per_module,
        num_modules=num_modules,
        num_intermodule_operations=num_intermodule,
        intermodule_fraction=intermodule_fraction,
        purification_rounds=ic['purification_rounds'],
        fidelity_after_purification_pct=ic['fidelity_after_purification_pct'],
        effective_gate_time_us=ic['effective_gate_time_us'],
        inter_module_slowdown_factor=ic['inter_module_slowdown_factor'],
        comm_qubits_per_link=comm_qubits_per_link,
        comm_qubits_total=comm_qubits_total,
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

    Modular (four component profiles — UI dropdowns):
        result = run_estimation(
            "data/circuits/test_circuit.qasm",
            profiles_dir="src/qrem/hardware_profiles",
            qubits="transmon_baseline_2026",
            interconnect="microwave_photonic_85pct",
            module="module_1000q_nearest_neighbor",
            error_correction="surface_code_1e6",
        )
    """
    from parser import parse_qasm
    from analyzer import analyze

    if profile_path:
        profile = load_profile(legacy_path=profile_path, overrides=profile_overrides)
    elif profiles_dir:
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
                    verbose=verbose, ir=ir)


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
