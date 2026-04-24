# circuit_ir.py
# Internal Representation (IR) of a parsed quantum circuit.
# This is the data structure that flows between pipeline stages.
# Stage 1 (parser) produces it. Stage 2 (analyzer) consumes it.

from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class Gate:
    """
    Represents a single gate operation in the circuit.

    Examples:
        Gate(name='cx', qubits=['data[0]', 'data[1]'], gate_type='two_qubit')
        Gate(name='h',  qubits=['ancilla[0]'],          gate_type='single_qubit')
        Gate(name='measure', qubits=['data[0]'],         gate_type='measurement')
    """
    name: str                  # gate name e.g. 'cx', 'h', 'x', 'measure'
    qubits: List[str]          # qubits this gate acts on, in order
    gate_type: str             # 'single_qubit', 'two_qubit', 'multi_qubit', 'measurement'


@dataclass
class CircuitIR:
    """
    The complete internal representation of a parsed quantum circuit.
    Produced by Stage 1 (parser), consumed by all downstream stages.
    """
    # --- Provenance ---
    source_file: str           # path to the original .qasm file

    # --- Qubit inventory ---
    qubits: List[str]          # all qubit names e.g. ['data[0]', 'data[1]', 'ancilla[0]']
    num_qubits: int            # total qubit count

    # --- Gate sequence ---
    gates: List[Gate]          # all gates in circuit order

    # --- Summary counts (derived from gates, for convenience) ---
    num_single_qubit_gates: int = 0
    num_two_qubit_gates: int   = 0
    num_multi_qubit_gates: int = 0
    num_measurements: int      = 0

    def summary(self) -> str:
        """Returns a human-readable summary of the circuit."""
        return (
            f"Circuit: {self.source_file}\n"
            f"  Qubits          : {self.num_qubits}\n"
            f"  Single-qubit gates : {self.num_single_qubit_gates}\n"
            f"  Two-qubit gates    : {self.num_two_qubit_gates}\n"
            f"  Multi-qubit gates  : {self.num_multi_qubit_gates}\n"
            f"  Measurements       : {self.num_measurements}\n"
            f"  Total gates        : {len(self.gates)}\n"
        )
