# estimator_tier2_modular.py
# Tier 2 — Modular overhead estimation functions.
#
# These functions were part of estimator.py (Stage 3) and have been separated
# here during the April 2026 rescoping of Baby QREM to a single-module estimator.
# They are preserved intact and are NOT currently called by the active pipeline.
#
# When to re-activate:
#   - Module count and inter-module overhead are a Center-wide research problem
#     involving computer scientists, algorithms, and error correction teams.
#   - When that work matures, import these functions back into estimator.py
#     and re-add Steps 4-6 to the estimate() function.
#   - The EstimationResult fields for Tier 2 (num_modules, num_intermodule_operations,
#     intermodule_fraction, purification_rounds, fidelity_after_purification_pct,
#     effective_gate_time_us, inter_module_slowdown_factor, comm_qubits_per_link,
#     comm_qubits_total) are already declared as Optional in EstimationResult
#     and will accept real values when this layer is reconnected.
#
# The three interconnect profile YAMLs (microwave_photonic_85pct.yaml,
# microwave_photonic_92pct.yaml, microwave_photonic_99pct.yaml) and the
# module profile YAML (module_1000q_nearest_neighbor.yaml) are also preserved
# exactly as-is in hardware_profiles/ — they encode real design decisions
# about purification tiers and should not be deleted.
#
# Preserved from estimator.py — April 28, 2026.

import math
from typing import Dict, Tuple
from analyzer import AnalysisResult


def assign_modules_greedy(analysis: AnalysisResult,
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


def count_intermodule_operations(analysis: AnalysisResult,
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


def extract_interconnect_params(profile: dict, local_gate_time_ns: float) -> dict:
    """
    Extract and derive interconnect parameters from the profile.
    Falls back to safe defaults if fields are missing (e.g. legacy profiles).

    Returns a dict with all interconnect values the estimator needs:
      link_fidelity_pct, purification_rounds, fidelity_after_purification_pct,
      effective_gate_time_us, inter_module_slowdown_factor, comm_qubits_per_link

    Purification model (DEJMPS protocol, idealized):
      85% raw fidelity → 2 rounds → 99.7% effective, 5,200× slowdown vs local gate
      92% raw fidelity → 1 round  → 99.3% effective, 1,100× slowdown
      99% raw fidelity → 0 rounds → direct use,      550×  slowdown
    Even at 99% raw, the 550× slowdown floor cannot be eliminated with
    current photonic approaches — fundamental Bell pair generation latency.
    """
    imc = profile.get('intermodule', {})

    # Raw link parameters
    link_fidelity_pct = imc.get('link_fidelity_pct', 85.0)
    entanglement_rate_hz = imc.get('entanglement_rate_Hz', 1000)

    # Purification model — use profile values if present, else derive
    purification_rounds = imc.get('purification_rounds', 0)
    purification_latency_us = imc.get('purification_latency_us', 0)
    fidelity_after_purification_pct = imc.get(
        'fidelity_after_purification_pct', link_fidelity_pct
    )

    # Effective parameters — use profile values if present, else derive
    bell_pair_time_us = 1_000_000.0 / entanglement_rate_hz
    derived_gate_time_us = bell_pair_time_us + purification_latency_us
    local_gate_time_us = local_gate_time_ns / 1000.0
    derived_slowdown = int(round(derived_gate_time_us / local_gate_time_us))

    effective_gate_time_us = imc.get('effective_gate_time_us', derived_gate_time_us)
    inter_module_slowdown_factor = imc.get('inter_module_slowdown_factor', derived_slowdown)

    # Communication qubit overhead
    comm_qubits_per_link = imc.get('communication_qubits_per_link', 0)

    return {
        'link_fidelity_pct':               link_fidelity_pct,
        'purification_rounds':             purification_rounds,
        'fidelity_after_purification_pct': fidelity_after_purification_pct,
        'effective_gate_time_us':          effective_gate_time_us,
        'inter_module_slowdown_factor':    inter_module_slowdown_factor,
        'comm_qubits_per_link':            comm_qubits_per_link,
    }
