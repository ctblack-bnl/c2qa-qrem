#!/usr/bin/env python3
"""
serve.py — Local development server for the QREM pipeline UI.
Serves static HTML files AND handles API calls from the browser UI.

Usage:
    python3 scripts/serve.py

Then open:
    http://localhost:8000/scripts/qrem_ui.html
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

# Hardware profile and circuits live here
PROFILE_PATH = QREM_SRC / "hardware_profiles" / "superconducting.yaml"
CIRCUITS_DIR = REPO_ROOT / "data" / "circuits"


class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    # ── Route POST requests ───────────────────────────────────────────────────
    def do_POST(self):
        if self.path == "/api/estimate":
            self._handle_estimate()
        elif self.path == "/api/circuits":
            self._handle_circuits()
        else:
            self._send_json(404, {"error": f"Unknown route: {self.path}"})

    def _handle_estimate(self):
        """
        Run the QREM pipeline and return results as JSON.

        Request body:
        {
            "circuit": "test_circuit.qasm",         // filename only, looked up in data/circuits/
            "profile_overrides": {                   // optional — vary params without editing yaml
                "gates": {
                    "two_qubit_fidelity_pct": 99.5
                }
            }
        }

        Response:
        {
            "ok": true,
            "result": { ...EstimationResult.to_dict()... }
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

            # Import here so import errors surface as clean JSON responses
            from estimator import run_estimation

            result = run_estimation(
                circuit_path=str(circuit_path),
                profile_path=str(PROFILE_PATH),
                profile_overrides=profile_overrides,
                verbose=False,
            )

            import math
            result_dict = result.to_dict()
            # JSON doesn't support Infinity or NaN — replace with null
            for key, val in result_dict.items():
                if isinstance(val, float) and not math.isfinite(val):
                    result_dict[key] = None
            self._send_json(200, {"ok": True, "result": result_dict})

        except Exception as e:
            import traceback
            print(f"[/api/estimate error] {e}")
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})

    def _handle_circuits(self):
        """
        Return a list of available circuit files.

        Response:
        {
            "ok": true,
            "circuits": ["test_circuit.qasm", "test_circuit_02.qasm"]
        }
        """
        try:
            circuits = sorted(
                f.name for f in CIRCUITS_DIR.glob("*.qasm")
            )
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
        if args and (str(args[0]).startswith("POST") or str(args[1]) not in ("200", "304")):
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
