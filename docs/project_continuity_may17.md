# C2QA QREM — Project Continuity & Coding Priorities
## Updated May 17, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Materials-first estimation complete. T1/T2 → fidelity → code distance. T1 sensitivity curve. Auto-run UI. Part A declutter complete. **Stage C complete (May 17): t1_decomposition wired into estimator, channel breakdown in API response.** |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | ✅ Operational. Three-pass pipeline. max_tokens = 64000. qubit_frequency_GHz added to prompt and database (May 17). |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | ✅ Live at https://c2qa-materials-explorer.onrender.com. 226 samples, 100% profile coverage. Select All / None material filter added (May 17). |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | ✅ Operational. 1 positive finding (Ta-Hf Tc vs deposition temperature). |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | ✅ Stage C complete (May 17). t1_decomposition.py integrated into estimator.py. Channel breakdown (pad TLS, junction TLS, QP, radiation) returned in every /api/estimate response. |

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
      |
      └── Material properties (Tc, RRR, loss tangent)
          → [5] Materials Predictor → [6] Mapping Layer
```

**The scientific question the pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and run this quantum circuit, how many physical qubits do I need?"*

---

## Recent Completions (May 17, 2026)

### Stage C — t1_decomposition integrated into estimator.py

`compute_t1_decomposition()` now runs automatically inside `run_estimation()` for every estimate. The full channel breakdown is returned in the `/api/estimate` response under the `t1_decomposition` key.

**Integration architecture:**
- `run_estimation()` builds an adapter dict translating qubit profile structure → material record structure that `compute_t1_decomposition()` expects
- Key mapping: `coherence.T1_us` → `measured.T1_us`, `materials.*`, `device.*`, `surface_participation.*`
- Defaults file resolved via `provenance.defaults_path` in the qubit profile YAML (relative to qubits/ directory)
- Non-fatal: if defaults file not found or decomposition fails, estimation continues normally with `t1_decomposition: null`
- `EstimationResult` has new `t1_decomposition: Optional[dict]` field; passes through `to_dict()` automatically

**Verified working:** Network tab confirms `t1_decomposition` block appears in API response with `T1_provenance: "MEASURED"` for Joshi and Bland profiles.

### Extended Qubit Profile YAML Schema

`generate_qubit_profile.py` now writes three new optional sections alongside `coherence` and `gates`:

```yaml
materials:              # Raw material properties for t1_decomposition
  Tc_K: 0.7            # [MEASURED] or null
  Qi: null
  Q_TLS_0: null
  mean_free_path_nm: null

device:                 # Device parameters
  f_qubit_GHz: 2.736   # [MEASURED] or null

surface_participation:  # FEM-derived geometry
  p_MS_pad: 0.00013    # [MEASURED] or null
  p_MS_resonator: null
```

`provenance.defaults_path` added — points to `transmon_analytical_defaults.yaml` relative to qubits/ directory, so `run_estimation()` can find defaults at runtime.

### qubit_frequency_GHz Added to Database and Prompt

- `build_sqlite.py`: `qubit_frequency_GHz` and `Q_TLS_0` added as named columns
- `prompts.py`: `qubit_frequency_GHz` added to extraction schema with guidance
- Joshi 2026 and Bland 2025 re-ingested — frequencies now populated as named fields
- Verified: Joshi_2026_Qubit-2 shows `f_qubit_GHz: 2.736 [MEASURED]` in dry-run

### Explorer UI — Select All / None Material Filter

Two links added to the material filter section header: **All** and **None**.
- None → unchecks all materials, shows nothing (correct behavior for focus workflow)
- All → restores full corpus view
- Bug fix: `getFilteredSamples()` now distinguishes "all checked" (show all) from "none checked" (show nothing) via `checkedMaterials.length < totalMaterials` guard

### records.jsonl Restored

`records.jsonl` was missing (lost during May 16 backfill swap). Restored from `records_backup2.jsonl` (127 papers, 264 raw samples → 226 after deduplication). Database rebuilt successfully. All 226 samples confirmed in Explorer.

---

## Next Coding Priorities

### Track A: Baby QREM

**1. Part B drawer UI (Stage 4b)** — bottom drawer triggered by clicking ε_T1 in Error Attribution panel (affordance already in place). Shows T1 decomposed into channels with per-channel provenance and values. Key design decisions:
- Pushes content up, does not overlay — staircase must stay visible
- Log-scale bar chart showing T1 per channel (pad TLS, junction TLS, QP, radiation)
- Per-channel provenance badges ([MEASURED], [DERIVED], [CLASS_DEFAULT], [ASSUMED])
- Harmonic sum shown as T1_total — the channel with shortest T1 is the bottleneck
- Read-only first (no new sliders) — Stage 5 adds upstream material sliders later
- Scientific insight: when T1_pad gets very long, other channels (junction, radiation) become the limit — shows scientist where to focus next
- T1 ceiling from defaults: ~450µs given current class defaults (junction ~1000µs, radiation ~5000µs, QP ~1000µs)
- No slider constraints needed — the bar chart makes the physics self-evident

**Implementation approach:** Look at actual `t1_decomposition` JSON from network tab first, design drawer around real data shape, then write HTML/CSS/JS in `qrem_ui.html`.

**2. Stage 5 — Upstream material property sliders** — Qi, Tc, mean free path sliders feeding through Tier 2 mapping functions into T1. Depends on Part B drawer existing first.

**3. Readout fidelity** — wire into QEC model (currently loaded but unused).

**4. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Track B: Ingester / Mining

**5. SI file linking** — DOI-based naming convention: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Ingester recognizes pair and ingests as single logical record with `source_files: [main, SI]`. **Do not ingest Bland SI as standalone — wait for this feature.**

**6. Corpus expansion** — older literature ingestion. Collection in progress.

**7. Ic/Jc disambiguation** — `derive.py` functions, schema columns, extraction prompt fix.

### Track C: Longer Term

**8. Community upload feature** — public Explorer with PDF upload.

**9. Materials Predictor** — Gaussian process regression per material class.

**10. Tier 2 modular reconnection** — reconnect modular overhead cost model (Arquin) when Center-wide architecture research matures.

---

## Key Scientific Insights (May 17)

**On the T1 channel bottleneck:**
- When pad TLS improves sufficiently, junction TLS and radiation become the limiting channels
- Current class defaults imply T1 ceiling ~450µs (1/T1_max = 1/1000 + 1/5000 + 1/1000)
- Bar chart visualization makes this immediately actionable: scientist can see when pad is no longer the bottleneck and should shift focus to junction quality or packaging

**On p_MS and the resonator → qubit chain (carried forward from May 16):**
- p_MS_resonator varies 30x across typical resonator geometries (CPW gap 2-16µm)
- Gold standard: fit Q_TLS,0 vs p_MS across many resonators → extract tan_delta directly
- Bland Figure S5 is definitive proof: resonator Q_TLS,0 and transmon Q lie on same line vs p_MS

**On TLS saturation (carried forward):**
- Model uses single-photon tan_delta → will systematically underpredict T1 for good qubits
- Correct behavior, not a bug — TLS partially saturates at qubit operating power

---

## Data Provenance Principles

**Peer review is inherited, not intrinsic.**

| Source | Confidence |
|---|---|
| Peer-reviewed paper (main text) | Highest |
| SI file linked to paper via DOI | High |
| arXiv preprint | Medium-high |
| External database entry with traceable DOI | Medium |
| External database entry, no traceable publication | Low |

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — self-contained. Target architecture: QREM reads PUKs directly, no YAML step.
- **AI proposes, humans approve** — every extracted value has confidence + source citation.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — correlations tested within material class. `derived_material` drives Phase A; `sim_material_class` drives Explorer sidebar.
- **Schema evolution is frequency-driven** — geometry-independent properties only.
- **Materials-first estimation** — gate fidelity is an output, not an input. ε_ctrl fixed from clean baseline.
- **The estimator always estimates** — tiered fallback: `[MEASURED]` → `[DERIVED]` → `[CLASS DEFAULT]` → `[ASSUMED]`.
- **Explorer is the Explorer** — literature database and discovery tool, not a physics inference engine.
- **Resonator is calibration, not loss channel** — v2.5 model. Qi → tan_delta → pad T1, never Qi/ω directly as qubit T1.
- **Qubit profile YAML stores only what the paper reported** — decomposition runs at estimation time, not at profile generation time. Predicted T1 is computed live, never baked into the YAML.

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py

# Baby QREM (port 8000)
cd "2026-04 c2qa_qrem" && python3 scripts/serve.py

# Rebuild SQLite after any JSONL or build_sqlite.py changes
cd ingester && python3 build_sqlite.py

# T1 decomposition (validation)
cd src/qrem
python3 t1_decomposition.py hardware_profiles/mapping_models/example_material_record.yaml hardware_profiles/mapping_models/transmon_analytical_defaults.yaml

# Generate qubit profile (dry-run)
cd ingester
python3 generate_qubit_profile.py "Joshi_2026_Qubit-2" --dry-run

# Remove papers from processed ledger for re-ingestion
python3 -c "
import json
ledger = json.loads(open('../data/ingested/processed_ledger.json').read())
entries = ledger.get('processed', [])
keep = [e for e in entries if e.get('filename') not in ('paper1.pdf', 'paper2.pdf')]
ledger['processed'] = keep
open('../data/ingested/processed_ledger.json', 'w').write(json.dumps(ledger, indent=2))
"

# Backfill similarity profiles — ALWAYS check line counts before swapping
python3 backfill_similarity_profiles.py --filter <pattern>
wc -l ../data/ingested/records_with_profiles.jsonl  # must match records.jsonl
wc -l ../data/ingested/records.jsonl
# Only if counts match:
mv ../data/ingested/records.jsonl ../data/ingested/records_backup.jsonl
mv ../data/ingested/records_with_profiles.jsonl ../data/ingested/records.jsonl
python3 build_sqlite.py

# Standard commit
git add . && git add ../data/ingested/records.db && git commit -m "description" && git push
```

---

*Last updated: May 17, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
