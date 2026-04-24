# parser.py
# Stage 1 of the QREM pipeline: Parse a .qasm file into a CircuitIR.
#
# Usage:
#   from qrem.parser import parse_qasm
#   ir = parse_qasm("data/circuits/test_circuit.qasm")
#   print(ir.summary())

from qiskit import QuantumCircuit
from circuit_ir import CircuitIR, Gate


# Gates we treat as measurements
MEASUREMENT_GATES = {'measure'}

# Gates we treat as single-qubit
SINGLE_QUBIT_GATES = {'h', 'x', 'y', 'z', 's', 't', 'sdg', 'tdg', 'rx', 'ry', 'rz', 'u', 'u1', 'u2', 'u3'}

# Gates we treat as two-qubit
TWO_QUBIT_GATES = {'cx', 'cz', 'cy', 'swap', 'ch', 'crx', 'cry', 'crz', 'cu', 'cp', 'rzz', 'rxx'}


def parse_qasm(filepath: str) -> CircuitIR:
    """
    Read a .qasm file and return a CircuitIR.

    Args:
        filepath: path to the .qasm file

    Returns:
        CircuitIR containing all qubits and gates found in the circuit
    """
    print(f"Parsing: {filepath}")

    # --- Load the circuit using Qiskit ---
    circuit = QuantumCircuit.from_qasm_file(filepath)

    # --- Extract qubit names ---
    qubit_names = []
    for qubit in circuit.qubits:
        # Qiskit gives us register name and index — combine into readable string
        reg_name = qubit._register.name
        reg_index = qubit._index
        qubit_names.append(f"{reg_name}[{reg_index}]")

    # --- Walk through every operation in the circuit ---
    gates = []
    for instruction in circuit.data:
        op = instruction.operation
        op_qubits = instruction.qubits

        # Get the qubit names for this operation
        gate_qubits = []
        for q in op_qubits:
            reg_name = q._register.name
            reg_index = q._index
            gate_qubits.append(f"{reg_name}[{reg_index}]")

        # Classify the gate type
        op_name = op.name.lower()
        if op_name in MEASUREMENT_GATES:
            gate_type = 'measurement'
        elif op_name in SINGLE_QUBIT_GATES:
            gate_type = 'single_qubit'
        elif op_name in TWO_QUBIT_GATES:
            gate_type = 'two_qubit'
        elif len(gate_qubits) == 1:
            gate_type = 'single_qubit'   # fallback for unknown single-qubit gates
        elif len(gate_qubits) == 2:
            gate_type = 'two_qubit'       # fallback for unknown two-qubit gates
        else:
            gate_type = 'multi_qubit'

        gates.append(Gate(
            name=op_name,
            qubits=gate_qubits,
            gate_type=gate_type
        ))

    # --- Compute summary counts ---
    num_single  = sum(1 for g in gates if g.gate_type == 'single_qubit')
    num_two     = sum(1 for g in gates if g.gate_type == 'two_qubit')
    num_multi   = sum(1 for g in gates if g.gate_type == 'multi_qubit')
    num_measure = sum(1 for g in gates if g.gate_type == 'measurement')

    # --- Assemble and return the IR ---
    ir = CircuitIR(
        source_file=filepath,
        qubits=qubit_names,
        num_qubits=len(qubit_names),
        gates=gates,
        num_single_qubit_gates=num_single,
        num_two_qubit_gates=num_two,
        num_multi_qubit_gates=num_multi,
        num_measurements=num_measure,
    )

    print("Done.")
    print(ir.summary())
    return ir


# --- Allow running this file directly as a quick test ---
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python parser.py <path_to_circuit.qasm>")
        sys.exit(1)
    ir = parse_qasm(sys.argv[1])
