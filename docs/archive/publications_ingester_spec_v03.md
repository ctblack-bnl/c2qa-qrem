# Publications Ingester Module
## Specification Document v0.3

**Version:** 0.3 — Implementation Update: Corpus Expanded, Prompt Enriched, Explorer UI Built
**Date:** April 23, 2026
**Status:** Phase 2 Operational — corpus at scale, Materials Explorer UI live
**Context:** Component of the C2QA Materials Characterization Database effort

---

## Purpose

The Publications Ingester is a tool that reads scientific papers and automatically extracts structured materials characterization data, populating records in the materials database schema. It sidesteps the central incentive problem of scientific data sharing — scientists already publish, and are strongly motivated to do so. By extracting data from publications, the database gets populated without asking anyone to fill out a form.

The core value proposition: **submit your paper, get your data in the database automatically, with full citation credit.**

---

## Implementation Status (Updated v0.3)

### Phase Status

Phase 1 (manual template) was skipped. Phase 2 (AI-assisted extraction) is fully operational as of April 23, 2026. The corpus has grown significantly from initial testing and the extraction prompt has been substantially enriched.

### Code Structure

```
2026-04 c2qa_qrem/
  ingester/
    pipeline_ingest.py      — main loop: find PDFs, relevance check, extract, write JSONL
    prompts.py              — relevance check prompt + extraction prompt builder (v2 enriched)
    processed_ledger.py     — DOI-primary / filename-fallback idempotency ledger
    build_sqlite.py         — loads JSONL into SQLite with display_name field
    serve_materials.py      — local server for the Materials Explorer UI
    materials_explorer.html — browser-based data explorer (strip plot, scatter, catchall)
    config.py               — Azure/Claude API configuration (env vars)
    openai_client.py        — provider abstraction (Azure Claude via Anthropic Foundry)
    io_jsonl.py             — append-only JSONL read/write utilities
    json_utils.py           — safe JSON serialization
  data/
    papers/                 — drop PDFs here for ingestion (subfolders supported)
    ingested/
      records.jsonl         — append-only canonical ledger of all ingestion records
      processed_ledger.json — tracks which papers have been seen (skip on re-run)
      records.db            — SQLite browse database (derived, rebuildable)
```

### Running the Ingester

```bash
cd ingester
export PROVIDER=claude
export AZURE_CLAUDE_API_KEY=your-key-here
caffeinate python3 pipeline_ingest.py
```

Drop PDFs into `data/papers/` before running. Subfolders are supported — the ingester discovers PDFs recursively. Already-processed papers are automatically skipped. After each run, rebuild the SQLite database:

```bash
python3 build_sqlite.py
```

### Running the Materials Explorer

After building the SQLite database, launch the local server:

```bash
python3 serve_materials.py
```

Open in browser: `http://localhost:8001/materials_explorer.html`

The Explorer provides three views:
- **By Material** (default) — strip plot showing measurement values grouped by material, substrate, or deposition method
- **Scatter Plot** — any two continuous fields plotted against each other, colored by material
- **Data Table** — full sample list with key fields and confidence indicators
- **Catchall Corpus** — browse all catchall entries filtered by type

### Resetting and Re-ingesting

To clear the corpus and re-ingest all papers (e.g. after a prompt update):

```bash
rm ../data/ingested/records.jsonl
rm ../data/ingested/processed_ledger.json
rm ../data/ingested/records.db
caffeinate python3 pipeline_ingest.py
```

### Current Corpus State (April 23, 2026)

| Metric | Value |
|---|---|
| Papers processed | 62 |
| Papers ingested | ~35 |
| Papers skipped (not relevant) | ~27 |
| Samples extracted | 150+ (estimate, run in progress) |
| Catchall items | 1000+ (estimate) |

Coverage breakdown will be updated after current ingestion run completes. Previous corpus (18 papers) showed: Tc 57%, RRR 33%, Qi 18%, T1 13%.

### Coverage Query

```sql
SELECT
    COUNT(*) as total_samples,
    SUM(CASE WHEN Tc_K IS NOT NULL THEN 1 ELSE 0 END) as has_Tc,
    SUM(CASE WHEN RRR IS NOT NULL THEN 1 ELSE 0 END) as has_RRR,
    SUM(CASE WHEN Qi_internal IS NOT NULL THEN 1 ELSE 0 END) as has_Qi,
    SUM(CASE WHEN T1_us IS NOT NULL THEN 1 ELSE 0 END) as has_T1
FROM samples;
```

---

## Scope

The ingester extracts:

- **Always:** Material properties, fabrication parameters, sample description
- **When present:** Connections to qubit device performance (resonators, junctions, transmons, other qubit architectures)
- **Always included regardless of qubit connection:** Kinetic inductance, critical current density, film stoichiometry — these are material properties even when measured in non-qubit device contexts
- **Explicitly excluded:** Non-qubit device performance metrics (SNSPD reset times, TWPA parameters, accelerator cavity performance, etc.) — these go to the catch-all only, flagged

The qubit connection does not need to be the primary focus of the paper. A paper about TaN nanowires for SNSPDs that also reports Tc, RRR, coherence length, and sheet resistance should have those material properties extracted even though the device application is outside scope.

---

## Input Types

The ingester handles three distinct paper types, each processed differently:

### Type 1 — Primary Research Paper
A paper reporting original measurements on specific samples. This is the highest-value input type.

- Creates one or more structured database records, one per sample or sample family
- Extracts numerical values directly from tables, figures, and text
- Confidence level: high for tabulated data, medium for prose-extracted values, low for inferred values
- Every extracted value gets a page/figure/table reference for traceability

### Type 2 — Review Paper
A paper synthesizing results from many primary sources. Does not report original measurements.

- Does **not** create primary database records
- Creates two outputs:
  1. **Schema evolution proposals** — parameters discussed in the review that are absent from the current schema
  2. **Primary paper queue** — references containing primary measurement data, flagged for direct ingestion

### Type 3 — Process Comparison Study
A paper systematically varying fabrication parameters across a family of samples. Common in materials science.

- Creates a linked family of records sharing provenance but varying in process parameters
- Table-heavy papers of this type are particularly high-value — the table is essentially a pre-formatted database

---

## Extraction Pipeline — Two-Pass Design

```
Input: PDF file
         |
    [PASS 1] RELEVANCE CHECK  (~10-15 seconds, low token cost)
         | — Is this paper relevant? (high / medium / low)
         | — What type is it? (primary / review / process_comparison)
         | — What is the DOI?
         |
         ├── LOW RELEVANCE → log as skipped, write to JSONL, update ledger. Stop.
         |
         └── HIGH or MEDIUM RELEVANCE →
                  |
             [PASS 2] FULL EXTRACTION  (~60-90 seconds, higher token cost)
                  | — Extract all structured fields present in the paper
                  | — Sparse output: only fields with actual data
                  | — Confidence score + source reference for every field
                  | — Catch-all: additional measurements, anomalies, correlations,
                  |              schema promotion candidates
                  |
             Output: Draft record written to JSONL ledger
                     Flagged human_reviewed: false, human_approved: false
```

### Why Two Passes

**Cost efficiency:** Pass 1 is fast and cheap. Irrelevant papers are rejected before incurring full extraction cost. In a corpus of 62 papers, approximately 44% were skipped as not relevant.

**Quality:** Separating relevance from extraction allows each prompt to be focused and clear.

**Auditability:** Every paper produces a record with an explicit decision and reason, whether ingested or skipped.

---

## Sparse Output Design

Claude only returns fields that are actually present in the paper. If a measurement is not reported, that field is simply absent from the output. Absence means not reported — it is never recorded as zero.

**Confidence scoring** is mandatory for every included field:
- `high` — value from a structured table with explicit units
- `medium` — value from prose, clear unambiguous claim
- `low` — value inferred or calculated from other reported values

**Source references** are mandatory for every included field, citing the specific location: "Table I column 3", "page 4 paragraph 2", "Figure 3 caption."

---

## Extraction Prompt — v2 Enriched (Updated v0.3)

The extraction prompt has been substantially enriched from the initial sparse version. Key additions:

### Domain Knowledge Glossary
The prompt now includes a full glossary of known connections between material properties and qubit performance. This grounds `suspected_relevance` entries in real physics rather than generic statements. Examples:

```
RRR (residual resistivity ratio) → quasiparticle density → T1 relaxation time
Surface oxide thickness → TLS density → T2 dephasing and Qi
Coherence length (xi) vs mean free path (l):
  xi < l → clean limit → vortex motion is primary loss channel
  xi > l → dirty limit → different loss mechanisms dominate
Two-qubit gate fidelity → error correction code distance → module count
  (99.5% → 16 modules; 99.9% → 2 modules for representative circuit)
```

### Error Prevention Rules
Explicit warnings about known extraction errors observed in testing:
- Tc and Qi confusion (similar numeric ranges in some papers)
- RRR is dimensionless — if units are present it is a different quantity
- T1 may be reported in ms — always convert to µs
- Qi vs Qc confusion — internal vs coupling quality factor

### Catchall Guidance
Detailed rules for each catchall section:
- `suspected_relevance` must cite specific physics, not generic statements
- `correlations_observed` must only include author-stated correlations, not inferred ones
- `schema_promotion_candidates` must explain specifically what would be lost without the field

### Material Name Standardization
The prompt now instructs Claude to use standard chemical abbreviations for film materials:

```
tantalum, Ta film          → Ta
niobium, Nb film           → Nb
niobium titanium nitride   → NbTiN
tantalum nitride           → TaN
Ta-Hf alloy (83% Ta, 17%) → Ta-Hf (83:17)
```

Crystal phase always goes in `film_crystal_phase`, never in `film_material`:
```
alpha-Ta → film_material: Ta, film_crystal_phase: alpha-Ta (bcc)
```

This prevents the material name inconsistency problem (e.g. "Tantalum (Ta)" vs "Ta" appearing as separate categories) that would otherwise require manual normalization. The prompt-level fix is preferred over a lookup table because it requires no ongoing human maintenance.

---

## Processed Papers Ledger

The ingester is fully idempotent. Papers already processed are skipped automatically.

**Key strategy:** DOI is the primary key when extractable. Filename is the fallback for preprints without DOIs. Papers are recognized as already processed even if renamed, as long as the DOI matches.

**Outcome values:**
- `ingested` — relevance check passed, extraction succeeded, record written
- `skipped` — relevance check returned low relevance
- `failed` — relevance check or extraction encountered an error

Failed papers are logged but not blocked — reprocess by deleting their ledger entry and rerunning.

---

## PDF Input via Direct Claude Vision

The ingester sends PDFs directly to Claude as base64-encoded documents. Claude reads the full PDF visually — text, tables, figures, and figure captions — in a single pass.

**Why this approach:** Materials papers frequently report key data in figures rather than tables. Text extraction would miss figure data entirely. Sending the PDF directly allows Claude to read both tabular data (high confidence) and figure data (medium confidence) in one pass.

**On PDF-to-Markdown conversion:** This approach was considered and rejected. Converting PDFs to markdown before sending to Claude would lose all figure data, which is a significant loss for this domain. The PDF-direct approach is the correct design choice for materials science papers. The JSONL ledger and source PDFs provide all necessary auditability without requiring an intermediate markdown representation.

**Subfolder support:** PDFs can be organized in subfolders within `data/papers/`. The ingester uses `rglob` to discover all PDFs recursively at any depth.

---

## Technical Implementation

### API Integration

Azure Foundry (AnthropicFoundry client). Provider abstraction from the SEM metadata pipeline reused — `openai_client.py` wraps both Azure Claude and Azure OpenAI behind a common interface.

### Streaming

Pass 2 uses streaming to show output token-by-token as Claude generates it. Confirms the pipeline is alive during the 60-90 second extraction and allows early detection of truncation.

### Token Budget

- Pass 1 (relevance check): 1,000 max tokens
- Pass 2 (extraction): 16,000 max tokens

### JSONL Ledger

All records written to append-only JSONL (`data/ingested/records.jsonl`). Every record contains full Pass 1 and Pass 2 outputs, provenance metadata, and human review flags. Records are never modified — the ledger is append-only.

### SQLite Review Layer

`build_sqlite.py` loads the JSONL ledger into SQLite with three tables:

**`papers`** — one row per paper: outcome, DOI, title, authors, journal, review flags, sample count.

**`samples`** — one row per extracted sample. Key addition in v0.3: `display_name` field — a compound identifier constructed as `{first_author}_{year}_{sample_id}` (e.g. `Bahrami_2026_D1`). This makes samples unambiguous across papers when browsing the database. Also added: `film_crystal_phase`, `annealing_temperature_C`, `annealing_duration_s`.

**`catchall_items`** — one row per catchall entry. Also carries `display_name` for easy joining with samples table.

The SQLite database is derived and rebuildable at any time from the JSONL. It is not a source of truth.

### Materials Explorer UI

A browser-based data explorer served by `serve_materials.py` on port 8001. Three API endpoints:

- `GET /api/samples` — all samples with numeric fields parsed to floats
- `GET /api/catchall` — all catchall items, optionally filtered by type
- `GET /api/coverage` — coverage summary (count of samples with each key field)

The UI (`materials_explorer.html`) provides:
- **By Material tab** (default) — strip/dot plot: Y = any measurement field, X = material categories with jitter. Designed for the primary scientific use case: comparing how a measurement varies across materials.
- **Scatter Plot tab** — continuous X vs Y, colored by material/substrate/deposition method
- **Data Table tab** — sortable table with confidence color coding
- **Catchall Corpus tab** — browse all catchall items filtered by type (correlations, schema candidates, additional measurements, anomalous observations)

Label truncation applied in strip plot — long material names extracted to their chemical symbol where possible (e.g. "Tantalum (Ta)" → "Ta" in axis labels), with full name preserved in tooltips.

---

## Confidence Scoring

| Level | Meaning | Example |
|---|---|---|
| `high` | Directly from a structured table with explicit units | Table I value with clear column headers |
| `medium` | Extracted from prose, unambiguous claim | "The Tc of our films was 4.1 K" |
| `low` | Inferred or calculated from other reported values | T1 estimated from loss tangent |

---

## The Catch-All as First-Class Output

The catch-all is a primary scientific output, not a fallback. The ingester populates it with:

- Measurements taken that don't map to any schema field
- Anomalous observations reported by the authors
- Correlations explicitly noted in the paper (author-stated only — not inferred)
- Author hypotheses about mechanisms
- Schema promotion candidates — fields that appear important but aren't in the schema yet

With 62 papers ingested, the catchall corpus contains thousands of entries. This is the primary input to the AI review process driving schema evolution, and the primary source for mining author-stated materials-to-device connections for the QREM mapping layer.

### Catch-All Item Types

| Type | Description |
|---|---|
| `additional_measurement` | Measurement with no schema field — value, units, source, suspected relevance |
| `anomalous_observation` | Unexpected result — description and author hypothesis |
| `correlation` | Author-stated correlation — two parameters and nature of relationship |
| `schema_candidate` | Important parameter absent from schema — candidate for promotion |

---

## Human Review Philosophy (Updated v0.3)

Early thinking assumed human review would be a batch process — sit down, review all records, approve them. Experience has shown this is the wrong model.

**The correct model is living review.** Scientists encounter records that need attention through normal use of the tool:

- Browsing the Materials Explorer and spotting an outlier that looks wrong
- Noticing a sample from their own paper is missing or incorrect
- Seeing a material name that doesn't look right in the strip plot

Review actions should be available wherever the data is visible — not in a separate workflow. The `human_reviewed` and `human_approved` flags in every record provide the infrastructure for this when the right UI design becomes clear through actual use of the tool.

**Design principle:** Review UI design should emerge from how people actually use the Explorer, not be designed in the abstract. The correct review mechanism will become obvious once the tool has been used by collaborators for a few weeks.

---

## Relevance Classification

**High relevance — always ingest:**
- C2QA funding acknowledgment
- Materials explicitly used in superconducting qubits (Ta, Nb, Al, TiN, NbTiN, TaN, PtSi, Re, NbN)
- Josephson junction fabrication and characterization
- Superconducting resonator loss studies

**Medium relevance — ingest material properties, flag application:**
- Superconducting materials in non-qubit applications (SNSPDs, accelerator cavities)
- Adjacent materials that may have qubit relevance

**Low relevance — skip entirely:**
- Classical materials with no superconducting content
- Superconducting power applications (motors, cables, magnets)
- High-Tc superconductors not relevant to quantum circuits
- Purely theoretical papers with no experimental measurements

**Observed performance:** Relevance filter correctly skipped ~44% of a 62-paper corpus as not relevant. No known false negatives (relevant papers incorrectly skipped).

---

## Limitations and Honest Uncertainty

- **Never invent values.** If a value cannot be confidently extracted, the field is omitted.
- **Flag rather than decide.** Ambiguous extractions go to the catch-all.
- **Confidence is mandatory.** Every included field has a confidence score.
- **Human approval before use.** All records start as `human_approved: false`.

### Known Limitations

**Qi data in figures:** Frequently reported in figures rather than tables. Coverage improves with the enriched prompt but remains lower than for tabulated properties like Tc and RRR.

**Value confusion:** Observed in Yang et al. where Tc and Qi values were confused. Human review is essential for medium-confidence extractions. The enriched prompt adds explicit warnings against this error.

**Large PDF performance:** Papers exceeding ~5MB base64 may take 2-3 minutes for Pass 2. Papers with extensive supplementary figures are most affected.

**Material name consistency:** The enriched prompt instructs Claude to use standard abbreviations, but novel or unusual materials may still produce verbose descriptions. Label truncation in the Explorer UI mitigates the display impact.

---

## Relationship to QREM Materials-to-Device Mapping Layer

The ingester feeds two things into the QREM pipeline:

**Structured measurements** (Tc, RRR, sheet resistance, film thickness, deposition method, Qi, T1, etc.) — direct inputs to the materials-to-device mapping layer. A sample record with Tc = 4.4K, RRR = 65, mean free path = 109nm is a quantitative fingerprint of a specific film.

**Catch-all connections** — author-stated connections between material properties and device performance. These are peer-reviewed claims that form the evidence base for the mapping layer.

**Near-term plan:**
1. Run a Claude analysis over the catchall corpus to extract all explicit author-stated materials-to-device connections
2. Rank connections by how many papers support each one
3. Implement the best-supported connections as the initial mapping layer entries
4. Use structured measurements to parameterize and validate those mapping functions

---

## Development Phases

**Phase 1 — Manual template:** Skipped.

**Phase 2 — AI-assisted extraction (Current):**
Operational. 62 papers ingested. Enriched prompt with domain knowledge glossary, error prevention, catchall guidance, and material name standardization. Materials Explorer UI live. Display name field for cross-paper sample identification.

**Phase 3 — Catchall mining and mapping layer (Next):**
Run Claude analysis over the catchall corpus to extract author-stated materials-to-device connections. Implement initial QREM mapping layer entries from best-supported connections.

**Phase 4 — Human review UI (Planned):**
Review mechanism integrated into Explorer — design to emerge from actual usage patterns rather than designed in the abstract.

**Phase 5 — Active literature monitoring (Planned):**
Automated monitoring of arXiv cond-mat.supr-con and relevant journals. Weekly or monthly human review of the queue.

---

*End of Specification v0.3*
*Original document produced April 2026. Updated April 23, 2026.*
