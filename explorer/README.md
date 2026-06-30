# C2QA Materials Explorer

A searchable database of superconducting materials characterization data, automatically extracted from the published literature using a three-pass AI pipeline.

**Live database: https://c2qa-materials-explorer.onrender.com** — browse without installing anything.

---

## What it does

The Explorer has two parts that work together:

**Ingestion pipeline** — reads scientific papers (PDFs) and automatically extracts structured materials characterization data: superconducting properties (Tc, RRR, sheet resistance), microwave performance (Qi, Q_TLS,0, loss tangent), qubit coherence (T1, T2), fabrication parameters, and more. Three passes per paper: relevance classification, full structured extraction, and semantic similarity profile generation.

**Browser UI** — four tabs:
- **Explore** — strip and scatter plots across the full corpus, filterable by material, substrate, deposition method
- **Search** — ranked and similarity search across records
- **Findings** — approved corpus mining findings (AI-extracted materials-to-device hypotheses, human-reviewed)
- **Catchall** — all extracted measurements that don't fit named schema fields, searchable by type

---

## Running locally

```bash
cd explorer
export PROVIDER=claude
export AZURE_CLAUDE_API_KEY=your-key-here
export AZURE_CLAUDE_BASE_URL=https://your-endpoint.services.ai.azure.com/anthropic
export AZURE_CLAUDE_DEPLOYMENT=claude-sonnet-4-6
python3 serve_materials.py
```

Open http://localhost:8001/materials_explorer.html for the Explorer, or http://localhost:8001/ingest_pipeline.html for the ingestion pipeline UI.

**Dependencies:**
```bash
pip install anthropic pyyaml python-dotenv
```

---

## Ingesting papers

The ingestion pipeline UI (`ingest_pipeline.html`) walks through four stages:

1. **Ingest** — drop PDFs in `data/papers/`, select the directory, click Start. Papers already processed are skipped automatically (DOI-primary idempotency).
2. **Review duplicates** — side-by-side comparison of arXiv preprint / published version pairs.
3. **Build database** — one click. Warns on unrecognized film materials.
4. **Mine corpus** — runs Phase A (evidence extraction) → B (AI reasoning) → C (AI write-up). Human review: Accept / Send Back / Reject.

The canonical data store is `data/ingested/records.jsonl` — append-only, never modified. SQLite (`records.db`) is derived and rebuildable at any time.

---

## Data schema

Records follow a six-block schema defined in `docs/materials_characterization_schema_vNN.md`:

- Block 1 — record metadata (provenance, DOI, review status)
- Block 2 — sample description (substrate, film, junction, R vs T geometry)
- Block 3 — structured measurements (~50 named fields with device-performance mappings)
- Block 4 — device performance implications (implied T1, code distance)
- Block 5 — catch-all (additional measurements, anomalous observations, author-stated correlations)
- Block 6 — similarity profile (8-dimension semantic tags for corpus search)

The catch-all is a first-class output — the 41 author-stated correlations in the current corpus are the primary evidence base for the corpus mining pipeline.

---

## Contributing

**Adding papers to the corpus** — drop PDFs in `data/papers/` and run the ingestion pipeline. Papers with C2QA acknowledgments or superconducting materials content (Ta, Nb, Al, TiN, NbTiN, Re, NbN, NbSe2, PtSi) are classified as high or medium relevance and extracted automatically.  Human review is essential before using extracted records in quantitative analysis.

**Improving extraction quality** — the extraction prompt is in `prompts.py` (Pass 2). The relevance classifier is also there (Pass 1). Follow the prompt evolution philosophy in the spec: only add guidance general enough to fire on multiple paper types, not one-off fixes for individual papers.

**Schema evolution** — fields are promoted from the catch-all to named database columns based on measurement frequency across the corpus. Add new fields in `build_sqlite.py` and update the FIELD_MAP in `pipeline_mining.py`. See `docs/materials_characterization_schema_vNN.md` for the full field list and promotion rules.

**Corpus mining** — Phase A is mechanical (no AI); improvements there are straightforward Python. Phase B and C use Claude — prompt changes go in `pipeline_mining.py`.

---

## Key files

| File | Purpose |
|---|---|
| `pipeline_ingest.py` | Main ingestion loop |
| `prompts.py` | All Claude prompts (relevance, extraction, profile) |
| `build_sqlite.py` | JSONL → SQLite; derived columns; exclusions |
| `pipeline_mining.py` | Phase A → B → C corpus mining |
| `generate_qubit_profile.py` | Export corpus sample as Baby QREM YAML |
| `compute_class_defaults.py` | Generate per-material corpus-average YAMLs |
| `serve_materials.py` | HTTP server |
| `materials_explorer.html` | Explorer UI |
| `ingest_pipeline.html` | Pipeline UI |

---

## Known limitations

- T1 and Qi data reported only in figures may be missed or extracted at lower confidence — human review is essential before quantitative use.
- PDFs over ~24MB fail due to base64 encoding limits — compress with ghostscript at 150dpi first.
- SI files are ingested as separate papers with no link to the main paper — do not ingest SI files as standalone until the DOI-based linking feature is implemented.
- `sim_material_class` (AI-generated) can be unreliable for uncommon materials (NbSe2, PtSi) — cosmetic Explorer issue only; mining uses `derived_material` (deterministic) instead.

---

