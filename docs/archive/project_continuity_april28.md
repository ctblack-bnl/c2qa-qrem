# C2QA QREM — Project Architecture & Next Steps
## Continuity Document — April 28, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | Stages 1-3 complete. **Rescoping in progress:** stripping modular overhead, focusing on single-module materials-informed estimator with rich noise modeling. See Baby QREM Rescoping section. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | Operational. Three-pass pipeline (relevance, extraction, similarity profile). 97 papers, 155 samples, ~1,318 catchall items, 100% profile coverage. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | Explore/Search/Catchall tabs. Hybrid similarity search live. Material class sidebar. Hosted at https://c2qa-materials-explorer.onrender.com |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction from corpus | **NEW — built April 28.** Three-phase A→B→C pipeline. Human review UI integrated into ingestion pipeline as Stage 4. `findings.jsonl` append-only ledger. |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | Designed, not built. Corpus mining pipeline feeds it. First findings produced April 28. |

---

## How They Connect

```
Scientific Papers
      ↓
[2] Publications Ingester (Pass 1 → Pass 2 → Pass 3)
      ↓
[3] Materials Database
    (Tc, RRR, Qi, T1, derived quantities, catchall, similarity_profiles)
      |
      |── Measured device performance (T1, T2, gate fidelity) ─────────────┐
      |   → Hardware Profile Updater → qubit profile YAML                  ↓
      |                                                            [1] Baby QREM
      |── Measured inter-module properties ─────────────────────►          ↑
      |   → interconnect profile YAML                                       |
      |                                                                     |
      |── All corpus records ──────────────────────────────────────────────┤
      |   → [4] Corpus Mining Pipeline (Phase A→B→C)                       |
      |        → findings.jsonl → [6] Mapping Layer ──────────────────────→┘
      |
      └── Material properties only (Tc, RRR, resistivity, loss tangent)
          → [5] Materials Predictor → [6] Mapping Layer
```

**The scientific question the materials pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and run this quantum circuit, how many physical qubits do I need?"*

The modular architecture question ("how many modules?") is a separate Center-wide research effort involving computer scientists, algorithms, and error correction teams. Materials and devices feed into it, but the architectural challenges are not materials challenges. The materials → single-module estimator connection is the right scope for this project.

---

## Corpus Mining Pipeline — Built April 28

The mining pipeline is now operational end-to-end. It lives in `ingester/pipeline_mining.py` and runs as Stage 4 of the ingestion pipeline UI.

### Three-Phase Design (adapted from SEM metadata project)

**Phase A — Evidence extraction (mechanical, no AI)**
- Reads all 41 correlation items from catchall corpus
- Maps descriptive terms to canonical field names via `FIELD_MAP`
- Classifies each correlation: matched hypothesis / corpus gap / out of scope
- Scans full corpus for cross-sample co-occurrence evidence
- Builds compact evidence records (structured fields + relevant catchall items)
- Produces measurement frequency report — fields the community keeps measuring
- Outputs: `mining_evidence.jsonl`, `mining_corpus_gaps.jsonl`, `mining_out_of_scope.jsonl`, `mining_measurement_frequency.json`

**Phase B — AI reasoning (Claude, constrained to evidence)**
- Sends Claude each evidence table: hypothesis, stated correlations, cross-sample records
- Claude identifies patterns, cites specific samples, attempts self-falsification
- Chunked at 30 records per call; conservative merge (lowest confidence wins)
- Prior approved findings fed as context in subsequent runs
- Outputs: `mining_reasoned.jsonl`

**Phase C — AI write-up (Claude)**
- Takes Phase B reasoning and writes structured human-reviewable finding
- Each finding: title, summary, detail, supporting/complicating records, QREM implications, per-material recommendation, questions for reviewer
- Outputs: `mining_findings.jsonl`, `mining_findings_report.md`

### Current Corpus Mining Results (April 28)

| Metric | Value |
|---|---|
| Correlations found | 41 |
| Out of scope (device/circuit physics) | 11 |
| Corpus gaps (unmappable/unmeasurable) | 16 |
| Hypotheses matched | 13 |
| Hypotheses with cross-sample evidence (≥3) | 3 |
| Findings produced | 3 |

The 3 findings are all negative/inconclusive — expected given sparse corpus coverage for key fields. This is honest and useful: negative results are real findings. The key scientific insight from Phase B: **cross-material analysis is confounded by material identity; per-material-class analysis is needed** for meaningful hypothesis testing.

### Human Review UI (Stage 4 — `ingest_pipeline.html`)

Stage 4 added to the ingestion pipeline alongside Stages 1-3. Finding cards expand inline with full detail. Review actions:
- **Accept Finding** — finding is scientifically correct (including negative results) — recorded in `findings.jsonl`
- **Send Back for Revision** — needs Claude to reconsider something specific, with reviewer notes
- **Reject Finding** — analysis is flawed, do not record

After review: "Update Database" button triggers database rebuild, then git push → Explorer Findings tab (not yet built).

### Running the Mining Pipeline

```bash
cd ingester
python3 pipeline_mining.py phase-a   # mechanical, no AI
python3 pipeline_mining.py phase-b   # AI reasoning
python3 pipeline_mining.py phase-c   # AI write-up

# Or run all phases via the UI (Stage 4 "Run Mining" button)
# Or run individually from CLI with custom paths:
python3 pipeline_mining.py phase-b --evidence ../data/ingested/mining_evidence.jsonl
python3 pipeline_mining.py phase-c --prior ../data/ingested/findings.jsonl
```

---

## Schema Evolution — Redesigned April 28

### Key decisions made

**`schema_candidate` catchall type is being retired.** Merge into `additional_measurement`. The name implied Claude was making a governance decision; the rename reflects the correct meaning — Claude noticed something that didn't fit existing schema, worth capturing for future review.

**Schema promotion is now frequency-driven, not per-paper.** The measurement frequency report (produced by Phase A) surfaces fields appearing in >X% of materials samples. These are promotion candidates — the community collectively decided they matter. Threshold: ~5% of materials samples (currently ~8 samples at 155 total).

**Promotion requires two things:** (1) add field as named column in `build_sqlite.py`, extracting from `catchall_items.value` (already populated with clean numeric values by Claude during Pass 2); (2) no prompt changes needed — Claude is already extracting these values, just not into named columns.

**Stage 4 in ingestion pipeline UI** will surface promotion candidates for human approval as part of normal workflow.

**Key domain rule:** Only geometry-independent (intrinsic) material properties are promotable. Sheet kinetic inductance (Lk,sq) yes; total kinetic inductance (Lk) no. Critical current density (Jc-material) yes; critical current (Ic) no.

### Fields ready for promotion (confirmed by diagnostic)

| Field | Frequency | Source in catchall | Units | Notes |
|---|---|---|---|---|
| Sheet kinetic inductance | 49× | `Kinetic inductance per square` description | pH/sq | Normalize all to pH/sq; skip total Lk entries |
| Mean free path | 9× | `Mean free path l` description | nm | 8 of 9 entries clean numeric; skip NbN range entry |
| Vortex activation temperature | 11× | `vortex activation` description | K | Intrinsic material property |

### Ic/Jc disambiguation — flagged for future work

Two physically distinct quantities both called Jc:
- **Material Jc** — bulk film critical current density. Intrinsic. Derivable from Ic_film / (film_width × film_thickness). Units: A/m².
- **Junction Jc** — Josephson junction critical current density. Device property. Derivable from Ic_junction / junction_area_um2. Units: µA/µm².

These need separate named columns: `derived_material_Jc_A_m2` and `derived_junction_Jc_uA_um2`. New `derive.py` functions needed. Extraction prompt currently conflates these — needs disambiguation. New schema fields: film geometry (width) and junction dimensions.

---

## `/api/corpus` Endpoint — Built April 28

New endpoint in `serve_materials.py` returns all ingested samples as self-contained records:
- All named column fields
- `sample_json` — full raw Pass 2 extraction (includes unpromoted fields)
- `derived_json` — all derived quantities
- `catchall` — nested list of all catchall items

```
GET /api/corpus                          # all types
GET /api/corpus?types=correlation        # filtered
GET /api/corpus?types=correlation,additional_measurement
```

Validated with `test_corpus_fetch.py` — 10/10 tests passing. Real corpus numbers: 155 samples, 41 correlations, 1,318 catchall items total.

---

## Baby QREM — Strategic Rescoping (April 28)

### The Core Reframe

Baby QREM will be simplified to focus on the **materials → single-module resource estimator** connection. The modular overhead calculations (module count, inter-module operations, purification rounds, communication qubits) are being removed. This is not a loss — it's a sharpening.

The modular architecture is a Center-wide research problem involving computer scientists, algorithms people, and error correction experts. Materials and devices feed into it, but the architectural challenges are not materials challenges. A clean single-module estimator that takes materials inputs and produces physical qubit counts is the right scope and is genuinely useful.

### What the Simplified Estimator Does

```
QASM circuit
    ↓
Stage 1 — Parse (already working)
  gate list, qubit count, T gate count
    ↓
Stage 2 — Analyze (add circuit depth)
  critical path depth via topological sort
  (drop: interaction graph, hub qubits, module partitioning)
    ↓
Stage 3 — Single-module estimate (simplify)
  gate fidelity → physical error rate
  circuit depth → logical error rate target
  → code distance d
  → physical qubits per logical qubit (2d²-1)
  → total physical qubits for this circuit
  (drop: module count, inter-module ops, purification, communication qubits)
    ↓
Materials inputs from corpus
  T1, T2, gate fidelity → hardware profile [MEASURED] or [ASSUMED]
  RRR, loss tangent → implied T1 via mapping layer (future)
  Noise spectrum → coherence budget breakdown (future)
```

### Why Circuit Depth Is Needed

Circuit depth is the length of the critical path through the QASM circuit — the longest sequence of gates that must execute sequentially. A deeper circuit needs a lower logical error rate per gate, which requires higher code distance and more physical qubits. The parser already extracts the full gate list; we just need to add critical path calculation (topological sort, ~20-30 lines).

**Note on connectivity:** Within a single module, qubit connectivity affects runtime via SWAP routing overhead (physically distant qubits require SWAP chains to interact — roughly 3 gates each). For the simplified estimator, assume perfect intra-module connectivity and flag this explicitly as assumption #1. This gives a lower bound on resource cost. Connectivity becomes important when modeling realistic chip layouts, which is a future addition.

### What the Estimator Can Do Beyond Basic Code Distance

Even without modularity, the single-module estimator can be rich:
- **Gate fidelity → code distance** — the basic connection
- **T1, T2 → coherence budget** — how much error budget is consumed by relaxation vs dephasing
- **Loss tangent, surface oxide → implied T1** — indirect materials path via mapping layer
- **RRR → quasiparticle density → T1 contribution** — materials property in coherence chain
- **Vortex activation temperature → microwave loss → T1** — full materials chain for Ta films
- **Sensitivity analysis** — "if RRR improves from 45 to 65, what happens to code distance?" — the most useful output for materials scientists

### Next Steps for Baby QREM

1. Add circuit depth calculation to Stage 2 (critical path via topological sort)
2. Strip Stage 3 down to single-module: code distance + physical qubit count only
3. Remove interconnect and module profile dropdowns from UI; simplify to qubit profile only
4. Add coherence budget breakdown output — T1 loss attribution by mechanism
5. Wire sensitivity analysis: materials property → implied T1 → code distance change

## Key Architectural Insights — April 28

### Per-material-class analysis

Phase B surfaced that cross-material hypothesis testing is confounded by material identity. Future Phase A should build per-material-class evidence tables in addition to cross-corpus tables. Materials with enough samples for focused analysis: Ta (Bahrami series), Ta-Hf (Yang series), NbSe2 (Zaman series), NbN (Bøttcher series).

### Mining pipeline is domain-generalizable

The three-phase A→B→C architecture is not specific to superconducting materials. All domain-specific knowledge lives in configuration: `FIELD_MAP`, `DEVICE_PHYSICS_TERMS`, `is_materials_sample()` filter, Phase B system prompt context. These should be extracted to a `mining_config.yaml` file — same philosophy as QREM hardware profiles (configuration as data, not code). Do this after the pipeline is validated end-to-end.

### Catchall value field is already structured

Diagnostic confirmed that Claude during Pass 2 already stores clean numeric values in `catchall_items.value` (e.g. "1.195 nH/sq", "109.3 ± 0.8 nm"). Schema promotion can read directly from this field without re-ingestion or prompt changes.

---

## Hosted Infrastructure

| Service | URL | Auto-deploys from |
|---|---|---|
| Materials Explorer | https://c2qa-materials-explorer.onrender.com | GitHub main branch |
| Baby QREM | Local only (localhost:8000) | — |
| Ingestion + Mining Pipeline | Local only (localhost:8001/ingest_pipeline.html) | — |

Mining pipeline is intentionally local-only: requires API keys, database write access, and long-running AI calls. The Explorer on Render stays read-only.

**Workflow:** Run mining locally → approve findings → git push → Explorer Findings tab updates (tab not yet built).

---

## Repository & Running

**GitHub:** `https://github.com/ctblack-bnl/c2qa-qrem`

```bash
# Standard commit workflow
git add .
git commit -m "description"
git push   # triggers Render redeploy

# Run Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py

# Run Baby QREM (port 8000)
cd 2026-04\ c2qa_qrem && python3 scripts/serve.py

# Run mining pipeline manually
cd ingester
python3 pipeline_mining.py phase-a
python3 pipeline_mining.py phase-b
python3 pipeline_mining.py phase-c

# Test corpus endpoint
python3 test_corpus_fetch.py
python3 test_corpus_fetch.py --sample "Bahrami_2026_D1"

# Backfill similarity profiles (if vocabulary changes)
python3 backfill_similarity_profiles.py --dry-run
python3 backfill_similarity_profiles.py
```

---

## Coding Priorities — Next Sessions

**Next session — two parallel tracks:**

**Track A: Mining improvement**

1. **Schema promotion implementation** — add sheet kinetic inductance, mean free path, vortex activation temperature as named columns in `build_sqlite.py`, reading from `catchall_items.value`. Rebuild SQLite. Re-run Phase A — expect significantly more hypotheses with cross-sample evidence.

2. **Per-material-class Phase A** — modify Phase A to build evidence tables stratified by material class (Ta, Ta-Hf, NbSe2, NbN). This is the architectural fix Phase B identified — cross-material analysis is confounded by material identity. The Bahrami Ta series (8 samples, wide mean free path range, vortex activation temperature measured) is particularly promising.

**Track B: Baby QREM simplification**

3. **Simplify Baby QREM** — strip modular overhead from Stage 3; add circuit depth to Stage 2; simplify UI to single-qubit profile dropdown. Primary output: code distance and physical qubit count per logical qubit, driven by materials inputs. See Baby QREM Rescoping section.

4. **Coherence budget output** — add T1 loss attribution breakdown to Baby QREM output: TLS, quasiparticle, vortex motion, radiation contributions. Makes the materials → resource connection explicit.

**Medium effort (one session each):**

5. **Stage 4 schema evolution UI** — surface measurement frequency report in ingestion pipeline for human approval of field promotions.

6. **Explorer Findings tab** — read-only view of approved `findings.jsonl` on hosted Explorer. Updates on git push.

7. **Sensitivity analysis in Baby QREM** — "if RRR improves from 45 to 65, what happens to code distance?" Routes material property improvements through the full single-module pipeline. This is the key output for materials scientists.

8. **Ic/Jc disambiguation** — new `derive.py` functions, new schema columns, extraction prompt disambiguation.

**Larger effort (multiple sessions):**

9. **Materials Predictor** — Gaussian process regression per material class.

10. **Mining config file** — extract domain-specific config to `mining_config.yaml` for generalizability.

11. **Corpus expansion** — older literature ingestion; policy/priority question.

12. **Supplementary information linking** — SI files linked to companion papers via DOI-based naming.

---

## Data Provenance — Supplementary Files and External Databases

*Captured April 28, 2026 — architectural principle, not yet implemented.*

Peer review is **inherited, not intrinsic**. SI files and external database entries that can be traced to published papers inherit that paper's peer review credibility.

| Source type | Record-level confidence |
|---|---|
| Peer-reviewed paper (main text) | Highest |
| SI file linked to paper via DOI | High |
| arXiv preprint | Medium-high |
| External database entry with traceable DOI | Medium |
| External database entry, no traceable publication | Low |

**SI linking fix:** DOI-based naming convention `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Ingester recognizes pattern and ingests as single logical record. Pass 2 has access to both documents simultaneously.

---

## Longer-Term Vision — Federated Knowledge Graph

The PUK concept scales to a general **federated knowledge graph for quantum computing research** built from public literature. Agreement required only at query time, not creation time. No permission required — inputs are already public.

*One-sentence summary: A continuously updated, AI-maintained knowledge graph of quantum computing research, built from public literature, that finds connections across centers and disciplines that no human would have the bandwidth to make.*

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — self-contained. Hardware profiles, similarity profiles, and mining findings are projections of records.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. Every mining finding requires human review before entering `findings.jsonl`.
- **Sparse extraction** — only fields actually reported in a paper are included. Absence = not reported, never zero.
- **Derived quantities live in SQLite, not JSONL** — computed at build time, no re-ingestion needed.
- **Configuration as data, not code** — hardware profiles, mining field maps, domain context are YAML/config files, not hardcoded logic.
- **Explicit assumptions in every output** — QREM documents all simplifying assumptions; mining pipeline documents all classification decisions.
- **Single-module first** — materials → single-module resource estimator is the primary deliverable. Modular overhead (Tier 2) is a separate Center-wide research problem; materials feed into it but do not drive it.
- **Schema evolution is frequency-driven** — promotion candidates surface from measurement frequency across corpus, not per-paper AI judgment.
- **Geometry-independent properties only** — only intrinsic material properties (sheet Lk, Jc-material, mean free path) are promotable to named columns. Geometry-dependent measurements (total Lk, Ic) stay in catchall.
- **Process variables vs signals** — Block 2 (deposition method, temperature, annealing) are inputs you control; Block 3 (Tc, RRR, T1) are outputs you measure.

---

*Last updated: April 28, 2026 (evening)*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
