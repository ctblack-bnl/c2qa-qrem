# analyzer.py
# Stage 2 of the QREM pipeline: Analyze circuit structure.
#
# Takes a CircuitIR (from Stage 1) and produces an AnalysisResult containing:
#   - The qubit interaction graph (which qubits talk to each other, how often)
#   - Interaction counts per qubit pair
#   - Hub qubits (most connected)
#   - A locality score (are interactions concentrated or spread out?)
#
# Usage:
#   from qrem.parser import parse_qasm
#   from qrem.analyzer import analyze
#   ir = parse_qasm("data/circuits/test_circuit.qasm")
#   result = analyze(ir)
#   print(result.summary())

import networkx as nx
from dataclasses import dataclass, field
from typing import List, Tuple, Dict
from circuit_ir import CircuitIR


def compute_circuit_depth(ir: CircuitIR) -> int:
    """
    Compute circuit depth via critical path traversal.

    Tracks the accumulated depth at each qubit as we walk the gate list
    in order. For each gate, its depth = max(depth of its qubits) + 1.
    Circuit depth = the maximum qubit depth at the end.

    Measurements are included — they are real time-consuming operations
    and nothing on that qubit can proceed until they complete.
    This matches Qiskit's convention.
    """
    qubit_depth = {q: 0 for q in ir.qubits}
    for gate in ir.gates:
        depth_here = max(qubit_depth[q] for q in gate.qubits) + 1
        for q in gate.qubits:
            qubit_depth[q] = depth_here
    return max(qubit_depth.values()) if qubit_depth else 0


@dataclass
class AnalysisResult:
    """
    The output of Stage 2 analysis.
    Consumed by Stage 3 (model) and Stage 4 (estimator).
    """
    # --- Provenance ---
    source_file: str

    # --- Circuit depth ---
    # Length of the critical path through the gate dependency graph.
    # Sets the per-gate logical error rate target in Stage 3.
    circuit_depth: int

    # --- The interaction graph ---
    # Nodes = qubits, Edges = interactions, Edge weight = number of interactions
    graph: nx.Graph

    # --- Interaction pairs ---
    # List of (qubit_a, qubit_b, count) sorted by count descending
    interaction_pairs: List[Tuple[str, str, int]]

    # --- Per-qubit interaction counts ---
    # How many total two-qubit gate interactions each qubit participates in
    qubit_interaction_counts: Dict[str, int]

    # --- Hub qubits ---
    # Qubits with the most interactions — these are expensive to place across module boundaries
    hub_qubits: List[str]

    # --- Locality score ---
    # A number between 0 and 1.
    # High (close to 1): the same qubit pairs interact repeatedly — good for modular architectures
    # Low (close to 0): interactions are spread broadly across many different pairs — harder to partition
    locality_score: float

    def summary(self) -> str:
        lines = []
        lines.append(f"Analysis: {self.source_file}")
        lines.append(f"  Circuit depth       : {self.circuit_depth}")
        lines.append(f"  Qubits in graph     : {self.graph.number_of_nodes()}")
        lines.append(f"  Interacting pairs   : {self.graph.number_of_edges()}")
        lines.append(f"  Locality score      : {self.locality_score:.2f}  (1.0 = very local, 0.0 = very spread)")
        lines.append("")
        lines.append("  Qubit interaction pairs (sorted by frequency):")
        for a, b, count in self.interaction_pairs:
            lines.append(f"    {a:15s} <-> {b:15s} : {count} interaction(s)")
        lines.append("")
        lines.append("  Per-qubit interaction count:")
        for qubit, count in sorted(self.qubit_interaction_counts.items(), key=lambda x: -x[1]):
            hub_marker = "  << hub" if qubit in self.hub_qubits else ""
            lines.append(f"    {qubit:15s} : {count} total{hub_marker}")
        return "\n".join(lines)


def analyze(ir: CircuitIR) -> AnalysisResult:
    """
    Analyze a CircuitIR and return an AnalysisResult.

    Args:
        ir: the CircuitIR produced by Stage 1 (parser)

    Returns:
        AnalysisResult with interaction graph and derived metrics
    """
    print(f"Analyzing: {ir.source_file}")

    # --- Compute circuit depth ---
    circuit_depth = compute_circuit_depth(ir)

    # --- Build the interaction graph ---
    # Start with an empty graph and add all qubits as nodes
    graph = nx.Graph()
    for qubit in ir.qubits:
        graph.add_node(qubit)

    # Walk through every two-qubit gate and add or increment an edge
    for gate in ir.gates:
        if gate.gate_type == 'two_qubit':
            a, b = gate.qubits[0], gate.qubits[1]
            # Use graph.get_edge_data() which handles both (a,b) and (b,a) orderings
            edge_data = graph.get_edge_data(a, b)
            if edge_data is not None:
                # Already seen this pair — increment the weight
                graph[a][b]['weight'] += 1
            else:
                # First time seeing this pair — create the edge
                graph.add_edge(a, b, weight=1)

    # --- Extract interaction pairs as a sorted list ---
    interaction_pairs = []
    for a, b, data in graph.edges(data=True):
        interaction_pairs.append((a, b, data['weight']))
    interaction_pairs.sort(key=lambda x: -x[2])  # sort by count, highest first

    # --- Compute per-qubit interaction counts ---
    qubit_interaction_counts = {qubit: 0 for qubit in ir.qubits}
    for gate in ir.gates:
        if gate.gate_type == 'two_qubit':
            for qubit in gate.qubits:
                qubit_interaction_counts[qubit] += 1

    # --- Identify hub qubits ---
    # Define hubs as qubits with above-average interaction counts
    if qubit_interaction_counts:
        avg = sum(qubit_interaction_counts.values()) / len(qubit_interaction_counts)
        hub_qubits = [q for q, count in qubit_interaction_counts.items() if count > avg]
        hub_qubits.sort(key=lambda q: -qubit_interaction_counts[q])
    else:
        hub_qubits = []

    # --- Compute locality score ---
    # Locality = (total interactions) / (number of unique interacting pairs)
    # If the same pairs interact repeatedly, this ratio is high (local)
    # If every interaction is between a different pair, this ratio is 1.0 (maximally spread)
    # We normalize to 0-1 by comparing against the maximum possible weight
    total_interactions = sum(d['weight'] for _, _, d in graph.edges(data=True))
    num_pairs = graph.number_of_edges()

    if num_pairs == 0:
        locality_score = 0.0
    elif total_interactions == num_pairs:
        # Every pair interacts exactly once — maximally spread
        locality_score = 0.0
    else:
        # Some pairs interact more than once — compute how concentrated that is
        max_weight = max(d['weight'] for _, _, d in graph.edges(data=True))
        locality_score = (total_interactions - num_pairs) / (total_interactions * (1 - 1/max_weight) + 1e-9)
        locality_score = min(1.0, max(0.0, locality_score))

    result = AnalysisResult(
        source_file=ir.source_file,
        circuit_depth=circuit_depth,
        graph=graph,
        interaction_pairs=interaction_pairs,
        qubit_interaction_counts=qubit_interaction_counts,
        hub_qubits=hub_qubits,
        locality_score=locality_score,
    )

    print("Done.")
    print(result.summary())
    return result


# --- Allow running this file directly as a quick test ---
if __name__ == "__main__":
    import sys
    from parser import parse_qasm

    if len(sys.argv) < 2:
        print("Usage: python3 analyzer.py <path_to_circuit.qasm>")
        sys.exit(1)

    ir = parse_qasm(sys.argv[1])
    print()
    result = analyze(ir)
