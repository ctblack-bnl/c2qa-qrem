# C2QA QREM — Project Architecture & Next Steps
## Continuity Document — May 5, 2026

---

## The Six Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | ✅ Materials-first estimation complete (May 2). T1/T2 → fidelity → code distance. T1 sensitivity curve. Auto-run UI. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | Operational. Three-pass pipeline. 98 papers, 155 samples, ~1,318 catchall items, 100% profile coverage. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | Live at https://c2qa-materials-explorer.onrender.com. Four tabs: Explore / Search / Findings / Catchall. Findings tab shows approved corpus mining results. |
| 4 | **Corpus Mining Pipeline** — AI-powered hypothesis extraction | Operational. Per-material-class stratification implemented May 5. 1 positive finding (Ta-Hf Tc vs deposition temperature). Human review UI in Stage 4. |
| 5 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 6 | **Materials-to-Device Mapping Layer** | Designed, not built. Corpus mining feeds it. First approved findings now in `findings.jsonl`. |

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
      |   → Hardware Profile Updater → qubit profile YAML   ← current (transitional)
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

## Baby QREM — Current State

**Materials-first estimation.** Gate fidelity is derived from material properties, not taken as input:

```
T1, T2 (sliders) + gate_time (fixed from profile)
  → ε_T1 = gate_time / T1
  → ε_T2 = gate_time / T2
  → ε_ctrl (fixed from clean baseline profile — engineering term, not materials)
  → ε_total → derived gate fidelity → code distance → physical qubits
```

Key design decision: ε_ctrl is derived once from the unmodified baseline profile and held constant regardless of slider changes. Without this, moving T1 slider would corrupt ε_ctrl and blur the code distance staircase.

**UI:** Auto-runs on load. T1 sensitivity curve (log y-axis, staircase labeled by code distance d). Error Attribution panel shows ε_T1/ε_T2/ε_ctrl decomposition. Running at `localhost:8000/scripts/qrem_ui.html`.

### What the Estimator Does NOT Yet Do (next priorities)

- **Loss mechanism attribution** — break T1 into TLS / quasiparticle / vortex motion / radiation contributions. Direct bridge to materials properties (RRR → quasiparticle, Qi → TLS). Makes Error Attribution scientifically complete.
- **RRR → T1 sensitivity** — once mapping functions exist from corpus mining, add RRR as upstream slider. T1 sensitivity curve becomes a material property sensitivity curve.
- **Readout fidelity** — in profile and loaded, not yet wired into QEC model.
- **T gate counting** — placeholder (0). Magic state factory underestimated for T-heavy circuits.

---

## Corpus Mining Pipeline — Current State (May 5)

### Architecture

Phase A (mechanical) → Phase B (AI reasoning) → Phase C (AI write-up) → Human review (Stage 4 UI) → `findings.jsonl`

### Per-Material-Class Stratification — Implemented May 5

**Key change:** Phase A now stratifies evidence tables by material identity, not cross-corpus. This was essential because cross-material hypothesis testing is confounded by material identity — finding that "high RRR correlates with high T1" across Ta and Al mixed together can't tell you if it's a real RRR→T1 relationship or just a material identity effect.

**Implementation:**
- `build_sqlite.py` now computes `derived_material` column — deterministic normalization of `film_material` using `normalize_film_material()`: strips parentheticals ("Ta (with Al/AlOx junction)" → "Ta"), checks against `KNOWN_MATERIALS` whitelist, everything else → "other"
- `KNOWN_MATERIALS` whitelist in `build_sqlite.py`: Ta, Nb, Al, Re, TiN, NbN, NbTiN, TaN, NbSe2, PtSi, Ta-Hf, Mo3Al2C
- Build output now shows ⚠ warning listing unrecognized film materials — surfaces new materials at ingestion time rather than silently accumulating them in "other"
- Phase A produces both global tables (cross-corpus) and per-material tables. "other" class is written to JSONL but never sent to Phase B.
- BCS gap terms in FIELD_MAP now map to `Tc_K` directly (not `derived_BCS_gap_meV`) — eliminates derived field artifacts while preserving the hypothesis

**Current corpus material breakdown:**
Ta (35), other (27), Al (16), unknown (13), NbSe2 (12), Re (12), Ta-Hf (12), PtSi (11), Mo3Al2C (5), NbN (5), TaN (2), Nb (1)

**Current mining results (May 5):**
- 41 correlations → 11 out of scope, 16 corpus gaps, 12 hypotheses matched
- 15 evidence tables sufficient for Phase B (global + per-class)
- 1 positive finding: Tc_K vs deposition_temperature in Ta-Hf (83:17), confidence 0.72
- Remaining: inconclusive (correct — zero variance in field, or single-paper confound)

### Similarity Profile Issue — Partially Resolved

The `backfill_similarity_profiles.py` script now has a `--filter PATTERN` flag to force-reprocess specific papers. Bug fixed: `build_profile_prompt()` now correctly flattens nested confidence/source dicts before sending to Claude. The NbSe2 (Zaman) samples still being assigned `other` rather than `niobium_diselenide` by the profile prompt — this is a cosmetic Explorer issue only (sidebar filter), not a mining correctness issue since Phase A now uses `derived_material` instead of `sim_material_class`.

---

## Materials Explorer — Current State (May 5)

Four tabs: **Explore → Search → Findings → Catchall**

**Findings tab** — read-only view of approved `findings.jsonl`. Cards show type badge, title, confidence, summary, clickable sample chips (supporting in green, complicating in red — each opens detail drawer). Full detail (finding detail text, key evidence prose, alternative explanations, next steps, QREM implications) is collapsible behind "▸ Show detail". Sorted: positive → negative → inconclusive → derived artifact, highest confidence first within type.

**Charts** — axis labels and ticks at size 13-14, color `#d0d8e0`. "Click any data point for full material information" hint above each chart.

---

## Data Provenance — SI Files and External Databases

*Architectural principle captured April 28 — not yet implemented, important to preserve.*

**Core insight: peer review is inherited, not intrinsic.** An SI file travels under the umbrella of its parent paper. External database entries inherit peer review credibility if traceable to a published paper via DOI.

**Provenance hierarchy (record level):**

| Source | Confidence | Rationale |
|---|---|---|
| Peer-reviewed paper (main text) | Highest | Full peer review, narrative context |
| SI file linked to paper via DOI | High | Same peer review umbrella |
| arXiv preprint | Medium-high | Author-accountable, not yet reviewed |
| External database entry with traceable DOI | Medium | Peer review inherited if link exists |
| External database entry, no traceable publication | Low | Unreviewed direct submission |
| Raw dataset repository (Zenodo, Figshare) | Variable | Depends on paper linkage |

**The SI linking problem (needs implementation):** Right now SI files are ingested as completely separate papers. Almost every paper has an SI, and SI files often contain the most detailed fabrication parameters. Proposed fix: DOI-based naming convention (`{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`) so the ingester treats them as a single logical record, Pass 2 has access to both documents, and the resulting record carries `source_files: [main, SI]`. Open question: SI files may need adjusted prompt handling — they're often just tables/figures without narrative context.

**Connection to external databases:** The prior C2QA materials database effort can be incorporated using the same provenance logic — entries traceable to a DOI get medium confidence; entries without a publication link get low confidence.

---

## Explorer Rollout Strategy

The Explorer is ready to share internally within C2QA. Key framing: "here's something I built that's been useful to me — want to try it?" rather than a commitment ask.

**What makes it compelling to a cold visitor:** 155 samples, Findings tab with approved scientific results, click-any-point to see full sample detail including DOI link. The hook: "your paper might already be in here."

**Non-threatening positioning for five-center working group:** The prior database effort probably failed because the database was the purpose — no pull for contributors. This one is different because QREM gives the data a job to do. Acknowledge prior work explicitly. Invite one or two people from the prior effort into schema governance early.

**Do not lead with QREM** when sharing externally — Baby QREM is still too early-stage to be a selling point. Let the Explorer stand on its own as a literature benchmarking and discovery tool.

---

## Coding Priorities — Next Sessions

### Track A: Mining + Schema

**1. Schema promotion implementation** — add `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K` as named columns in `build_sqlite.py`. Values already in `catchall_items.value` as clean numerics — no re-ingestion needed. Re-run Phase A after — expect more cross-sample evidence for these fields.

**2. Per-material-class Phase A — second pass** — now that `derived_material` is working, re-run Phase A after schema promotion (#1 above). The Bahrami Ta series (8 samples, wide mean free path range) is the most promising dataset for finding real within-material correlations.

**3. Stage 4 schema evolution UI** — surface measurement frequency report for human approval of field promotions.

**4. SI file linking** — implement DOI-based naming convention for SI files. See provenance section above.

### Track B: Baby QREM

**5. Loss mechanism attribution (Stage 4)** — break T1 into TLS / quasiparticle / vortex motion / radiation using standard analytical formulas. **Does NOT require corpus mining findings** — Tier 2 physics formulas (Qi → T1_TLS, RRR → T1_QP, mean free path → T1_vortex) are well-established and can be implemented now. Each contribution labeled with provenance tier. Corpus mining findings will validate/refine later.

**6. RRR → T1 sensitivity (Stage 5)** — upstream material property sliders feeding through Tier 2 mapping functions. T1 sensitivity curve becomes a material property sensitivity curve.

**7. Readout fidelity** — wire into QEC model (currently loaded but unused).

**8. T gate counting** — replace placeholder (0) with actual count from circuit analysis.

### Key design principle — Tiered Fallback Hierarchy (QREM spec v0.8)

The estimator always estimates. Every input follows a four-tier fallback:
- **Tier 1** `[MEASURED]` — directly in the paper
- **Tier 2** `[DERIVED]` — computed from measured quantities via physics formulas
- **Tier 3** `[CLASS DEFAULT]` — typical value for this material class
- **Tier 4** `[ASSUMED]` — baseline profile default

Core use case: ingest a paper, map whatever was measured to QREM inputs via the best available tier, always estimate, always show provenance. A film-only paper with no device measurements still produces a useful benchmark result. Full specification in QREM spec v0.8.

### Medium effort

**9. Ic/Jc disambiguation** — `derive.py` functions, schema columns, extraction prompt fix.

**10. Corpus expansion** — older literature ingestion.

### Larger effort

**11. Materials Predictor** — Gaussian process regression per material class.

**12. Tier 2 reconnection** — modular overhead, when Center-wide architecture research matures. Functions preserved in `estimator_tier2_modular.py`.

---

## Running the System

```bash
# Materials Explorer + Pipeline UI (port 8001)
cd ingester && python3 serve_materials.py
# Open http://localhost:8001/ingest_pipeline.html

# Baby QREM (port 8000)
cd "2026-04 c2qa_qrem" && python3 scripts/serve.py
# Open http://localhost:8000/scripts/qrem_ui.html

# Mining pipeline (after ingestion + build)
python3 pipeline_mining.py phase-a
python3 pipeline_mining.py phase-b
python3 pipeline_mining.py phase-c

# Rebuild SQLite after any JSONL changes
python3 build_sqlite.py

# Backfill similarity profiles for specific paper
python3 backfill_similarity_profiles.py --filter Zaman
python3 backfill_similarity_profiles.py --dry-run  # preview

# Standard commit
git add . && git commit -m "description" && git push
```

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — self-contained. The target architecture is QREM reading PUKs directly — no YAML export step. Current Explorer → YAML → QREM workflow is transitional.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. Every mining finding requires human review before entering `findings.jsonl`.
- **Sparse extraction** — absence = not reported, never zero.
- **Per-material stratification** — materials-to-device correlations must be tested within a material class, not cross-corpus. `derived_material` (deterministic, whitelist-based) drives Phase A stratification; `sim_material_class` (AI-generated) drives Explorer sidebar filter.
- **BCS gap maps to Tc** — `derived_BCS_gap_meV` is a deterministic transform of Tc_K. Author correlations mentioning "BCS gap" or "energy gap" are correctly mapped to `Tc_K` in FIELD_MAP.
- **Schema evolution is frequency-driven** — promotion candidates surface from measurement frequency across corpus, not per-paper AI judgment. Geometry-independent (intrinsic) properties only.
- **Materials-first estimation** — gate fidelity is an output, not an input. ε_ctrl is fixed from clean baseline profile and does not vary with T1/T2 slider changes.
- **The estimator always estimates** — documents assumptions, flags uncertainty, never refuses to give a number.
- **Peer review is inherited** — SI files and external database entries can carry peer review credibility if traceable to a published paper via DOI.

---

*Last updated: May 5, 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
