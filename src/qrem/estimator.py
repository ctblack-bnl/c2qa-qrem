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
#   - T gate / magic state factory estimate
#   - Feasibility assessment
#
# Key simplifying assumptions (documented honestly):
#   1. Perfect intra-module connectivity assumed (no SWAP routing overhead)
#   2. Simplified surface code analytical formula (not full Stim simulation)
#   3. Simple greedy module assignment (not optimal partitioning)
#   4. Magic state factory cost uses standard distillation overhead estimate
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
    physical_error_rate: float        # derived from two-qubit gate fidelity
    code_distance: int                # smallest odd d achieving target logical error rate
    logical_error_rate_achieved: float # what logical error rate we actually achieve

    # --- Physical qubit counts ---
    num_logical_qubits: int           # from the circuit
    physical_qubits_per_logical: int  # = 2d² - 1
    computation_qubits: int           # logical qubits * physical_qubits_per_logical

    # --- T gate / magic state factories ---
    num_t_gates: int                  # T gates in the circuit (from analyzer)
    num_factories_needed: int         # how many magic state factories required
    factory_qubits: int               # physical qubits consumed by factories
    qubits_per_factory: int           # physical qubits per factory (from profile)

    # --- Total physical qubits ---
    total_physical_qubits: int        # computation + factory qubits

    # --- Module assignment ---
    physical_qubits_per_module: int   # from hardware profile
    num_modules: int                  # ceil(total_physical_qubits / qubits_per_module)

    # --- Inter-module operations ---
    num_intermodule_operations: int   # two-qubit gates that cross module boundaries
    intermodule_fraction: float       # fraction of two-qubit gates that are inter-module

    # --- Feasibility ---
    feasible: bool                    # can the computation run within coherence budget?
    feasibility_notes: List[str]      # human-readable explanation of any issues

    # --- Circuit analysis (from Stage 2) ---
    num_single_qubit_gates: int = 0
    num_two_qubit_gates_circuit: int = 0  # renamed to avoid clash with two_qubit gate fidelity
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
        lines.append("--- Feasibility ---")
        lines.append(f"  Feasible                 : {'YES' if self.feasible else 'NO'}")
        for note in self.feasibility_notes:
            lines.append(f"  Note: {note}")
        lines.append("")
        lines.append("--- Assumptions ---")
        for assumption in self.assumptions:
            lines.append(f"  * {assumption}")
        return "\n".join(lines)


def _load_profile(profile_path: str) -> dict:
    """Load a hardware profile yaml file."""
    with open(profile_path, 'r') as f:
        return yaml.safe_load(f)


def _apply_overrides(profile: dict, overrides: dict) -> dict:
    """
    Apply a nested override dict to a profile dict.
    Merges one level deep — sufficient for all current profile parameters.

    Example:
        overrides = {"gates": {"two_qubit_fidelity_pct": 99.9}}
        will update profile["gates"]["two_qubit_fidelity_pct"] without
        touching other keys inside profile["gates"].
    """
    import copy
    profile = copy.deepcopy(profile)
    for section, values in overrides.items():
        if isinstance(values, dict) and section in profile:
            profile[section].update(values)
        else:
            profile[section] = values
    return profile


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
    # If physical error rate is above threshold, error correction makes things worse
    if physical_error_rate >= threshold:
        return 1, physical_error_rate

    # Search for the smallest odd d that achieves our target
    for d in range(3, 100, 2):  # odd integers starting at 3
        ratio = physical_error_rate / threshold
        logical_error_rate = ratio ** ((d + 1) / 2)
        if logical_error_rate <= target_logical_error_rate:
            return d, logical_error_rate

    # If we get here, even d=99 wasn't enough — hardware is too noisy
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
    """
    # How many logical qubits fit in one module?
    # IMPORTANT: if one logical qubit needs more physical qubits than the module holds,
    # each logical qubit gets its own module (we cannot split a logical qubit across modules).
    logical_qubits_per_module = physical_qubits_per_module // physical_qubits_per_logical

    # Process hub qubits first, then remaining qubits
    ordered_qubits = analysis.hub_qubits.copy()
    for q in analysis.graph.nodes():
        if q not in ordered_qubits:
            ordered_qubits.append(q)

    # Assign qubits to modules greedily
    assignment = {}
    current_module = 0

    if logical_qubits_per_module == 0:
        # Each logical qubit needs more than one module worth of physical qubits.
        # In this regime, assign each logical qubit its own module.
        # Future: model multi-module logical qubits properly.
        for qubit in ordered_qubits:
            assignment[qubit] = current_module
            current_module += 1
    else:
        # Pack logical qubits into modules, keeping hubs together where possible
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
            # This pair is on different modules — all their interactions are inter-module
            intermodule_count += data['weight']
    return intermodule_count


def _estimate_magic_state_factories(num_t_gates: int,
                                    profile: dict) -> Tuple[int, int, int]:
    """
    Estimate the number of magic state factories needed and their qubit cost.

    For now uses a simple rule of thumb:
      - If no T gates: no factories needed
      - If T gates present: need at least 1 factory
      - Each factory produces roughly 1 magic state per error correction cycle
      - We assume 1 factory is sufficient for small circuits
        (a more sophisticated model would account for T gate rate vs factory rate)

    Returns (num_factories, qubits_per_factory, total_factory_qubits)
    """
    if num_t_gates == 0:
        return 0, 0, 0

    # Get factory qubit cost from profile, or use standard estimate
    qubits_per_factory = profile.get('magic_state_factory', {}).get(
        'qubits_per_factory', 1000
    )

    # Simple rule: 1 factory for small circuits
    # Future: scale with T gate rate vs factory production rate
    num_factories = 1

    return num_factories, qubits_per_factory, num_factories * qubits_per_factory


def estimate(analysis: AnalysisResult,
             profile_path: str,
             profile_overrides: Optional[dict] = None,
             verbose: bool = True,
             ir=None) -> EstimationResult:
    """
    Run Stage 3 estimation: translate logical analysis into physical resources.

    Args:
        analysis:          AnalysisResult from Stage 2
        profile_path:      path to a hardware profile yaml file
        profile_overrides: optional dict of parameter overrides applied after
                           loading the profile. Merged one level deep. Example:
                           {"gates": {"two_qubit_fidelity_pct": 99.5}}
                           This allows the UI/server to vary parameters without
                           editing the yaml file.
        verbose:           if True (default), print progress and summary to stdout.
                           Set to False when calling programmatically from serve.py
                           to keep server logs clean.

    Returns:
        EstimationResult with full physical resource breakdown
    """
    if verbose:
        print(f"Estimating resources for: {analysis.source_file}")
        print(f"Hardware profile: {profile_path}")

    # --- Load hardware profile ---
    profile = _load_profile(profile_path)

    # --- Apply any parameter overrides (e.g. from UI slider) ---
    if profile_overrides:
        profile = _apply_overrides(profile, profile_overrides)

    # --- Extract key parameters from profile ---
    two_qubit_fidelity = profile['gates']['two_qubit_fidelity_pct'] / 100.0
    physical_error_rate = 1.0 - two_qubit_fidelity

    target_logical_error_rate = profile['error_correction']['target_logical_error_rate']
    threshold = profile['error_correction']['threshold']
    physical_qubits_per_module = profile['module']['physical_qubits_per_module']

    # --- Step 1: Compute code distance ---
    code_distance, logical_error_rate_achieved = _compute_code_distance(
        physical_error_rate,
        target_logical_error_rate,
        threshold
    )
    # Correct surface code formula: 2d² - 1
    # A d×d surface code needs d² data qubits plus (d²-1) ancilla qubits
    # for syndrome measurements -- giving 2d²-1 total physical qubits per logical qubit.
    physical_qubits_per_logical = 2 * (code_distance ** 2) - 1

    # --- Step 2: Compute computation qubit count ---
    num_logical_qubits = analysis.graph.number_of_nodes()
    computation_qubits = num_logical_qubits * physical_qubits_per_logical

    # --- Step 3: Count T gates and estimate magic state factories ---
    # Count T gates from the interaction graph's source circuit
    # We look for 't' gates in the analysis (passed through from parser)
    # For now we track this through the gate list stored in the IR
    # Note: analyzer doesn't currently pass T gate count — we'll add this
    # as a field in a future refinement. For now we use 0 as placeholder.
    num_t_gates = 0  # TODO: pass T gate count through from parser/analyzer

    num_factories, qubits_per_factory, factory_qubits = _estimate_magic_state_factories(
        num_t_gates, profile
    )

    # --- Step 4: Total physical qubits ---
    total_physical_qubits = computation_qubits + factory_qubits

    # --- Step 5: Module assignment and count ---
    module_assignment = _assign_modules_greedy(
        analysis,
        physical_qubits_per_logical,
        physical_qubits_per_module
    )
    # Module count = total physical qubits / qubits per module, rounded up.
    # This is the authoritative calculation — the greedy assignment is used
    # for inter-module operation counting, not for the module count itself.
    num_modules = math.ceil(total_physical_qubits / physical_qubits_per_module)

    # --- Step 6: Count inter-module operations ---
    num_intermodule = _count_intermodule_operations(analysis, module_assignment)
    total_two_qubit = sum(
        data['weight'] for _, _, data in analysis.graph.edges(data=True)
    )
    intermodule_fraction = num_intermodule / total_two_qubit if total_two_qubit > 0 else 0.0

    # --- Step 7: Feasibility check ---
    feasibility_notes = []
    feasible = True

    # Check: are we above the error correction threshold?
    if physical_error_rate >= threshold:
        feasible = False
        feasibility_notes.append(
            f"Physical error rate ({physical_error_rate:.3f}) exceeds "
            f"surface code threshold ({threshold}). Error correction cannot help."
        )

    # Check: is the inter-module link fidelity above threshold?
    link_fidelity = profile['intermodule']['link_fidelity_pct'] / 100.0
    link_error_rate = 1.0 - link_fidelity
    if link_error_rate >= threshold:
        feasibility_notes.append(
            f"Inter-module link error rate ({link_error_rate:.3f}) exceeds threshold. "
            f"Inter-module operations may not be correctable without additional overhead."
        )

    if feasible and not feasibility_notes:
        feasibility_notes.append("All parameters within correctable regime.")

    # --- Assumptions ---
    assumptions = [
        "Perfect intra-module connectivity assumed (no SWAP routing overhead).",
        "Surface code analytical approximation used (not full Stim simulation).",
        "Greedy module assignment used (not optimal graph partitioning).",
        "T gate count is placeholder (0) — will be wired through from parser in next phase.",
        "Magic state factory cost uses standard 1000-qubit-per-factory estimate.",
        "Inter-module link fidelity is checked for feasibility only — it does not yet affect code distance or physical qubit overhead. A rigorous model would apply higher code distance to inter-module operations.",
        "Transduction efficiency (microwave-to-optical conversion) is stored in the hardware profile but not yet used in any calculation. It affects entanglement rate and effective error accumulation during inter-module operations.",
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


def run_estimation(circuit_path: str,
                   profile_path: str,
                   profile_overrides: Optional[dict] = None,
                   verbose: bool = False) -> EstimationResult:
    """
    Convenience wrapper: run the full pipeline (parse → analyze → estimate)
    from file paths alone. This is the primary entry point for serve.py.

    Args:
        circuit_path:      path to a .qasm circuit file
        profile_path:      path to a hardware profile yaml file
        profile_overrides: optional parameter overrides (see estimate() docstring)
        verbose:           passed through to estimate(). Defaults to False here
                           since this function is primarily called from the server.

    Returns:
        EstimationResult with full physical resource breakdown

    Example:
        result = run_estimation(
            "data/circuits/test_circuit.qasm",
            "src/qrem/hardware_profiles/superconducting.yaml",
            profile_overrides={"gates": {"two_qubit_fidelity_pct": 99.5}}
        )
        print(result.to_dict())
    """
    from parser import parse_qasm
    from analyzer import analyze

    ir = parse_qasm(circuit_path)
    analysis = analyze(ir)
    return estimate(analysis, profile_path,
                   profile_overrides=profile_overrides,
                   verbose=verbose,
                   ir=ir)


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
