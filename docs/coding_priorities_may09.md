# C2QA QREM — Coding Priorities

*Updated May 9, 2026*

---

## Completed

- `derived_material` added to `fetch_samples()` API response in `serve_materials.py`
- Strip and scatter charts now group by `derived_material` instead of `film_material`
- `buildMaterialFilters()` colorMap populated for `derived_material` keys
- Chart x-axis labels now show clean chemical abbreviations (Ta, Al, Re) rather than long parenthetical names
- **Chart CSV export** — Download button on strip and scatter charts exports currently plotted data as CSV with active filters applied. `display_name` as identifier column. Pure frontend change.
- **Schema promotion** — `promote_fields.py` built and operational. Promotes catchall measurements into named SQLite columns using Claude for value extraction and unit conversion. Auto-patches `pipeline_mining.py` (FIELD_MAP, NAMED_COLUMNS, SELECT, NUMERIC_FIELDS) so Phase A immediately recognises new columns. Three fields promoted: `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K`. Phase A now has 19 sufficient evidence tables (was 15).
- **Findings deduplication guard** — `↻ previously approved` badges in Stage 4 review list. Inline warning + Replace button when approving a finding whose `hypothesis_key` already exists in `findings.jsonl`. Explorer Findings tab now reads from canonical `findings.jsonl` via `/api/approved_findings` endpoint (deduplicated, latest wins). Append-only guarantee preserved.
- **Schema promotion UI** — Stage 4 candidates section auto-loads alongside findings. Cards show field name and frequency. Promote triggers `promote_fields.py --field` + `build_sqlite.py` rebuild. Defer hides card for session. Candidates filtered to fields defined in `promote_fields.py` that are not yet in schema — prevents garbage geometry/device terms from surfacing.
- **Extraction prompt fix for `film_material`** — Pass 2 prompt now explicitly instructs Claude that `film_material` is the superconducting film identity only. Junction material goes in `junction_material` field. Removed the example that was actively instructing Claude to use parenthetical notation (`Ta (with Al/AlOx junction)`).
- **Baby QREM Part A UI declutter** ✅ Complete (May 9) — Full layout compaction and clutter reduction:
  - Circuit Analysis and Simplifying Assumptions moved into `▸ Reference Details` collapsible at bottom of left panel (hidden by default, accessible when needed)
  - Error Attribution panel made full-width single column (was two-column with Circuit Analysis alongside)
  - Top table removed from Error Attribution (T1, T2, Gate time, T1-limited ceiling, Derived fidelity) — all redundant with sliders and metric cards
  - Gate Error Decomposition bar + ε_T1/ε_T2/ε_ctrl breakdown is now the sole Error Attribution content
  - ε_T1 row styled with cursor pointer and `▸` affordance — marked as Part B drawer trigger
  - Section labels shortened: "T1 — Energy Relaxation Time" → "T1", "T2 — Dephasing Time" → "T2", "Target Circuit Success Rate" → "Success Rate"
  - Header padding reduced; chart padding tightened; metric card padding and font size reduced
  - Status bar slimmed — platform item removed (was never actionable); JS reference cleaned up
  - Derived Fidelity metric card restored (was missing from `updateCards()`)

---

## Baby QREM UI Redesign — Next: Part B

**1. Part A — Declutter main UI ✅ Complete (May 9)**

**2. Part B — Material deep dive bottom drawer** — Bottom drawer that pushes main content up when opened rather than overlaying it. Prerequisite: Loss mechanism attribution backend (item 3 below) must be implemented first so the drawer has physics to show. Design principles:

- Triggered by clicking ε_T1 in the Gate Error Decomposition section (affordance already in place)
- Shows T1 decomposed into TLS / quasiparticle / vortex / radiation channels
- Each channel labeled with its individual provenance tier (`[MEASURED]`, `[DERIVED]`, `[CLASS DEFAULT]`, `[ASSUMED]`)
- Upstream material property sliders (Qi, Tc, mean free path) that update main page metrics and staircase position in real time
- Staircase chart stays visible — it is the key visual for watching code distance threshold crossings as material sliders move
- Works on mobile: bottom drawer is a natural mobile pattern, push-up keeps metric cards and staircase in view

**Sequencing for next session:**
1. First: implement Stage 4 backend in `estimator.py` (item 3 below) — pure Python, no HTML needed
2. Then: build Part B drawer UI on top of that

---

## Larger Items

**3. Loss mechanism attribution (QREM Stage 4)** — Break T1 into TLS / quasiparticle / vortex motion / radiation contributions using standard Tier 2 physics formulas:

- `T1_TLS ≈ Qi / (2πf)` — from internal quality factor
- `T1_QP` — from Tc via thermal activation: `n_qp ∝ exp(−1.76 Tc / T_operating)`
- `T1_vortex` — from mean free path relative to coherence length (clean vs dirty limit). Now has corpus support: approved finding shows dirty-limit Ta films have ~10× higher vortex activation temperature than clean-limit films.
- `T1_radiation` — class default if nothing relevant measured

Each channel labeled with its individual provenance tier. Does not require corpus mining findings — standard analytical formulas implementable now. Prerequisite for Part B (material deep dive drawer).

**4. Pluggable mapping model profiles** — Extend the YAML profile pattern to cover T1 decomposition models, following the same architecture as hardware profiles, QEC profiles, and interconnect profiles. New directory: `hardware_profiles/mapping_models/`. Allows different groups across the five centers to contribute their own models without touching core estimator code. First implementation: `t1_decomposition_analytical.yaml` containing the standard physics formulas from item #3.

**5. SI file linking** — Implement DOI-based naming convention so SI files ingest as part of the same logical record as the main paper. Convention: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Ingester recognizes the pattern, Pass 2 extraction has access to both documents, resulting record carries `source_files: [main, SI]`. Open question: SI files are often tables and figures without narrative context — may need adjusted prompt handling.

**6. RRR → T1 sensitivity sliders (QREM Stage 5)** — Add upstream material property sliders (RRR, Qi, loss tangent) that feed through Tier 2 mapping functions into T1/T2. The T1 sensitivity staircase becomes a material property sensitivity curve — "if I improve RRR from 10 to 50, what happens to my physical qubit count?" Depends on loss mechanism attribution (#3) being complete first.

---

## Longer Term / Vision

**7. Community upload feature** — Public Explorer with PDF upload capability allowing scientists to submit their own papers for ingestion. Key design notes:

- Requires real server infrastructure — not Render. AWS, university server, or Hugging Face Spaces with persistent storage.
- Architecture: upload queue → existing three-pass pipeline → record appears in Explorer
- Safety: file type validation, size limits, rate limiting per user. Pass 1 relevance check acts as content filter — irrelevant or nonsensical uploads logged as skipped.
- Scientific impact: changes the Explorer from a tool people use into a tool people contribute to. "Your paper might already be in here" becomes "submit your paper and see your data alongside the corpus."

**8. Materials Predictor** — Gaussian process regression per material class, connecting material properties to device performance predictions with uncertainty quantification.

**9. Tier 2 modular reconnection** — Reconnect modular overhead cost model (Arquin integration) when Center-wide architecture research matures. Functions already preserved in `estimator_tier2_modular.py`. `EstimationResult` retains all Tier 2 fields as `Optional`, defaulting to `None`.

---

## Key Design Principles (for reference)

- **Stage 4 backend before Part B frontend** — drawer needs physics engine before UI
- **Staircase must stay visible when material drawer is open** — it shows code distance threshold crossings in real time
- **Bottom drawer pushes, not overlays** — main content slides up, nothing is hidden
- **Per-channel provenance** — T1 decomposition labels each channel individually with its tier, not a single label on the total
- **Schema promotion is frequency-driven** — geometry-independent (intrinsic) properties only; values already in catchall, promotion is just adding named columns. New fields surface automatically once defined in `promote_fields.py`.
- **The estimator always estimates** — documents assumptions, flags uncertainty, never refuses to give a number
- **findings.jsonl is append-only** — supersede old entries by hypothesis_key, never mutate in place; Explorer filters to latest per key
- **film_material is superconducting film identity only** — junction material goes in `junction_material`; existing records handled by `derived_material` normalization

---

*Updated May 9, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*
