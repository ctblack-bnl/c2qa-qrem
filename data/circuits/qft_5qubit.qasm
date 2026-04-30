// Quantum Fourier Transform — 5 qubits
// OpenQASM 2.0
//
// The QFT is a core subroutine in Shor's algorithm (integer factoring)
// and quantum phase estimation. It is the quantum analogue of the
// classical discrete Fourier transform.
//
// Structure: each qubit gets a Hadamard gate followed by a cascade of
// controlled-phase rotations from all subsequent qubits, then the
// register is reversed with SWAP gates at the end.
//
// For n=5 qubits:
//   Single-qubit gates (H):      5
//   Two-qubit gates (CP + SWAP): 10 controlled-phase + 2 SWAPs = 12
//   Circuit depth:               ~15-20 (gates are partially parallelizable)
//
// This is a real algorithm — not a toy circuit. The QFT on 5 qubits
// is the largest component of Shor's algorithm factoring a ~10-bit number.

OPENQASM 2.0;
include "qelib1.inc";

qreg q[5];
creg c[5];

// --- Qubit 0 ---
h q[0];
cp(pi/2) q[1], q[0];
cp(pi/4) q[2], q[0];
cp(pi/8) q[3], q[0];
cp(pi/16) q[4], q[0];

// --- Qubit 1 ---
h q[1];
cp(pi/2) q[2], q[1];
cp(pi/4) q[3], q[1];
cp(pi/8) q[4], q[1];

// --- Qubit 2 ---
h q[2];
cp(pi/2) q[3], q[2];
cp(pi/4) q[4], q[2];

// --- Qubit 3 ---
h q[3];
cp(pi/2) q[4], q[3];

// --- Qubit 4 ---
h q[4];

// --- Bit reversal (SWAP network) ---
// QFT outputs are in reversed order — swap to correct
swap q[0], q[4];
swap q[1], q[3];
// q[2] is the center — no swap needed

// --- Measure ---
measure q[0] -> c[0];
measure q[1] -> c[1];
measure q[2] -> c[2];
measure q[3] -> c[3];
measure q[4] -> c[4];
