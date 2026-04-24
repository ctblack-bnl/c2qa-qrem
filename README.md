# C2QA QREM — Quantum Resource Estimation and Materials Pipeline

A modular, staged pipeline for quantum resource estimation and materials characterization data for superconducting qubit systems. The system estimates the physical resources (qubits, modules, error correction overhead) required to run quantum circuits on modular hardware, connects those estimates to physical material properties, and automatically extracts structured materials data from scientific publications into a searchable database.

**Core principle throughout: AI proposes, humans approve.** Every AI inference carries a confidence score and source citation. Simplifying assumptions are always documented explicitly in tool outputs.

---

## Three Components

**QREM Pipeline** — takes a quantum circuit and a hardware profile, and estimates how many physical qubits, modules, and error correction resources are needed to run it. Connects circuit-level requirements to device-level parameters and ultimately to material properties.

**Publications Ingester** — reads scientific papers (PDFs) and automatically extracts structured materials characterization data into a database. Handles relevance classification, two-pass extraction, idempotent processing, and human review flagging.

**Materials Database** — a structured, queryable store of materials characterization records following the Five-Center Materials Working Group schema. Populated by the ingester and by direct submission. Feeds into the QREM materials-to-device mapping layer.

---

## Prerequisites

- Python 3.10+ recommended (3.9 minimum — some deprecation warnings with Qiskit)
- API access: Azure Claude via Anthropic Foundry (for ingester)

```bash
pip install qiskit networkx pyyaml anthropic
```

---

## Directory Structure

```
2026-04 c2qa_qrem/
  src/
    qrem/
      parser.py                   ← Stage 1: OpenQASM → CircuitIR
      circuit_ir.py               ← Internal circuit representation
      analyzer.py                 ← Stage 2: interaction graph + metrics
      estimator.py                ← Stages 3-4: physical resource estimation
      reporter.py                 ← Stage 5: comparison + report (planned)
      hardware_profiles/
        superconducting.yaml      ← Superconducting baseline profile
        neutral_atom.yaml         ← Neutral atom profile (planned)

  ingester/
    pipeline_ingest.py            ← Main loop: find PDFs, classify, extract, write JSONL
    prompts.py                    ← Relevance check + extraction prompt builders
    processed_ledger.py           ← DOI-primary / filename-fallback idempotency ledger
    build_sqlite.py               ← Loads JSONL into SQLite for browsing
    config.py                     ← Azure/Claude API configuration (env vars)
    openai_client.py              ← Provider abstraction (Azure Claude / OpenAI)
    io_jsonl.py                   ← Append-only JSONL read/write utilities
    json_utils.py                 ← Safe JSON serialization

  materials/
    schema.py                     ← Python dataclasses for the 5-block schema
    database.py                   ← Read/write characterization records

  data/
    circuits/                     ← Input .qasm circuit files
      test_circuit.qasm           ← 3-qubit repetition code syndrome (5 qubits)
      test_circuit_02.qasm        ← VQE ansatz layer (4 qubits)
    papers/                       ← Drop PDFs here for ingestion
    ingested/
      records.jsonl               ← Append-only canonical ingestion ledger
      processed_ledger.json       ← Tracks processed papers (skip on re-run)
      records.db                  ← SQLite browse database (derived, rebuildable)

  docs/
    quantum_resource_estimator_spec.md   ← QREM pipeline specification
    publications_ingester_spec.md        ← Ingester specification
    materials_characterization_schema.md ← Five-center schema specification
```

---

## Environment Setup

```bash
# For the ingester (Claude via Azure Foundry)
export PROVIDER=claude
export AZURE_CLAUDE_API_KEY=your-key-here
export AZURE_CLAUDE_BASE_URL=https://your-endpoint.services.ai.azure.com/anthropic
export AZURE_CLAUDE_DEPLOYMENT=claude-sonnet-4-6
```

The client factory in `ingester/openai_client.py` wraps both Azure Claude and Azure OpenAI behind a common interface. Switch providers by changing the `PROVIDER` env var.

---

## Running the QREM Pipeline

The pipeline currently runs stage by stage from `src/qrem/`. Stages 1-3 are complete.

### Stage 1 — Parse a circuit

```bash
cd src/qrem
python3 parser.py ../../data/circuits/test_circuit.qasm
```

Reads the OpenQASM file and produces a CircuitIR: qubit inventory, gate list, and summary counts (single-qubit gates, two-qubit gates, measurements).

### Stage 2 — Analyze circuit structure

```bash
python3 analyzer.py ../../data/circuits/test_circuit.qasm
```

Builds the qubit interaction graph. Reports interacting qubit pairs sorted by frequency, per-qubit interaction counts, hub qubits, and a locality score (0.0 = interactions spread broadly, 1.0 = same pairs interact repeatedly).

### Stage 3 — Estimate physical resources

```bash
python3 estimator.py ../../data/circuits/test_circuit.qasm hardware_profiles/superconducting.yaml
```

Translates the logical circuit into physical resource requirements for the specified hardware platform. Reports:
- Physical error rate and surface code distance
- Physical qubits per logical qubit (formula: 2d²-1)
- Computation qubits and magic state factory qubits
- Total physical qubit count and module count
- Inter-module operation count and fraction
- Feasibility assessment
- All simplifying assumptions made

### Example output (test_circuit.qasm, 99.9% two-qubit fidelity)

```
Physical error rate      : 0.0010 (0.10%)
Code distance (d)        : 11
Physical qubits/logical  : 241 (= 2d² - 1)
Logical qubits           : 5
Computation qubits       : 1205
TOTAL physical qubits    : 1205
Modules needed           : 2
Inter-module operations  : 2 (33.3% of two-qubit gates)
Feasible                 : YES
```

---

## Running the Publications Ingester

### Setup

Drop PDF papers into `data/papers/`. The ingester will process all PDFs it finds, skip papers already in the processed ledger, and write records to `data/ingested/records.jsonl`.

```bash
cd ingester
export PROVIDER=claude
export AZURE_CLAUDE_API_KEY=your-key-here
python3 pipeline_ingest.py
```

### Two-pass processing

Each paper goes through two passes:

**Pass 1 — Relevance check (~15 seconds):** Claude reads the paper and decides whether it is relevant to the superconducting qubit materials database (high / medium / low), what type of paper it is (primary research / review / process comparison), and extracts the DOI. Low-relevance papers are logged and skipped — no further API cost.

**Pass 2 — Full extraction (~60-90 seconds):** For relevant papers only. Claude extracts structured materials characterization data following the five-center schema. Sparse output — only fields actually reported in the paper are included. Every field carries a confidence score (high / medium / low) and a specific source citation.

### Idempotency

Papers already processed are automatically skipped. The processed ledger uses DOI as the primary key (stable even if the file is renamed) with filename as a fallback. Re-running the ingester on the same directory is safe.

### Building the SQLite browse database

After each ingestion run, rebuild the SQLite database for browsing:

```bash
python3 build_sqlite.py
```

Open `data/ingested/records.db` in DB Browser for SQLite (free, sqlitebrowser.org). Three tables:

- **papers** — one row per paper: outcome, DOI, title, authors, journal, review flags
- **samples** — one row per extracted sample: all schema fields as columns
- **catchall_items** — one row per catchall entry: additional measurements, anomalous observations, correlations, schema promotion candidates

The SQLite database is derived and rebuildable at any time from the JSONL ledger. It is not a source of truth.

### Useful queries

```sql
-- Coverage summary
SELECT
    COUNT(*) as total_samples,
    SUM(CASE WHEN Tc_K IS NOT NULL THEN 1 ELSE 0 END) as has_Tc,
    SUM(CASE WHEN RRR IS NOT NULL THEN 1 ELSE 0 END) as has_RRR,
    SUM(CASE WHEN Qi_internal IS NOT NULL THEN 1 ELSE 0 END) as has_Qi,
    SUM(CASE WHEN T1_us IS NOT NULL THEN 1 ELSE 0 END) as has_T1
FROM samples;

-- All samples with key measurements
SELECT filename, sample_id, film_material, Tc_K, RRR, Qi_internal
FROM samples
ORDER BY filename, sample_id;

-- Schema promotion candidates
SELECT filename, sample_id, description, notes
FROM catchall_items
WHERE item_type = 'schema_candidate';
```

---

## JSONL Ledger Design

All ingester records are written to an append-only JSONL file. Every record contains the full Pass 1 and Pass 2 outputs, provenance metadata, and human review flags. Records are never modified in place — the ledger is append-only.

```
records.jsonl  ← canonical ledger (source of truth)
  → records.db ← SQLite projection (derived, rebuildable)
```

Every ingested record starts with `human_reviewed: false` and `human_approved: false`. Records should be reviewed before feeding into the QREM materials-to-device mapping layer.

---

## Key Design Decisions

**Append-only JSONL as canonical ledger.** Reproducibility and auditability. Any downstream artifact can be regenerated from the JSONL. In-place mutation would break this guarantee.

**Two-pass ingestion.** Relevance classification is separated from extraction. Irrelevant papers are rejected cheaply before incurring full extraction cost. Every paper — whether ingested or skipped — produces an auditable record with an explicit decision and reason.

**Sparse extraction output.** Only fields actually reported in a paper are included in the extraction record. Absence means not reported — never zero. This keeps records clean and avoids token limit issues from dense null-filled output.

**DOI-primary idempotency.** The processed ledger uses DOI as the primary key, filename as fallback. Papers are recognized as already processed even if renamed, as long as the DOI matches.

**Hardware profiles as data, not code.** Hardware platform parameters (gate fidelity, coherence time, module capacity, inter-module link fidelity) are YAML files, not code. Changing platforms or running sensitivity analysis requires only editing a data file.

**Explicit assumptions in every output.** The QREM estimator documents every simplifying assumption in its output — perfect intra-module connectivity, analytical surface code approximation, greedy module assignment, T gate placeholder. These are not hidden.

**Provider abstraction.** `openai_client.py` wraps both Azure Claude and Azure OpenAI behind a common interface. Switch providers by changing the `PROVIDER` environment variable.

---

## Validated Results

### QREM Pipeline

| Circuit | Fidelity | Code distance | Physical qubits/logical | Modules |
|---|---|---|---|---|
| test_circuit (5 qubits) | 99.5% | 39 | 3,041 | 16 |
| test_circuit (5 qubits) | 99.9% | 11 | 241 | 2 |
| test_circuit_02 (4 qubits) | 99.5% | 39 | 3,041 | 13 |
| test_circuit_02 (4 qubits) | 99.9% | 11 | 241 | 1 |

A 0.4% improvement in two-qubit gate fidelity (99.5% → 99.9%) reduces module count from 16 to 2 for the syndrome measurement circuit. This is the core quantitative insight the tool is designed to surface.

### Publications Ingester

| Paper | Outcome | Samples |
|---|---|---|
| Bahrami et al. PRB 2026 (Ta vortex loss) | ✅ Ingested | 8 |
| Yang et al. PNAS 2026 (Ta-Hf resonators) | ✅ Ingested | 8 |
| Gant et al. 2026 | ✅ Ingested | — |
| Bhatia et al. 2025 (TaN nanowires) | ✅ Ingested | — |
| Meng et al. Quantum 2026 (network percolation) | ✅ Skipped — not relevant | 0 |

---

## Known Limitations

**QREM Pipeline:**
- Perfect intra-module connectivity assumed — SWAP routing overhead not yet modeled. Physical qubit counts are lower bounds.
- Analytical surface code approximation used — not full Stim simulation.
- T gate counting is a placeholder — magic state factory costs will be underestimated for T-gate-heavy circuits.
- Neutral atom hardware profile not yet implemented.
- Circuit depth and critical path (Stage 2d) not yet implemented.

**Publications Ingester:**
- Qi and T1 data reported only in figures (not tables) may be missed or extracted at lower confidence.
- Very large PDFs (>5MB) may take 2-3 minutes for Pass 2 extraction.
- Human review is essential before using extracted records in quantitative analysis — value confusion errors have been observed in testing.

---

## Specification Documents

Full design rationale, interface contracts, and implementation details are in the `docs/` folder:

- `quantum_resource_estimator_spec.md` — QREM pipeline architecture, error correction model, hardware profiles, development sequence
- `publications_ingester_spec.md` — ingester design, two-pass pipeline, sparse output, ledger design, known limitations
- `materials_characterization_schema.md` — five-center schema, all Block 1-5 fields, governance, schema evolution process

---

*C2QA QREM Project — April 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
