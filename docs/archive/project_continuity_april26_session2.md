# C2QA QREM — Project Architecture & Next Steps
## Continuity Document — April 26, 2026 (Session 2)

---

## The Five Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | Stages 1-3 complete. Modular profile system operational. UI live. Stage 4 (sensitivity analysis) pending. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | Operational. 92 records, 145 samples, 1,203 catchall items. Pass 3 (similarity profiles) now integrated. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | 3-tab restructure (Explore/Search/Catchall). Similarity search working. Hosted at https://c2qa-materials-explorer.onrender.com |
| 4 | **Materials Predictor** | Similarity search built. Profile-based scoring next. |
| 5 | **Materials-to-Device Mapping Layer** | Designed, not built. |

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

---

## What Was Done This Session

### Explorer UI Restructure
5 tabs → 3 tabs:
- **Explore** — strip plot + scatter, internal Strip/Scatter toggle
- **Search** — Table / Ranked / Similar sub-toggle
- **Catchall** — unchanged

### Similarity Search (working, numeric-only scoring for now)
- Triggered from detail panel "Find similar →" link only — no text input
- Panel closes, Search → Similar tab activates, results fill full width
- "Include same publication" checkbox (unchecked by default)
- Same-pub filter bug fixed (URL encoding of display names with parentheses/commas)
- Result cards show matched field chips with proximity labels (close/near/distant)
  and colored borders (green/blue/gray)
- Discovery loop: click result → detail panel → Find similar → new search

### Readability Pass
- `--text` #e6edf3 → #f0f6fc (brighter)
- `--muted` #8b949e → #adbac7 (much more readable on dark backgrounds)
- `--border` #21262d → #30363d (more visible)
- Base font 14px → 15px; table fonts 12px → 13px; detail panel fonts bumped throughout

### Pass 3 — Similarity Profile Generation (NEW)
Full pipeline now has three passes:
```
Pass 1 — Relevance check
Pass 2 — Full structured extraction → PUK
Pass 3 — Similarity profile → appended to PUK
```

**Profile schema (8 dimensions):**

| Dimension | Type | Vocabulary |
|---|---|---|
| `material_class` | single | niobium, aluminum, tantalum, rhenium, titanium, vanadium, indium, tin, lead, titanium_nitride, niobium_nitride, niobium_titanium_nitride, tantalum_nitride, platinum_silicide, cobalt_silicide, vanadium_silicide, molybdenum_silicide, tungsten_silicide, other_silicide, platinum_germanide, cobalt_germanide, other_germanide, niobium_titanium, tantalum_hafnium, aluminum_manganese, other_alloy, indium_oxide, other_oxide, other |
| `transport_regime` | single | clean_limit, dirty_limit, intermediate, unknown |
| `loss_mechanisms` | list | TLS_substrate, TLS_interface, TLS_metal_vacuum, TLS_unattributed, quasiparticle, vortex_motion, radiation, dielectric_substrate, surface_oxide, flux_noise, charge_noise, unknown |
| `device_type` | single | film_only, resonator, transmon, fluxonium, gatemon, kinetic_inductance_detector, junction_only, multi_qubit_device, unknown |
| `coherence_tier` | single | not_applicable, early_exploration, competitive, state_of_the_art |
| `science_focus` | list | process_optimization, loss_mechanism_identification, materials_characterization, device_demonstration, cross_platform_comparison, noise_characterization, surface_treatment, junction_engineering, scaling |
| `growth_method` | single | sputtering, MBE, ALD, CVD, evaporation, other |
| `key_correlations` | list | RRR_to_T1, anneal_to_crystal_phase, surface_oxide_to_Qi, etc. (21 entries) |

**Profile version:** 1.0 — bump when vocabulary changes to detect stale profiles.

**Backfill:** All 42 ingested records profiled via `backfill_similarity_profiles.py`.
Profiles live in JSONL (source of truth). **Not yet in SQLite** — this is the next step.

---

## Current State of Similarity Scoring

**What's working:**
- Numeric-only similarity via z-score normalization + overlap weighting
- Same-pub filter working correctly
- URL encoding fix for display names with parentheses/commas

**What's next (top priority for next session):**
Profiles are in JSONL but not projected into SQLite yet. Three things needed:

1. **`build_sqlite.py`** — project `similarity_profiles` from JSONL into SQLite.
   Each profile dimension becomes a column (or JSON blob) on the `samples` table.

2. **`serve_materials.py` — `compute_similarity()` rewrite** — hybrid scoring:
   - Profile dimensions: 75% of score
     - Single-value fields (material_class, device_type, etc.): binary match (0 or 1)
     - List fields (loss_mechanisms, science_focus, key_correlations): Jaccard similarity
   - Numeric fields: 25% of score (z-score normalized distance, as today)
   - Explanation draws from both layers for result cards

3. **Frontend — richer result cards** — show matched profile tags as a row above
   the numeric field chips. E.g.:
   ```
   tantalum ✓  transmon ✓  state_of_the_art ✓  sputtering ✓
   Tc (K): 4.1 → 4.3 close   RRR: 52 → 48 close
   ```

Do all three together in one session and commit as a unit.

---

## Scoring Design (for implementation)

```python
def profile_similarity(query_profile, candidate_profile):
    # Single-value dimensions — binary match
    single_dims = ['material_class', 'transport_regime', 'device_type',
                   'coherence_tier', 'growth_method']
    # List dimensions — Jaccard similarity
    list_dims = ['loss_mechanisms', 'science_focus', 'key_correlations']

    scores = []
    matched_tags = []

    for dim in single_dims:
        q = query_profile.get(dim)
        c = candidate_profile.get(dim)
        if q and c and q != 'unknown' and q != 'other':
            match = 1.0 if q == c else 0.0
            scores.append(match)
            if match == 1.0:
                matched_tags.append(dim + ':' + q)

    for dim in list_dims:
        q = set(query_profile.get(dim, []))
        c = set(candidate_profile.get(dim, []))
        if q and c:
            jaccard = len(q & c) / len(q | c)
            scores.append(jaccard)
            matched_tags.extend(q & c)

    profile_score = sum(scores) / len(scores) if scores else 0.0
    return profile_score, matched_tags

# Final score: profile 75%, numeric 25%
# Lower is more similar for numeric (distance); higher is more similar for profile (similarity)
# Need to invert numeric score: numeric_similarity = 1 / (1 + weighted_distance)
final_score = 0.75 * (1 - profile_score) + 0.25 * numeric_distance_normalized
# Sort ascending (lower = more similar)
```

---

## Ingester Pipeline — Three Passes

| Pass | Script | Time | Purpose |
|---|---|---|---|
| Pass 1 | `pipeline_ingest.py` | ~15s | Relevance check, DOI extraction |
| Pass 2 | `pipeline_ingest.py` | ~60-90s | Full structured extraction → PUK |
| Pass 3 | `pipeline_ingest.py` | ~10-20s | Similarity profile generation |

Pass 3 is now in `prompts.py` as `build_profile_prompt()`. **Not yet wired into `pipeline_ingest.py`** for new ingestions — currently only available via the backfill script. Wire it in after the SQLite projection is working.

---

## Hosted Infrastructure

| Service | URL | Auto-deploys from |
|---|---|---|
| Materials Explorer | https://c2qa-materials-explorer.onrender.com | GitHub main branch |
| Baby QREM | Local only (localhost:8000) | — |

Render free tier spins down on inactivity — first load after idle takes ~50 seconds.
`git push` → Render rebuilds in ~2 minutes.

---

## Coding Priorities — Next Sessions

**Immediate (start of next session):**

1. **Project profiles into SQLite** — update `build_sqlite.py` to read `similarity_profiles`
   from JSONL records and add columns to `samples` table. Then rebuild.

2. **Hybrid similarity scoring** — update `compute_similarity()` in `serve_materials.py`.
   Profile 75%, numeric 25%. See scoring design above.

3. **Richer result cards** — show matched profile tags in frontend above numeric chips.

4. **Wire Pass 3 into `pipeline_ingest.py`** — new ingestions should auto-generate profiles.

**Medium effort:**

5. **Catchall mining** — run Claude over ~31 author-stated correlations to populate
   the QREM mapping layer. This was the original "next" before similarity search took over.

6. **QREM Stage 4** — sensitivity analysis, threshold detection, what-if engine.

7. **Automatic QREM profile generation at ingestion** — currently manual button click.

**Larger effort:**

8. **Materials Predictor** — Gaussian process regression per material class.
   Gives predicted T1/Qi + uncertainty bounds grounded in corpus samples.

9. **Materials-to-Device Mapping Layer** — physics-based bridge from material
   properties to device parameters.

10. **Neutral atom hardware profile** — YAML file, enables cross-platform comparison.

---

## Longer-Term Vision — Federated Knowledge Graph

*Captured April 26, 2026 — not a near-term coding priority but an important architectural north star.*

### The Core Insight

The PUK concept scales beyond materials characterization to become a general **federated knowledge graph for quantum computing research**, built from public literature.

**Why traditional data sharing fails:** It requires agreement upfront — on schema, vocabulary, units, curation standards. Five centers will never fully agree before they start. The history of scientific data sharing is littered with failed unified schemas.

**Why PUKs are different:** They require agreement only at *query time*, not at *creation time*. Each center (or each paper) generates PUKs in whatever schema captures their work best. The catchall absorbs everything that doesn't fit a structured field. An AI then rationalizes across heterogeneous PUKs at query time — finding connections not by matching field names but by understanding what measurements *mean*.

### No Permission Required

The inputs are already public. Scientists publish because they want their work read. Ingesting published papers and building PUKs from them is a more systematic version of what a very diligent human reader would do. This can proceed without buy-in from any other center.

**The buy-in ask changes completely.** Instead of "please give us your data" (which requires trust, extra work, schema agreement), the ask becomes "please look at what we found in your published work and tell us if our reading is correct." You are offering something — a synthesis of their published knowledge connected to work from other centers — not asking for a favor.

The published paper is the ground truth. It has been peer reviewed. The authors stand behind it. Disagreements are about interpretation, not data ownership.

### What This Enables

**Cross-silo hypothesis generation.** A materials scientist rarely reads quantum error correction theory papers. An algorithm designer rarely reads materials characterization papers. An AI that has ingested both can say: *"This error correction scheme requires gate fidelity > 99.9%. These materials papers suggest RRR > 60 is needed to achieve that. These fabrication papers show anneal conditions that reliably produce RRR > 60 in Ta."* That chain exists in no single paper.

**The connection types that matter:**
- Causal claims ("X causes Y")
- Correlational observations ("X correlates with Y across N samples")
- Theoretical predictions ("X should imply Y")
- Experimental confirmations ("Y was observed when X was achieved")
- Contradictions between papers ("Paper A reports X; Paper B reports not-X under similar conditions")

The schema for connections needs to be as carefully designed as the materials schema — particularly the distinction between author-stated and AI-inferred connections, which is already a core principle of the catchall.

### Relationship to Current Work

The catchall corpus (~31 author-stated correlations) is already a primitive version of this. The similarity profile vocabulary is a rationalization layer Claude generates from heterogeneous records to enable cross-record comparison. These are working prototypes of the broader vision.

**The proof of concept path:**
1. Fully realize connection-finding within the current narrow materials domain (catchall mining — already planned)
2. If that works, broaden to all five centers' published materials work
3. Then broaden to adjacent quantum computing domains (error correction, algorithms, hardware architecture)
4. Eventually: a continuously updated AI-maintained knowledge graph of quantum computing research that finds connections across centers and disciplines that no human would have the bandwidth to make

### One-Sentence Summary

*A continuously updated, AI-maintained knowledge graph of quantum computing research, built from public literature, that finds connections across centers and disciplines that no human would have the bandwidth to make.*

---


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

# Backfill similarity profiles (future records)
cd ingester && python3 backfill_similarity_profiles.py --dry-run
cd ingester && python3 backfill_similarity_profiles.py
```

---

## Key Design Principles

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **Records are PUKs** — each record is self-contained. Hardware profiles and similarity profiles are projections of records, not independent sources of truth.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. `human_reviewed: false` until reviewed.
- **Sparse extraction** — only fields actually reported in a paper are included. Absence = not reported, never zero.
- **Derived quantities live in SQLite, not JSONL** — computed at build time, no re-ingestion needed.
- **Hardware profiles as YAML data, not code** — changing platforms requires only editing a data file.
- **Explicit assumptions in every output** — QREM documents all simplifying assumptions.
- **Two-tier separation** — Tier 1 (qubit physics, solid ground) always separated from Tier 2 (modular overhead, shakier ground).
- **Profile version tracking** — `PROFILE_VERSION` in `prompts.py` allows detection of stale profiles after vocabulary updates.

---

*Last updated: April 26, 2026 (Session 2)*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
