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
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Add qrem to path so we can import the pipeline modules
QREM_SRC = REPO_ROOT / "qrem"
sys.path.insert(0, str(QREM_SRC))

# Modular hardware profiles directory
PROFILES_DIR = QREM_SRC / "hardware_profiles"

# Legacy fallback — still works if modular profiles not specified
LEGACY_PROFILE_PATH = PROFILES_DIR / "superconducting.yaml"

CIRCUITS_DIR = REPO_ROOT / "data" / "circuits"
print(f"[DEBUG] REPO_ROOT: {REPO_ROOT}", flush=True)
print(f"[DEBUG] CIRCUITS_DIR: {CIRCUITS_DIR}", flush=True)
print(f"[DEBUG] CIRCUITS_DIR exists: {CIRCUITS_DIR.exists()}", flush=True)


STATIC_DIR = REPO_ROOT / "explorer" / "static"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT / "qrem"), **kwargs)

    # ── Route GET requests ────────────────────────────────────────────────────
    def do_GET(self):
        if self.path.startswith("/static/"):
            self._handle_static()
        elif self.path.startswith("/api/profile_values"):
            self._handle_profile_values()
        elif self.path == "/api/profiles":
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

    def _handle_static(self):
        """Serve static files from ingester/static/."""
        filename = self.path[len("/static/"):]
        filepath = STATIC_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            self._send_json(404, {"error": f"Static file not found: {filename}"})
            return
        suffix = filepath.suffix.lower()
        content_types = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".svg": "image/svg+xml",
            ".css": "text/css", ".js": "application/javascript",
        }
        content_type = content_types.get(suffix, "application/octet-stream")
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_profile_values(self):
        """
        Return the coherence and gate values from a named qubit profile.
        Used to initialize T1/T2/gate_time sliders on page load and profile change.

        Request: GET /api/profile_values?qubits=transmon_baseline_2026

        Response:
        {
            "ok": true,
            "T1_us": 200,
            "T2_us": 300,
            "two_qubit_gate_time_ns": 50,
            "two_qubit_fidelity_pct": 99.9,
            "measured_fields": [],
            "assumed_fields": ["T1_us", "T2_us", ...]
        }
        """
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            qubits_name = (params.get('qubits', [None])[0])

            if not qubits_name:
                self._send_json(400, {"error": "Missing ?qubits= parameter"})
                return

            from profile_loader import load_profile
            profile = load_profile(
                profiles_dir=str(PROFILES_DIR),
                qubits=qubits_name,
                error_correction=None,
            )

            coherence  = profile.get('coherence', {})
            gates      = profile.get('gates', {})
            provenance = profile.get('provenance', {})

            self._send_json(200, {
                "ok": True,
                "T1_us":                  coherence.get('T1_us', 200),
                "T2_us":                  coherence.get('T2_us', None),
                "two_qubit_gate_time_ns": gates.get('two_qubit_gate_time_ns', 50),
                "two_qubit_fidelity_pct": gates.get('two_qubit_fidelity_pct', 99.9),
                "measured_fields":        provenance.get('measured_fields', []),
                "assumed_fields":         provenance.get('assumed_fields', []),
            })
        except Exception as e:
            self._send_json(500, {"error": str(e)})

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

            # Determine modular vs legacy mode.
            # In the single-module estimator, the UI sends null for interconnect
            # and module (Tier 2 not yet active). Fall back to legacy profile
            # when either is missing, which loads only qubits + error_correction.
            qubits          = body.get("qubits")
            interconnect    = body.get("interconnect")
            module          = body.get("module")
            error_correction = body.get("error_correction")

            # Use modular mode only when all four components are present and non-null.
            # Currently interconnect and module will be null (single-module estimator).
            use_modular = all([qubits, interconnect, module, error_correction])

            # Partial modular: qubits + error_correction present, interconnect/module null.
            # This is the normal operating mode for the single-module estimator.
            use_partial_modular = bool(qubits and error_correction and not (interconnect and module))

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
            elif use_partial_modular:
                # Single-module estimator: load qubits + error_correction only.
                # Interconnect and module profiles are not needed (Tier 2 inactive).
                result = run_estimation(
                    circuit_path=str(circuit_path),
                    profiles_dir=str(PROFILES_DIR),
                    qubits=qubits,
                    interconnect=None,
                    module=None,
                    error_correction=error_correction,
                    profile_overrides=profile_overrides,
                    verbose=False,
                )
                profile_used = {
                    "qubits":           qubits,
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
            print(f"[DEBUG] t1_decomposition is: {type(result_dict.get('t1_decomposition'))} — {result_dict.get('t1_decomposition') is not None}")
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
    print(f"  QREM UI:    http://localhost:{PORT}/scripts/qrem_ui.html  (run from repo root)")
    print(f"")
    print(f"Press Ctrl+C to stop.")
    print(f"")
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
