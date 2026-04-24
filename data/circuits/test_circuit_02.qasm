// test_circuit_02.qasm
// Second test circuit for QREM pipeline testing
// Represents a variational quantum eigensolver (VQE) ansatz layer
// Key differences from test_circuit_01:
//   - Same qubit pairs interact MULTIPLE times (tests locality scoring)
//   - One clear hub qubit with many more interactions than others
//   - Larger circuit: 4 qubits, more gates
//   - No ancilla qubits — all qubits are data qubits

OPENQASM 2.0;
include "qelib1.inc";

// --- Qubit registers ---
qreg q[4];          // 4 data qubits
creg c[4];          // 4 classical bits for readout

// --- Initial state preparation ---
h q[0];
h q[1];
h q[2];
h q[3];

// --- Entangling layer 1 ---
// q[0] is the hub — it interacts with all other qubits
cx q[0], q[1];
cx q[0], q[2];
cx q[0], q[3];

// --- Rotation layer 1 ---
rz(0.5) q[0];
rz(0.5) q[1];
rz(0.5) q[2];
rz(0.5) q[3];

// --- Entangling layer 2 ---
// Same pairs interact again — this is what creates locality
cx q[0], q[1];
cx q[1], q[2];
cx q[2], q[3];

// --- Rotation layer 2 ---
rx(0.3) q[0];
rx(0.3) q[1];
rx(0.3) q[2];
rx(0.3) q[3];

// --- Entangling layer 3 ---
// q[0] dominates again — cementing its hub status
cx q[0], q[1];
cx q[0], q[2];
cx q[1], q[3];

// --- Final rotation layer ---
rz(0.7) q[0];
rz(0.7) q[1];
rz(0.7) q[2];
rz(0.7) q[3];

// --- Readout ---
measure q[0] -> c[0];
measure q[1] -> c[1];
measure q[2] -> c[2];
measure q[3] -> c[3];
