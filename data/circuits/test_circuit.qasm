// test_circuit.qasm
// Small example circuit for QREM pipeline testing
// Represents a 3-qubit repetition code syndrome measurement
// Suitable for: parser development, analyzer testing, initial resource estimation

OPENQASM 2.0;
include "qelib1.inc";

// --- Qubit registers ---
qreg data[3];       // 3 data qubits storing the logical qubit
qreg ancilla[2];    // 2 ancilla qubits for syndrome measurement
creg syndrome[2];   // 2 classical bits to record measurement results

// --- Encode logical |0> across 3 data qubits ---
// Start with data[0] in |0>, spread to data[1] and data[2] via CNOT
cx data[0], data[1];
cx data[0], data[2];

// --- Syndrome measurement: check data[0] and data[1] agree ---
h ancilla[0];
cx ancilla[0], data[0];
cx ancilla[0], data[1];
h ancilla[0];
measure ancilla[0] -> syndrome[0];

// --- Syndrome measurement: check data[1] and data[2] agree ---
h ancilla[1];
cx ancilla[1], data[1];
cx ancilla[1], data[2];
h ancilla[1];
measure ancilla[1] -> syndrome[1];

// --- Single qubit gates on data qubits ---
x data[0];
z data[1];
h data[2];

// --- Final readout of data qubits ---
creg result[3];
measure data[0] -> result[0];
measure data[1] -> result[1];
measure data[2] -> result[2];
