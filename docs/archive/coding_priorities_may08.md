# C2QA QREM — Coding Priorities

*Updated May 8, 2026*

---

## Completed

- `derived_material` added to `fetch_samples()` API response in `serve_materials.py`
- Strip and scatter charts now group by `derived_material` instead of `film_material`
- `buildMaterialFilters()` colorMap populated for `derived_material` keys
- Chart x-axis labels now show clean chemical abbreviations (Ta, Al, Re) rather than long parenthetical names
- **Chart CSV export (#3)** — Download button on strip and scatter charts exports currently plotted data as CSV with active filters applied. `display_name` as identifier column. Pure frontend change.
- **Schema promotion (#1)** — `promote_fields.py` built and operational. Promotes catchall measurements into named SQLite columns using Claude for value extraction and unit conversion. Auto-patches `pipeline_mining.py` (FIELD_MAP, NAMED_COLUMNS, SELECT, NUMERIC_FIELDS) so Phase A immediately recognises new columns. Three fields promoted: `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K`. Phase A now has 19 sufficient evidence tables (was 15).

---

## Short Sessions — High Value

**1. Findings deduplication guard** — When a finding is approved in the Stage 4 UI, check `hypothesis_key` against existing `findings.jsonl` entries before writing. If already present, show a warning ("Previously approved on [date]") and offer to replace rather than append. In the Stage 4 review list, badge findings that match an existing `findings.jsonl` entry with a `↻ previously approved` or `↻ previously rejected` indicator so the reviewer knows at a glance which hypotheses have prior decisions. In the Explorer Findings tab, filter to show only the latest approved entry per `hypothesis_key` to prevent duplicate display. Keeps append-only guarantee — old entries are superseded, not deleted.

**2. Schema promotion UI** — Stage 4 sub-step in the ingestion pipeline UI surfacing measurement frequency report candidates for human approve/defer/reject. Approved promotions auto-trigger a `build_sqlite.py` rebuild and `promote_fields.py` run. Natural moment to surface candidates is immediately after Phase A runs, alongside the mining findings review.

**3. Extraction prompt fix for `film_material`** — Explicitly instruct Claude in the Pass 2 extraction prompt that `film_material` is the superconducting film identity only — no parenthetical junction or encapsulation context. Junction material goes in the junction fields. Encapsulation details go in fabrication notes. Affects new ingestions going forward; existing records already handled by `derived_material` normalization.

---

## Baby QREM UI Redesign — Two Parts, Do A Before B

**4. Part A — Declutter main UI (prerequisite for Part B)** — Move circuit analysis (gate counts, depth, locality score, hub qubits), simplifying assumptions, and hardware configuration details behind a "Circuit & Configuration" reference drawer or collapsed section. After declutter, the main screen shows only:

- Metric cards
- T1 sensitivity staircase chart
- T1/T2 sliders with error attribution bar

This creates the vertical space needed for the material deep dive drawer to push into without covering important content.

**5. Part B — Material deep dive bottom drawer** — Bottom drawer that pushes main content up when opened rather than overlaying it. Design principles:

- Triggered by clicking ε_T1 in the error attribution bar
- Shows T1 decomposed into TLS / quasiparticle / vortex / radiation channels
- Each channel labeled with its provenance tier (`[MEASURED]`, `[DERIVED]`, `[CLASS DEFAULT]`, `[ASSUMED]`)
- Upstream material property sliders (Qi, Tc, mean free path) that update main page metrics and staircase position in real time
- Staircase chart stays visible — it is the key visual for watching code distance threshold crossings as material sliders move
- Works on mobile: bottom drawer is a natural mobile pattern, push-up keeps metric cards and staircase in view

---

## Larger Items

**6. Loss mechanism attribution (QREM Stage 4)** — Break T1 into TLS / quasiparticle / vortex motion / radiation contributions using standard Tier 2 physics formulas:

- `T1_TLS ≈ Qi / (2πf)` — from internal quality factor
- `T1_QP` — from Tc via thermal activation: `n_qp ∝ exp(−1.76 Tc / T_operating)`
- `T1_vortex` — from mean free path relative to coherence length (clean vs dirty limit). Now has corpus support: approved finding shows dirty-limit Ta films have ~10× higher vortex activation temperature than clean-limit films.
- `T1_radiation` — class default if nothing relevant measured

Each channel labeled with its individual provenance tier. Does not require corpus mining findings — standard analytical formulas implementable now. Prerequisite for Part B (material deep dive drawer).

**7. Pluggable mapping model profiles** — Extend the YAML profile pattern to cover T1 decomposition models, following the same architecture as hardware profiles, QEC profiles, and interconnect profiles. New directory: `hardware_profiles/mapping_models/`. Allows different groups across the five centers to contribute their own models (e.g. a more sophisticated QP model from a group that has done extensive quasiparticle characterization) without touching core estimator code. First implementation: `t1_decomposition_analytical.yaml` containing the standard physics formulas from item #6.

**8. SI file linking** — Implement DOI-based naming convention so SI files ingest as part of the same logical record as the main paper. Convention: `{DOI_slug}_main.pdf` / `{DOI_slug}_SI.pdf`. Ingester recognizes the pattern, Pass 2 extraction has access to both documents, resulting record carries `source_files: [main, SI]`. Open question: SI files are often tables and figures without narrative context — may need adjusted prompt handling.

**9. RRR → T1 sensitivity sliders (QREM Stage 5)** — Add upstream material property sliders (RRR, Qi, loss tangent) that feed through Tier 2 mapping functions into T1/T2. The T1 sensitivity staircase becomes a material property sensitivity curve — "if I improve RRR from 10 to 50, what happens to my physical qubit count?" Depends on loss mechanism attribution (#6) being complete first.

---

## Longer Term / Vision

**10. Community upload feature** — Public Explorer with PDF upload capability allowing scientists to submit their own papers for ingestion. Key design notes:

- Requires real server infrastructure — not Render. AWS, university server, or Hugging Face Spaces with persistent storage.
- Architecture: upload queue → existing three-pass pipeline → record appears in Explorer
- Safety: file type validation, size limits, rate limiting per user. Pass 1 relevance check acts as content filter — irrelevant or nonsensical uploads logged as skipped.
- Scientific impact: changes the Explorer from a tool people use into a tool people contribute to. "Your paper might already be in here" becomes "submit your paper and see your data alongside the corpus."

**11. Materials Predictor** — Gaussian process regression per material class, connecting material properties to device performance predictions with uncertainty quantification.

**12. Tier 2 modular reconnection** — Reconnect modular overhead cost model (Arquin integration) when Center-wide architecture research matures. Functions already preserved in `estimator_tier2_modular.py`. `EstimationResult` retains all Tier 2 fields as `Optional`, defaulting to `None`.

---

## Key Design Principles (for reference)

- **Part A before Part B** — declutter main UI before adding material deep dive drawer
- **Staircase must stay visible when material drawer is open** — it shows code distance threshold crossings in real time
- **Bottom drawer pushes, not overlays** — main content slides up, nothing is hidden
- **Per-channel provenance** — T1 decomposition labels each channel individually with its tier, not a single label on the total
- **Schema promotion is frequency-driven** — geometry-independent (intrinsic) properties only; values already in catchall, promotion is just adding named columns
- **The estimator always estimates** — documents assumptions, flags uncertainty, never refuses to give a number
- **findings.jsonl is append-only** — supersede old entries by hypothesis_key, never mutate in place; Explorer filters to latest per key

---

*Updated May 8, 2026*
*C2QA QREM Project — developed in collaboration between C2QA center director and Claude (Anthropic)*