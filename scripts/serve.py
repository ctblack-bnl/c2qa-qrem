#!/usr/bin/env python3
"""
serve.py — Local development server for the QREM pipeline UI.
Serves static HTML files AND handles API calls from the browser UI.

Usage:
    python3 scripts/serve.py

Then open:
    http://localhost:8000/scripts/qrem_ui.html

API routes:
    GET  /api/profiles   — list available profile components for UI dropdowns
    GET  /api/circuits   — list available .qasm circuit files
    POST /api/estimate   — run estimation, returns EstimationResult as JSON
"""
import http.server
import json
import os
import sys
from pathlib import Path

PORT = 8000

# ── Resolve repo root (parent of scripts/) ────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent

# Add src/qrem to path so we can import the pipeline modules
QREM_SRC = REPO_ROOT / "src" / "qrem"
sys.path.insert(0, str(QREM_SRC))

# Modular hardware profiles directory
PROFILES_DIR = QREM_SRC / "hardware_profiles"

# Legacy fallback — still works if modular profiles not specified
LEGACY_PROFILE_PATH = PROFILES_DIR / "superconducting.yaml"

CIRCUITS_DIR = REPO_ROOT / "data" / "circuits"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    # ── Route GET requests ────────────────────────────────────────────────────
    def do_GET(self):
        if self.path == "/api/profiles":
            self._handle_profiles()
        elif self.path == "/api/circuits":
            self._handle_circuits_get()
        else:
            super().do_GET()

    # ── Route POST requests ───────────────────────────────────────────────────
    def do_POST(self):
        if self.path == "/api/estimate":
            self._handle_estimate()
        elif self.path == "/api/circuits":
            self._handle_circuits_get()
        else:
            self._send_json(404, {"error": f"Unknown route: {self.path}"})

    def _handle_profiles(self):
        """
        Return available profile names for each component directory.
        Used to populate the four UI dropdowns.

        Response:
        {
            "ok": true,
            "profiles": {
                "qubits":           ["transmon_baseline_2026"],
                "interconnect":     ["microwave_photonic_85pct", ...],
                "module":           ["module_1000q_nearest_neighbor"],
                "error_correction": ["surface_code_1e6"]
            }
        }
        """
        try:
            from profile_loader import list_profiles
            profiles = list_profiles(str(PROFILES_DIR))
            self._send_json(200, {"ok": True, "profiles": profiles})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_estimate(self):
        """
        Run the QREM pipeline and return results as JSON.

        Request body — modular mode (preferred):
        {
            "circuit": "test_circuit.qasm",
            "qubits":           "transmon_baseline_2026",
            "interconnect":     "microwave_photonic_85pct",
            "module":           "module_1000q_nearest_neighbor",
            "error_correction": "surface_code_1e6",
            "profile_overrides": {
                "gates": {"two_qubit_fidelity_pct": 99.5}
            }
        }

        Request body — legacy mode (still works):
        {
            "circuit": "test_circuit.qasm",
            "profile_overrides": {
                "gates": {"two_qubit_fidelity_pct": 99.5}
            }
        }

        Response:
        {
            "ok": true,
            "result": { ...EstimationResult.to_dict()... },
            "profile_used": {
                "qubits": "transmon_baseline_2026",
                "interconnect": "microwave_photonic_85pct",
                "module": "module_1000q_nearest_neighbor",
                "error_correction": "surface_code_1e6"
            }
        }
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            # Resolve circuit path — only allow files inside data/circuits/
            circuit_filename = body.get("circuit", "test_circuit.qasm")
            circuit_path = CIRCUITS_DIR / Path(circuit_filename).name
            if not circuit_path.exists():
                self._send_json(404, {"error": f"Circuit not found: {circuit_filename}"})
                return

            profile_overrides = body.get("profile_overrides", None)

            # Determine modular vs legacy mode
            qubits          = body.get("qubits")
            interconnect    = body.get("interconnect")
            module          = body.get("module")
            error_correction = body.get("error_correction")

            use_modular = all([qubits, interconnect, module, error_correction])

            # Import here so import errors surface as clean JSON responses
            from estimator import run_estimation

            if use_modular:
                result = run_estimation(
                    circuit_path=str(circuit_path),
                    profiles_dir=str(PROFILES_DIR),
                    qubits=qubits,
                    interconnect=interconnect,
                    module=module,
                    error_correction=error_correction,
                    profile_overrides=profile_overrides,
                    verbose=False,
                )
                profile_used = {
                    "qubits":           qubits,
                    "interconnect":     interconnect,
                    "module":           module,
                    "error_correction": error_correction,
                }
            else:
                # Legacy fallback — use monolithic superconducting.yaml
                result = run_estimation(
                    circuit_path=str(circuit_path),
                    profile_path=str(LEGACY_PROFILE_PATH),
                    profile_overrides=profile_overrides,
                    verbose=False,
                )
                profile_used = {"legacy": str(LEGACY_PROFILE_PATH)}

            import math
            result_dict = result.to_dict()
            # JSON doesn't support Infinity or NaN — replace with null
            for key, val in result_dict.items():
                if isinstance(val, float) and not math.isfinite(val):
                    result_dict[key] = None

            self._send_json(200, {
                "ok": True,
                "result": result_dict,
                "profile_used": profile_used,
            })

        except Exception as e:
            import traceback
            print(f"[/api/estimate error] {e}")
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})

    def _handle_circuits_get(self):
        """
        Return a list of available circuit files.

        Response:
        {
            "ok": true,
            "circuits": ["test_circuit.qasm", "test_circuit_02.qasm"]
        }
        """
        try:
            circuits = sorted(f.name for f in CIRCUITS_DIR.glob("*.qasm"))
            self._send_json(200, {"ok": True, "circuits": circuits})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress routine GET logs; show POSTs and errors
        if args and (str(args[0]).startswith("POST") or
                     str(args[0]).startswith("GET /api") or
                     str(args[1]) not in ("200", "304")):
            super().log_message(format, *args)


if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    print(f"QREM Pipeline — Local Server")
    print(f"Serving from: {REPO_ROOT}")
    print(f"")
    print(f"  QREM UI:    http://localhost:{PORT}/scripts/qrem_ui.html")
    print(f"")
    print(f"Press Ctrl+C to stop.")
    print(f"")
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
