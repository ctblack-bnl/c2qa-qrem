# C2QA QREM — Project Continuity & Coding Priorities
## Updated June 28, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Stages 1–4 complete. T1 loss channel breakdown panel operational. ε_ctrl now specified directly in YAML rather than back-calculated. Live at https://c2qa-baby-qrem.onrender.com |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | ✅ Operational. Three-pass pipeline. Prompt updated May 23 for participation matrix papers. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | ✅ Live at https://c2qa-materials-explorer.onrender.com. Five tabs: Explore, Search, Findings, Catchall, Papers. |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | ✅ Operational. Run May 22 — see Mining State below. |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | `t1_decomposition.py` complete and validated. UI panel integrated. Per-material corpus-average defaults wired in. **New priority: extract mapping layer as standalone feed-anything service — see Track D below.** |

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
      |── Measured device performance (T1, T2, gate fidelity)
      |   → Hardware Profile Updater → qubit profile YAML   ← transitional
      |   [target: QREM reads PUKs directly, no YAML step]
      |                                        ↓
      |── All corpus records              [1] Baby QREM
      |   → [4] Corpus Mining Pipeline        ↑
      |        → findings.jsonl               |
      |        → [6] Mapping Layer ───────────┘
      |                    |
      |                    └── [standalone API — feeds any tool]
      |                         Microsoft QRE, Stim, HetArch, etc.
      |
      └── Material properties (Tc, RRR, loss tangent)
          → [5] Materials Predictor → [6] Mapping Layer
```

**The scientific question the pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and run this quantum circuit, how many physical qubits do I need?"*

---

## Recent Completions (June 12, 2026)

### Demo Prep — Baby QREM UI Improvements

Several UI improvements made in preparation for C2QA leadership demo:

- **Metric card expand text rewritten** — all 5 cards now tell a clean left-to-right story: material gives p → success rate + depth give target LER → p and LER determine d → d determines overhead → times logical qubits = total physical qubits
- **Chart title simplified** — "Physical qubit count needed vs. T1 relaxation time" with subtitle "Each step down = a lower code distance threshold crossed"
- **Circuit details moved** — from buried Reference Details section to a `▸ circuit details` turndown directly under the circuit dropdown. Zero vertical space when collapsed.
- **`epsilon_control` now directly specified in YAML** — `transmon_baseline_2026.yaml` now has `epsilon_control: 0.000583` as a first-class field. `_derive_control_error_baseline()` reads it directly with fallback to back-calculation for legacy profiles. Cleaner conceptually — ε_ctrl is a property of the control electronics, not back-calculated from fidelity.
- **`measured_fields` added to corpus-average YAMLs** — `compute_class_defaults.py` now populates `measured_fields` list in provenance so UI shows `[MEASURED]` rather than `[ASSUMED]` for corpus-averaged T1/T2. Manual patch applied to `Ta_corpus_average.yaml`.
- **BV circuit added** — `bv_7qubit.qasm` (Bernstein-Vazirani, 7 qubits, hidden string 101101) added to `data/circuits/`. Good demo circuit with clean intuitive explanation.
- **`compute_class_defaults.py` auto-call** — added to end of `build_sqlite.py` so corpus-average YAMLs regenerate automatically after every DB rebuild.

### Leadership Demo — June 2026

Baby QREM and Materials Explorer presented to C2QA leadership. Key takeaways:

- QEC experts found Baby QREM too simplistic for their work — expected, and not the target audience
- General reception modest but not discouraging
- **Strategic reframing decided:** Baby QREM serves two distinct purposes: (1) education and communication for non-experts across the center, (2) a materials data pipeline that feeds any resource estimation tool. The mapping layer specifically should be extracted as a standalone service.

### DOE Demo Prep — Explorer UI Fixes and Papers Tab (June 15, 2026)

Several fixes and additions made in preparation for DOE monthly meeting demo:

- **Papers tab added** — fifth tab in the Explorer showing all papers that contributed samples to the corpus. Sortable by author or sample count; each row has a clickable DOI link. Backed by a new `/api/papers` endpoint in `serve_materials.py`.
- **Unknown sidebar filter fixed** — "unknown" samples are now controlled by an explicit checkbox in the material filter sidebar (checked by default, uncheck to hide unclassified samples). Root cause: duplicate `onFilterChange` function; sidebar was also incorrectly filtering on `sim_material_class` instead of `derived_material`, which is what the chart actually uses for grouping.
- **Material colors preserved on group-by switch** — when switching the strip/scatter chart group-by from "Film material" to "Substrate" or "Deposition method", data points now retain their material-class colors rather than switching to substrate/deposition colors. Makes cross-group comparisons much more readable.

---

## Next Coding Priorities

### Priority 1 — Wire Corpus Averages into Stage 4 Panel (Track A)

The corpus-average YAMLs are generated and `generate_qubit_profile.py` routes to them correctly. But existing corpus-derived profiles in `qrem/hardware_profiles/qubits/` still point to old defaults paths. Two steps:

1. **Regenerate all corpus profiles** — batch script calling `generate_qubit_profile.py` for all samples in the DB.
2. **Stage 5 — Material property sliders** — tan_delta, p_MS_pad sliders running forward through `t1_decomposition.py` → predicted T1 → staircase.

### Priority 2 — Centralized Field Registry (Track B)

The same field name mappings maintained in four places. A shared `schema_fields.py` would define canonical field names, fallback chains, and text→field mappings once. Design requires care — deliberate design session needed before coding.

### Track A: Baby QREM

**3. Decomposition panel: Qi path** — when `Qi` and `p_MS_resonator` are both non-null, `t1_decomposition.py` can derive tan_delta. Panel should show for these profiles. Currently only tan_delta gates the panel.

**4. Stage 5 — Material property sliders** — see Priority 1 above.

**5. Readout fidelity** — wire into QEC model (currently loaded but unused).

**6. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Explorer

**7. Batch profile regeneration** — script to regenerate all corpus-derived qubit profiles in `qrem/hardware_profiles/qubits/` so they point to material-specific defaults. Currently requires manual Explorer clicks per sample.

**8. Missing correlation: Yang 2026 Ta-Hf deposition temperature vs Tc** — Table 2 of the PNAS paper shows monotonic Tc suppression from 550→850°C, but current ingestion missed this as a correlation item. The finding remains in `findings.jsonl` but is unsupported by the live corpus.

**9. Extraction prompt fix: normal_state_resistivity_uOhm_cm** — Bahrami 2026 and Yang 2026 resistivity values in catchall rather than named field. `build_sqlite.py` fallback in place — once prompt fixed and papers re-ingested, derived sheet resistance coverage improves significantly.

**10. Prev/next navigation in sidecar footer** — ← → arrows to cycle through samples in current filtered set.

**11. Exclusions UI** — management interface for `exclusions.json` in pipeline UI. Currently requires manual JSON editing.

**12. SI file linking** — DOI-based naming: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Do not ingest SI files as standalone in the meantime.

**13. Corpus expansion** — older literature ingestion. Collection in progress.

### Track C: Longer Term

**14. Community upload feature** — public Explorer with PDF upload.

**15. Materials Predictor** — Gaussian process regression per material class.

**16. Tier 2 modular reconnection** — reconnect modular overhead cost model (Arquin) when Center-wide architecture research matures.

### Track D: Standalone Mapping Layer — NEW PRIORITY

**Strategic decision from June 2026 leadership meeting:** Extract the Materials-to-Device Mapping Layer as a standalone, feed-anything service. This is potentially the highest-impact next step.

**The vision:**
```
Materials Explorer (Tc, RRR, loss tangent, mean free path)
         ↓
[Mapping Layer API] — standalone service
         ↓
  predicted T1, T2, gate fidelity + provenance
         ↓
    ↙              ↘
Baby QREM      Microsoft QRE / Stim / HetArch / anything
```

**Why this matters:** Right now sophisticated resource estimation tools have to assume qubit parameters or use a handful of well-known published values. The mapping layer offers a systematic, citable, corpus-backed source of material-to-device predictions. Baby QREM becomes one consumer among many rather than the only destination.

**Design questions to resolve in next session:**
- What is the API contract? (inputs, outputs, format)
- How does provenance flow through to the consumer tool?
- What is the relationship to the existing `t1_decomposition.py`?
- Should this be a REST endpoint on the Explorer server, or a separate service?

---

## Key Scientific Insights (June 12, 2026)

**On ε_ctrl as the fundamental floor:**
- With ε_ctrl = 5.83e-4, the physical error rate has a floor regardless of how good T1 and T2 get. This sets a minimum achievable code distance for any given circuit and success rate. For 99% success on depth-11 circuits, the floor is d=5 — already reachable. For 99.99%, the floor is d=9 — unreachable no matter how good the material. Better materials shift the error budget fractions but cannot break through the ε_ctrl floor.
- **Demo insight:** when ε_ctrl is 58% of the error budget (as at T1=200µs), the tool is correctly diagnosing that the bottleneck has shifted from materials to control engineering. This is a real scientific output, not a limitation.

**On Baby QREM's scope and positioning:**
- Baby QREM is intentionally simplified — single-module, analytical QEC, no idling errors, no time-domain simulation. This is by design, not a gap to close.
- The Microsoft Azure Quantum Resource Estimator is more complete on the QEC side. Baby QREM's differentiator is the materials-first entry point and C2QA corpus connection — not competition with Stim.
- Target audiences: (1) materials scientists who need intuition for how T1 improvements translate to computational resources; (2) any resource estimation tool that needs corpus-backed material-to-device predictions.

**On what Baby QREM doesn't model (honest accounting):**
- Idling errors — qubits accumulate decoherence while waiting, not just during gates
- Per-qubit error rates — currently one global error rate for the whole circuit
- Time-domain circuit execution — depth is a proxy, not a simulation
- Classical feedback latency for syndrome processing
- Magic state factories (placeholder only)
- SWAP routing overhead

**On the shallow circuit problem:**
- Current demo circuits (depth 8-11) are too shallow to stress the resource estimation meaningfully — we're always near the bottom of the staircase. This is honest: these circuits are near-term demos, not the fault-tolerant era algorithms Baby QREM is really designed for. Frame it as: "These simple circuits let you see the machinery clearly. The real use case is planning hardware for algorithms that don't exist as working code yet."

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Exclusions are build-time overlays** — `exclusions.json` excludes records from the SQLite view without touching the JSONL.
- **Records are PUKs** — self-contained. Target architecture: QREM reads PUKs directly, no YAML step.
- **AI proposes, humans approve** — every extracted value has confidence + source citation.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — correlations tested within material class. `derived_material` drives Phase A and Explorer sidebar filtering; `sim_material_class` is no longer used for sidebar filtering (bug fixed June 15).
- **Schema evolution is frequency-driven** — geometry-independent properties only.
- **Materials-first estimation** — gate fidelity is an output, not an input.
- **ε_ctrl is fixed to the controls baseline** — now directly specified in YAML rather than back-calculated. Corpus profiles contribute T1 and T2 only. ε_ctrl = 5.83e-4, always.
- **The estimator always estimates** — tiered fallback: `[MEASURED]` → `[DERIVED]` → `[CORPUS AVERAGE]` → `[CLASS DEFAULT]` → `[ASSUMED]`.
- **Stage 4 decomposition panel is read-only** — disappears when sliders touched. Stage 5 adds forward-direction material sliders.
- **Resonator is calibration, not loss channel** — v2.5 model. Qi → tan_delta → pad T1, never Qi/ω directly as qubit T1.
- **General solutions over one-offs** — new derived fields follow the established `derived_X` fallback pattern.
- **Don't ingest SI files as standalone** — wait for SI file linking implementation.
- **Prompt evolution: resist whack-a-mole** — only add guidance that fires on multiple paper types, not one-off fixes for individual papers.
- **Per-material defaults over single general defaults** — `{Material}_material_defaults.yaml` files replace the single `transmon_general_defaults.yaml` as the corpus grows. General defaults remain as fallback of last resort.
- **Repo structured for audience** — `explorer/` for materials contributors, `qrem/` for QEC/algorithms contributors. Each has its own README with plugin points for expert integration.
- **Mapping layer feeds anything** — NEW: the materials-to-device mapping layer is a standalone service, not a Baby QREM internal component. Baby QREM is one consumer among many.

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd explorer && python3 serve_materials.py

# Baby QREM (port 8000)
cd qrem/scripts && python3 serve.py

# Rebuild SQLite after any JSONL, build_sqlite.py, or exclusions.json changes
cd explorer && python3 build_sqlite.py

# Regenerate per-material corpus-average YAMLs (run after build_sqlite.py)
cd explorer && python3 compute_class_defaults.py

# Backfill similarity profiles — ALWAYS check line counts before swapping
cd explorer
python3 backfill_similarity_profiles.py --filter <pattern>
wc -l ../data/ingested/records_with_profiles.jsonl  # must match records.jsonl
wc -l ../data/ingested/records.jsonl
# Only if counts match:
mv ../data/ingested/records.jsonl ../data/ingested/records_backup.jsonl
mv ../data/ingested/records_with_profiles.jsonl ../data/ingested/records.jsonl
python3 build_sqlite.py

# Standard commit
git add . && git add ../data/ingested/records.db && git commit -m "description" && git push

# Find and remove ledger entries for re-ingestion
python3 -c "import json; ledger = json.load(open('../data/ingested/processed_ledger.json')); entries = ledger.get('processed', []); [print(repr(e['filename'])) for e in entries if 'keyword' in (e.get('filename') or '').lower()]"
```

---

*Last updated: June 28, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
