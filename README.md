# C2QA QREM — Quantum Resource Estimation and Materials Pipeline

This repository contains two connected tools for superconducting qubit research at C2QA:

**[Materials Explorer](explorer/)** — a searchable database of superconducting materials characterization data, automatically extracted from the published literature. Browse the live database at **https://c2qa-materials-explorer.onrender.com** — no installation required.

**[Baby QREM](qrem/)** — a quantum resource estimator. Given a quantum circuit and a qubit hardware profile, it estimates how many physical qubits are needed and how that changes as materials improve.

---

## How they connect

The Explorer ingests materials papers and extracts structured characterization records (T1, T2, Tc, RRR, loss tangent, and ~50 other fields). Records with device performance data can be projected into Baby QREM hardware profiles, directly connecting materials measurements to resource estimates.

```
Scientific Papers
      ↓
[Explorer] — ingestion pipeline → materials database
      |
      |── Measured device performance (T1, T2)
      |   → hardware profile YAMLs
      |                  ↓
      |             [Baby QREM]
      |
      └── Material properties (Tc, RRR, loss tangent)
          → corpus mining → materials-to-device mapping layer
```

The interface between the two is narrow and one-directional: the Explorer produces YAML hardware profiles (via `explorer/generate_qubit_profile.py`), and Baby QREM consumes them. A QREM contributor only needs to understand the YAML format, not the ingestion pipeline.

---

## Who should read what

**You want to browse materials data** → go to https://c2qa-materials-explorer.onrender.com. No installation needed.

**You want to contribute to the Explorer** (ingestion pipeline, schema, corpus mining) → read [`explorer/README.md`](explorer/README.md).

**You want to contribute to Baby QREM** (error correction model, noise model, circuits, hardware profiles) → read [`qrem/README.md`](qrem/README.md).

---

## Specification documents

Full design rationale and implementation details are in [`docs/`](docs/):

- `quantum_resource_estimator_spec` — Baby QREM architecture
- `publications_ingester_spec` — Explorer ingestion pipeline and corpus mining
- `materials_characterization_schema` — six-block data schema, all fields, vocabulary
- `project_continuity` — current development state and next priorities

---

*C2QA QREM Project — May 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
