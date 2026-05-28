# C2QA QREM — Project Architecture & Next Steps
## Continuity Document — April 2026

---

## The Five Components

| # | Component | Status |
|---|---|---|
| 1 | **Baby QREM** — circuit + hardware profile → resource estimate | Stages 1-3 complete. Stage 4 (sensitivity analysis) and Stage 5 (reporting) pending. |
| 2 | **Publications Ingester** — reads PDFs, extracts structured materials data | Operational. ~130 samples, 1000+ catchall items, enriched prompt with R vs T extraction. |
| 3 | **Materials Database + Explorer** — SQLite + browser UI | Working. Strip plot, scatter plot, derived quantities, dynamic dropdowns, slide-in detail panel. |
| 4 | **Materials Predictor** | Not yet built. Similarity search is the first step. |
| 5 | **Materials-to-Device Mapping Layer** | Designed, not built. Connects materials side to QREM side. |

---

## How They Connect

```
Scientific Papers
      ↓
[2] Publications Ingester
      ↓
[3] Materials Database
    (Tc, RRR, Qi, T1, derived quantities, catchall)
      |
      |── Measured device performance (T1, T2, gate fidelity, Qi)  ────────┐
      |   → straight to QREM hardware profile                              ↓
      |                                                             [1] Baby QREM
      |── Measured inter-module properties ──────────────────────►         ↑
      |   (link fidelity, entanglement rate, transduction efficiency)       |
      |   → straight to QREM hardware profile                              |
      |                                                                     |
      |── Material properties only (Tc, RRR, resistivity, loss tangent)    |
          → [4] Materials Predictor                                         |
               → [5] Mapping Layer ─────────────────────────────────────────┘
```

**Key design point:** Measured device performance (T1, T2, gate fidelity) goes straight to QREM — no predictor needed. The predictor is only needed for samples where only material properties were measured, which is the majority of the corpus.

**The scientific question the full pipeline answers:**
*"I have a superconducting film with these material properties. If I build a qubit from it and use it in a modular architecture to run this quantum algorithm, how many modules would I need?"*

---

## Direct vs Indirect Paths to QREM

**Direct — no prediction needed:**
- Measured T1, T2, gate fidelity, Qi → straight to hardware profile
- Inter-module link fidelity, entanglement rate, transduction efficiency → straight to hardware profile

**Indirect — needs predictor + mapping layer:**
- Material properties only: Tc, RRR, resistivity, loss tangent, surface oxide, crystal phase
- Noise predictors: T/Tc ratio, Rn, coherence length, mean free path

**Noise channels the mapping layer must model:**
- Quasiparticle noise: driven by T/Tc and Rn → affects T1
- TLS noise: driven by surface oxide, loss tangent → affects T1, T2, Qi
- Vortex motion: driven by coherence length, mean free path → affects Qi, T1
- 1/f flux noise: driven by surface spin density → affects T2

---

## Two Missing Pieces Not Yet Built

**Hardware Profile Updater** — script that reads measured T1/T2/gate fidelity from the database and auto-generates a QREM hardware profile YAML. Most urgent missing piece — enables the direct path that already works with today's corpus.

**Sensitivity Analysis / What-If Engine** — answers "if I improve RRR from 45 to 65, how much does module count change?" Sits above QREM at the top of the stack. Partially specified in QREM spec Stage 4 but needs the materials layer to be meaningful.

---

## The Vertical Integration

```
Materials science    → [2][3] Ingester + Database
Device physics       → [4][5] Predictor + Mapping Layer
Quantum architecture → [1]    QREM
Computer science     → [1]    Circuit analysis
```

No existing tool connects all four. That's the novel contribution.

---

## Coding Priorities — Next Sessions

**Quick wins (hours):**
1. Fix slide-in detail panel in Materials Explorer — URL encoding bug for special characters (Bøttcher)
2. Add T/Tc derived quantity to `derive.py` — assumes 20mK operating temperature
3. Promote `upper_critical_field_T` to structured field in `build_sqlite.py` — unlocks coherence length derivation

**Medium effort (one session each):**
4. **Hardware Profile Updater** — reads T1/T2/fidelity from DB, generates QREM hardware profile YAML. Most direct QREM connection buildable now.
5. **Similarity search** — given a material description, find N most similar samples. Pure SQL + distance metric. First step toward Materials Predictor.
6. **Schema candidate consolidation** — run Claude over 108 schema candidates to cluster synonyms. Human review step.

**Larger effort (multiple sessions):**
7. **Materials Predictor** — similarity search + simple regression (Gaussian process). Needs more corpus first.
8. **Catchall mining script** — Claude analysis over 31 correlations + 750 additional measurements to extract materials-to-device connections for the mapping layer.
9. **QREM Stage 4** — sensitivity analysis and threshold detection. Being worked in separate QREM chat.

---

## Repository

GitHub: `https://github.com/ctblack-bnl/c2qa-qrem`

```bash
# Standard commit workflow
git add .
git commit -m "description"
git push
```

---

## Key Design Principles (don't lose these)

- **JSONL is the source of truth** — append-only, never modified. SQLite is derived and rebuildable.
- **AI proposes, humans approve** — every extracted value has confidence + source citation. `human_reviewed: false` until reviewed.
- **Sparse extraction** — only fields actually reported in a paper are included. Absence = not reported, never zero.
- **Derived quantities live in SQLite, not JSONL** — computed at build time, no re-ingestion needed to add new derivations.
- **Hardware profiles as YAML data, not code** — changing platforms requires only editing a data file.
- **Explicit assumptions in every output** — QREM documents all simplifying assumptions.
- **No manual lookup tables** — normalization is done in the extraction prompt, not maintained by humans.

---

*Last updated: April 25, 2026*
*Developed in collaboration between C2QA center director and Claude (Anthropic)*
