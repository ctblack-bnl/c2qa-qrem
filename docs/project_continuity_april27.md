# C2QA QREM — Project Architecture & Next Steps
## Continuity Document — April 27, 2026

---

## The Five Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | Stages 1-3 complete. Modular profile system operational. UI live. Stage 4 (sensitivity analysis) pending. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | Operational. Three-pass pipeline (relevance, extraction, similarity profile). 97 papers, 155 samples, ~1,300 catchall items, 100% profile coverage. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | Explore/Search/Catchall tabs. Hybrid similarity search live. Material class sidebar. Hosted at https://c2qa-materials-explorer.onrender.com |
| 4 | **Materials Predictor** | Similarity search complete. Gaussian process regression not yet built. |
| 5 | **Materials-to-Device Mapping Layer** | Designed, not built. Catchall mining is the next step toward populating it. |

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
      └── Material properties only (Tc, RRR, resistivity, loss tangent)    |
          → [4] Materials Predictor                                         |
               → [5] Mapping Layer ─────────────────────────────────────────┘
```

**Key design point:** Measured device performance goes straight to QREM via the Hardware Profile Updater — no predictor needed. The predictor is only needed for samples where only material properties were measured, which is the majority of the corpus (T1 coverage is only 12%).

**The scientific question the full pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and use it in a modular architecture to run this quantum algorithm, how many modules would I need?"*

---

## Similarity Search — Current State

Three-layer system, fully operational:

**Pass 3 (ingestion):** Claude generates an 8-dimension semantic profile for each sample at ingestion time. Profiles live in JSONL (source of truth) and are projected into `sim_*` columns in SQLite.

**Hybrid scoring (`serve_materials.py`):**
- 75% profile score — binary match (single fields) or Jaccard similarity (list fields) across 8 dimensions
- 25% numeric score — z-score normalized distance over overlapping numeric fields, weighted by √(overlap count)
- Falls back gracefully: profile-only or numeric-only when one layer is unavailable

**Frontend result cards:** Green ✓ tags for matched profile dimensions, "N dimensions differ" note for mismatches, numeric field chips below.

**Explorer sidebar:** Filters by `sim_material_class` (~10 stable categories) rather than exact `film_material` string — sidebar stays manageable as corpus grows.

---

## Two-Tier Estimation Architecture (QREM)

**Tier 1 — Single-module baseline:**
- Code distance and physical qubits per logical qubit
- Driven entirely by `two_qubit_fidelity_pct` and surface code theory
- Well-grounded analytically, independent of inter-module assumptions

**Tier 2 — Modular overhead:**
- Module count, inter-module operations, communication qubit cost, runtime slowdown
- Driven by interconnect and module profiles
- Active research area — more assumptions, explicitly flagged

| Interconnect tier | Raw fidelity | Purification rounds | Slowdown factor |
|---|---|---|---|
| microwave_photonic_85pct | 85% | 2 | 5,200× |
| microwave_photonic_92pct | 92% | 1 | 1,100× |
| microwave_photonic_99pct | 99% | 0 | 550× |

Key insight: the jump from 85% → 92% (eliminating one purification round) is 5× more impactful than 92% → 99%.

---

## Hosted Infrastructure

| Service | URL | Auto-deploys from |
|---|---|---|
| Materials Explorer | https://c2qa-materials-explorer.onrender.com | GitHub main branch |
| Baby QREM | Local only (localhost:8000) | — |

Render free tier spins down on inactivity — first load after idle takes ~50 seconds.
`git push` → Render rebuilds in ~2 minutes.

---

## Repository & Running

**GitHub:** `https://github.com/ctblack-bnl/c2qa-qrem`

```bash
# Standard commit workflow
git add .
git commit -m "description"
git push   # triggers Render redeploy

# Run Materials Explorer (port 8001)
cd ingester && python3 serve_materials.py

# Run Baby QREM (port 8000)
cd 2026-04\ c2qa_qrem && python3 scripts/serve.py

# Backfill similarity profiles (if vocabulary changes)
cd ingester && python3 backfill_similarity_profiles.py --dry-run
cd ingester && python3 backfill_similarity_profiles.py
```

---

## Coding Priorities — Next Sessions

**Medium effort (one session each):**

1. **Catchall mining** — run Claude over the ~31 author-stated correlations in the catchall corpus to extract, rank, and formalize materials-to-device connections. These become the initial entries in the QREM mapping layer. This was the original "next" item before similarity search took priority.

2. **QREM Stage 4** — sensitivity analysis, threshold detection, what-if engine. "If I improve RRR from 45 to 65, how much does module count change?" Routes material property improvements through the full pipeline to system-level impact. T1 and T2 from corpus records become fully meaningful here.

3. **Automatic QREM profile generation at ingestion** — currently requires manual button click in Explorer. Wire it in alongside Pass 3 for papers that have T1/T2 data.

4. **Human review UI** — review mechanism integrated into Explorer. Design should emerge from actual usage patterns; `human_reviewed` and `human_approved` flags are already in the schema.

**Larger effort (multiple sessions):**

5. **Materials Predictor** — Gaussian process regression per material class. Gives predicted T1/Qi + uncertainty bounds grounded in specific corpus samples. Similarity search is the foundation; regression is the next layer.

6. **Materials-to-Device Mapping Layer** — physics-based bridge from material properties (Tc, RRR, loss tangent) to device parameters (T1, T2, gate fidelity). Feeds QREM when direct measurement isn't available. Catchall mining populates the evidence base.

7. **Neutral atom hardware profile** — just a YAML file following existing structure. Enables cross-platform comparison for Stage 4.

8. **Corpus expansion** — Mingzhao noted the corpus currently covers only 2025-2026 papers. Ingesting older literature is a policy/priority question; the pipeline can handle it.

9. **Supplementary information linking** — wire SI files to their companion papers via DOI-based naming convention. Currently SI files are ingested as independent records with no connection to the main paper. See "Data Provenance" section for design.

---

## Data Provenance — Supplementary Files and External Databases

*Captured April 28, 2026 — important architectural principle, not yet implemented.*

### The Core Insight

Peer review is **inherited, not intrinsic**. A supplementary information (SI) file isn't peer reviewed on its own, but it travels under the umbrella of the paper it belongs to. The same logic applies to external database entries — if you can trace them back to a published paper, they inherit the credibility of that peer review.

This gives a principled way to incorporate data sources beyond the main paper text without compromising the provenance model.

### Provenance Hierarchy

| Source type | Record-level confidence | Rationale |
|---|---|---|
| Peer-reviewed paper (main text) | Highest | Full peer review, narrative context |
| SI file linked to paper via DOI | High | Same peer review umbrella, less scrutinized |
| arXiv preprint | Medium-high | Author-accountable, not yet reviewed |
| External database entry with traceable DOI | Medium | Peer review inherited if link can be made |
| External database entry, no traceable publication | Low | Treat like unreviewed direct submission |
| Raw dataset repository (Zenodo, Figshare, etc.) | Variable | Depends on whether linked to a paper |

This complements the existing field-level confidence (`high`/`medium`/`low`) — provenance confidence operates at the record level, field confidence operates at the value level.

### The SI Linking Problem (needs implementation)

Right now the ingester treats SI files as completely separate papers — they go through Pass 1 relevance check independently and get their own records, with no connection to the companion paper. This is wrong. Almost every paper has an SI file, and SI files are often where the most detailed fabrication parameters live — the stuff too granular for the main paper but essential for reproducibility.

**The fix:** DOI-based linking. Proposed naming convention in the papers folder:

```
{DOI_slug}_main.pdf
{DOI_slug}_SI.pdf
{DOI_slug}_SI2.pdf   # some papers have multiple SI files
```

The ingester recognizes the pattern and ingests them as a single logical record — Pass 2 extraction has access to both documents simultaneously. The resulting record carries `source_files: [main, SI]` in its provenance block.

**Open question:** Does SI content need different prompt handling? Main papers have abstracts, narrative, conclusions. SI files are often just tables and figures without context. Probably needs a flag that adjusts the extraction prompt — less emphasis on narrative framing, more on raw tabular extraction.

**Practical first step:** Audit the current corpus for SI files that were ingested separately and check how much additional data they contain vs the main paper.

### Connection to External Databases

An external database from another group (e.g. a prior C2QA materials effort) can be treated the same way as SI data — if entries can be traced back to published papers via DOI, they inherit medium confidence. If not, they're low confidence direct submissions. This framing avoids the data ownership problem entirely: you're not asking for their database, you're offering to connect their published work to yours.

---

## Longer-Term Vision — Federated Knowledge Graph

*Captured April 26, 2026 — not a near-term coding priority but an important architectural north star.*

The PUK concept scales beyond materials characterization to become a general **federated knowledge graph for quantum computing research**, built from public literature.

**Why traditional data sharing fails:** It requires agreement upfront — on schema, vocabulary, units, curation standards. Five centers will never fully agree before they start.

**Why PUKs are different:** They require agreement only at *query time*, not at *creation time*. Each center generates PUKs in whatever schema captures their work best. The catchall absorbs everything that doesn't fit. An AI rationalizes across heterogeneous PUKs at query time — finding connections not by matching field names but by understanding what measurements *mean*.

**No permission required.** The inputs are already public. The buy-in ask changes completely: instead of "please give us your data," it becomes "please look at what we found in your published work and tell us if our reading is correct."

**What this enables:** Cross-silo hypothesis generation. A materials scientist rarely reads QEC theory papers. An algorithm designer rarely reads materials characterization papers. An AI that has ingested both can say: *"This error correction scheme requires gate fidelity > 99.9%. These materials papers suggest RRR > 60 is needed. These fabrication papers show anneal conditions that reliably produce RRR > 60 in Ta."* That chain exists in no single paper.

**The proof of concept path:**
1. Fully realize connection-finding within the current narrow materials domain (catchall mining — already planned)
2. Broaden to all five centers' published materials work
3. Broaden to adjacent domains (error correction, algorithms, hardware architecture)
4. Eventually: a continuously updated AI-maintained knowledge graph of quantum computing research

*One-sentence summary: A continuously updated, AI-maintained knowledge graph of quantum computing research, built from public literature, that finds connections across centers and disciplines that no human would have the bandwidth to make.*

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — self-contained. Hardware profiles and similarity profiles are projections of records, not independent sources of truth.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. `human_reviewed: false` until reviewed.
- **Sparse extraction** — only fields actually reported in a paper are included. Absence = not reported, never zero.
- **Derived quantities live in SQLite, not JSONL** — computed at build time, no re-ingestion needed.
- **Hardware profiles as YAML data, not code** — changing platforms requires only editing a data file.
- **Explicit assumptions in every output** — QREM documents all simplifying assumptions; the catalog of unknowns is itself a scientific contribution.
- **Two-tier separation** — Tier 1 (qubit physics, solid ground) always separated from Tier 2 (modular overhead, shakier ground).
- **Profile version tracking** — `profile_version` field detects stale profiles after vocabulary updates; regenerate via backfill script.
- **Process variables vs signals** — Block 2 (deposition method, temperature, annealing) are inputs you control; Block 3 (Tc, RRR, T1) are outputs you measure. This separation enables ML/optimization approaches (autonomous experiment framing) without requiring schema changes.

---

*Last updated: April 27, 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
