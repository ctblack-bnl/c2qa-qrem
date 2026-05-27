# tests/test_estimation_sync.py
#
# Sync test for the QREM estimator.
#
# PURPOSE: Ensure that the Python estimator produces the validated results
# documented in the README. Any change to the estimation math that shifts
# these numbers will cause this test to fail — which is the intended behavior.
# Fix the test only by updating BOTH the math AND the README table together.
#
# Run from the project root:
#   python3 tests/test_estimation_sync.py
#
# Or with pytest (if installed):
#   pytest tests/test_estimation_sync.py -v
#
# VALIDATED RESULTS (from README):
#   Circuit              | Fidelity | Code dist | Phys/logical | Modules
#   test_circuit (5q)    | 99.5%    | 39        | 3,041        | 16
#   test_circuit (5q)    | 99.9%    | 11        | 241          | 2
#   test_circuit_02 (4q) | 99.5%    | 39        | 3,041        | 13
#   test_circuit_02 (4q) | 99.9%    | 11        | 241          | 1

import sys
import os

# Allow running from project root or from tests/ directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QREM_SRC = os.path.join(PROJECT_ROOT, "qrem")
sys.path.insert(0, QREM_SRC)

from estimator import run_estimation

# Paths relative to project root
PROFILE = os.path.join(QREM_SRC, "hardware_profiles", "superconducting.yaml")
CIRCUIT_01 = os.path.join(PROJECT_ROOT, "data", "circuits", "test_circuit.qasm")
CIRCUIT_02 = os.path.join(PROJECT_ROOT, "data", "circuits", "test_circuit_02.qasm")

FIDELITY_LOW  = 99.5   # produces code distance 39
FIDELITY_HIGH = 99.9   # produces code distance 11


def check(label, result, expected_code_distance, expected_phys_per_logical,
          expected_modules, expected_logical_qubits):
    """
    Assert that a result matches expected values. Prints PASS or FAIL.
    Returns True if all assertions pass.
    """
    failures = []

    if result.code_distance != expected_code_distance:
        failures.append(
            f"  code_distance: got {result.code_distance}, expected {expected_code_distance}"
        )
    if result.physical_qubits_per_logical != expected_phys_per_logical:
        failures.append(
            f"  physical_qubits_per_logical: got {result.physical_qubits_per_logical}, "
            f"expected {expected_phys_per_logical}"
        )
    if result.num_modules != expected_modules:
        failures.append(
            f"  num_modules: got {result.num_modules}, expected {expected_modules}"
        )
    if result.num_logical_qubits != expected_logical_qubits:
        failures.append(
            f"  num_logical_qubits: got {result.num_logical_qubits}, "
            f"expected {expected_logical_qubits}"
        )

    if failures:
        print(f"FAIL  {label}")
        for f in failures:
            print(f)
        return False
    else:
        print(f"PASS  {label}")
        return True


def run_tests():
    print("=" * 60)
    print("QREM Estimator Sync Test")
    print("Validating against README table of known-good results")
    print("=" * 60)
    print()

    all_passed = True

    # -------------------------------------------------------------------------
    # test_circuit.qasm at 99.5% two-qubit fidelity
    # Expected: code distance 39, 3041 phys/logical, 16 modules, 5 logical qubits
    # -------------------------------------------------------------------------
    result = run_estimation(
        CIRCUIT_01, PROFILE,
        profile_overrides={"gates": {"two_qubit_fidelity_pct": FIDELITY_LOW}}
    )
    all_passed &= check(
        label="test_circuit.qasm  @ 99.5% fidelity",
        result=result,
        expected_code_distance=39,
        expected_phys_per_logical=3041,
        expected_modules=16,
        expected_logical_qubits=5,
    )

    # -------------------------------------------------------------------------
    # test_circuit.qasm at 99.9% two-qubit fidelity
    # Expected: code distance 11, 241 phys/logical, 2 modules, 5 logical qubits
    # -------------------------------------------------------------------------
    result = run_estimation(
        CIRCUIT_01, PROFILE,
        profile_overrides={"gates": {"two_qubit_fidelity_pct": FIDELITY_HIGH}}
    )
    all_passed &= check(
        label="test_circuit.qasm  @ 99.9% fidelity",
        result=result,
        expected_code_distance=11,
        expected_phys_per_logical=241,
        expected_modules=2,
        expected_logical_qubits=5,
    )

    # -------------------------------------------------------------------------
    # test_circuit_02.qasm at 99.5% two-qubit fidelity
    # Expected: code distance 39, 3041 phys/logical, 13 modules, 4 logical qubits
    # -------------------------------------------------------------------------
    result = run_estimation(
        CIRCUIT_02, PROFILE,
        profile_overrides={"gates": {"two_qubit_fidelity_pct": FIDELITY_LOW}}
    )
    all_passed &= check(
        label="test_circuit_02.qasm @ 99.5% fidelity",
        result=result,
        expected_code_distance=39,
        expected_phys_per_logical=3041,
        expected_modules=13,
        expected_logical_qubits=4,
    )

    # -------------------------------------------------------------------------
    # test_circuit_02.qasm at 99.9% two-qubit fidelity
    # Expected: code distance 11, 241 phys/logical, 1 module, 4 logical qubits
    # -------------------------------------------------------------------------
    result = run_estimation(
        CIRCUIT_02, PROFILE,
        profile_overrides={"gates": {"two_qubit_fidelity_pct": FIDELITY_HIGH}}
    )
    all_passed &= check(
        label="test_circuit_02.qasm @ 99.9% fidelity",
        result=result,
        expected_code_distance=11,
        expected_phys_per_logical=241,
        expected_modules=1,
        expected_logical_qubits=4,
    )

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print()
    print("=" * 60)
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED — see above for details")
        print()
        print("If you changed the estimation math intentionally:")
        print("  1. Update the expected values in this test file")
        print("  2. Update the validated results table in README.md")
        print("  3. Update the spec document if the formula changed")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
