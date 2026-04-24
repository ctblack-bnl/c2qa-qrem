# ingester/prompts.py
# Prompt builders for the publications ingester.
# Two prompts are used per paper:
#   1. RELEVANCE CHECK — fast first pass: is this paper worth ingesting?
#   2. EXTRACTION — sparse extraction of only what the paper actually reports
#
# Key design principle: SPARSE OUTPUT.
# Claude only returns fields that are actually present in the paper.
# Absence from the output means not reported — we never fill fields with null
# just to confirm they're absent. This keeps records small and meaningful.
#
# Version history:
#   v1 — initial sparse prompt, minimal guidance
#   v2 — enriched catchall guidance, error prevention, domain knowledge glossary

import json

# =============================================================================
# PROMPT 1 — RELEVANCE CHECK
# =============================================================================

_RELEVANCE_SCHEMA = {
    "relevance": "<high | medium | low>",
    "relevance_reason": "<one sentence explaining the relevance decision>",
    "paper_type": "<primary | review | process_comparison | unclear>",
    "paper_type_reason": "<one sentence explaining the type decision>",
    "doi": "<DOI string if found in paper, or null>",
    "title": "<paper title>",
    "authors": "<first author et al., year>",
    "journal_or_preprint": "<journal name or arXiv etc.>",
    "skip": "<true if relevance is low, false otherwise>"
}
_RELEVANCE_SCHEMA_STR = json.dumps(_RELEVANCE_SCHEMA, indent=2)

RELEVANCE_PROMPT = f"""
You are a relevance classifier for a materials science database focused on
superconducting qubit and resonator systems for quantum computing.

Your job is to read this paper and decide:
  1. Is it relevant to our database?
  2. What type of paper is it?
  3. What is the DOI?

---
RELEVANCE CRITERIA
---

HIGH relevance — always ingest:
  - C2QA funding acknowledgment present
  - Materials explicitly used in superconducting qubits:
    Ta, Nb, Al, TiN, NbTiN, TaN, NbN, Re, PtSi, or alloys thereof
  - Josephson junction fabrication or characterization
  - Superconducting resonator loss studies (TLS, dielectric loss, Qi)
  - Qubit coherence measurements (T1, T2, gate fidelity)

MEDIUM relevance — ingest material properties only, flag application:
  - Superconducting materials used in non-qubit applications
    (SNSPDs, accelerator cavities, TWPAs)
  - Adjacent materials that may have qubit relevance

LOW relevance — skip entirely:
  - Classical materials with no superconducting content
  - Superconducting power applications (motors, cables, magnets)
  - High-Tc superconductors not relevant to quantum circuits
  - Purely theoretical papers with no experimental measurements

---
PAPER TYPE DEFINITIONS
---

primary:             Reports original measurements on specific samples.
review:              Synthesizes results from many primary sources.
                     Does NOT report original measurements.
process_comparison:  Systematically varies fabrication parameters across
                     a family of samples. Table-heavy.

---
OUTPUT
---
Return ONLY valid JSON. No markdown fences. No text before or after.
{_RELEVANCE_SCHEMA_STR}
""".strip()


# =============================================================================
# PROMPT 2 — SPARSE EXTRACTION (enriched v2)
# =============================================================================

# Domain knowledge glossary — tells Claude what "relevant to qubit performance"
# means in this field, so suspected_relevance entries are scientifically grounded
# rather than generic. Modeled on the SEM pipeline's measurements glossary.
_DOMAIN_GLOSSARY = """
DOMAIN KNOWLEDGE — MATERIALS TO QUBIT PERFORMANCE CONNECTIONS
When assessing suspected_relevance for catchall entries, use this glossary
of known connections between material properties and qubit performance.
These are the links our database is designed to capture.

Film purity and crystallinity:
  RRR (residual resistivity ratio) → quasiparticle density → T1 relaxation time
  Mean free path (l) → clean vs dirty superconducting limit → vortex behavior
  Crystal phase (alpha-Ta vs beta-Ta) → defect density → coherence and loss
  Grain size and boundaries → surface roughness → TLS density at interfaces
  Lattice constant deviation from bulk → strain / defect density → loss

Surface and interface quality:
  Surface oxide thickness → TLS (two-level system) density → T2 dephasing and Qi
  Surface oxide composition → TLS species identification → loss mechanism
  Interface roughness → scattering, TLS → coherence
  Native oxide regrowth rate → processing sensitivity → yield

Superconducting properties:
  Tc → operating temperature margin, quasiparticle density at operating temp
  Coherence length (xi) relative to mean free path (l):
    xi < l → clean limit → vortex motion is primary loss channel (not pinned)
    xi > l → dirty limit → different loss mechanisms dominate
  Upper critical field Hc2 → operating magnetic field margin
  Vortex activation temperature → characterizes vortex motion loss channel

Microwave performance:
  Qi (internal quality factor) → resonator loss → directly sets T1 upper bound
  Loss tangent → dielectric contribution to T1
  TLS density → dephasing, low-frequency noise, Qi degradation
  Loss mechanism attribution (TLS vs quasiparticle vs vortex motion vs radiation)
    → tells us which material improvement would have the largest impact

Device performance:
  T1 → physical gate fidelity → error correction code distance → module count
  T2 → dephasing → gate fidelity for longer sequences
  Gate fidelity → directly sets error correction overhead in QREM
  Two-qubit gate fidelity is the dominant cost — small improvements here
    (e.g. 99.5% → 99.9%) can reduce module count by 8x or more
""".strip()


_SPARSE_SCHEMA = {
    "doi": "<DOI or null>",
    "title": "<paper title>",
    "authors": "<first author et al., year>",
    "journal_or_preprint": "<journal name or arXiv>",
    "paper_type": "<primary | review | process_comparison>",
    "relevance": "<high | medium>",
    "samples": [
        {
            "sample_id": "<identifier from paper>",
            "substrate_material": {"value": "<value>", "confidence": "<high|medium|low>", "source": "<location in paper>"},
            "substrate_orientation": {"value": "<value>", "confidence": "<high|medium|low>", "source": "<location>"},
            "film_material": {"value": "<value>", "confidence": "<high|medium|low>", "source": "<location>"},
            "film_crystal_phase": {"value": "<e.g. alpha-Ta (bcc), beta-Ta (tetragonal)>", "confidence": "<high|medium|low>", "source": "<location>"},
            "film_thickness_nm": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "deposition_method": {"value": "<value>", "confidence": "<high|medium|low>", "source": "<location>"},
            "deposition_temperature_C": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "annealing_temperature_C": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "annealing_duration_s": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_present": {"value": "<true|false>", "confidence": "<high|medium|low>", "source": "<location>"},
            "Tc_K": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "RRR": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "sheet_resistance_Ohm_sq": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "loss_tangent_substrate": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "loss_tangent_interface": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "TLS_density_per_GHz_per_um2": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "Qi_internal_quality_factor": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "Qi_single_photon": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "surface_oxide_thickness_nm": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "T1_us": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "T2_echo_us": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "single_qubit_gate_fidelity_pct": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "two_qubit_gate_fidelity_pct": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "catchall": {
                "additional_measurements": [
                    {"description": "<what was measured>", "value": "<value and units>",
                     "source": "<location>", "suspected_relevance": "<specific connection to qubit performance using domain glossary>"}
                ],
                "anomalous_observations": [
                    {"description": "<what was unexpected and why>", "hypothesis": "<authors best explanation, or your assessment if not stated>"}
                ],
                "correlations_observed": [
                    {"description": "<correlation>", "measurement_a": "<param>",
                     "measurement_b": "<param>", "nature": "<positive/negative correlation, threshold behavior, etc.>"}
                ],
                "schema_promotion_candidates": [
                    {"parameter": "<parameter name>", "description": "<what it measures and its units>",
                     "why_important": "<specific scientific reason this should be a structured field>",
                     "source": "<location>"}
                ],
                "free_notes": "<fabrication details, processing context, cross-sample observations>"
            }
        }
    ],
    "review_outputs": {
        "schema_evolution_proposals": [
            {"parameter": "<n>", "description": "<what>",
             "why_important": "<reason>", "supporting_text": "<quote>"}
        ],
        "primary_paper_queue": [
            {"citation": "<full citation>", "doi": "<DOI>", "why_relevant": "<reason>"}
        ]
    }
}

_SPARSE_SCHEMA_STR = json.dumps(_SPARSE_SCHEMA, indent=2)


def build_extraction_prompt(relevance: str, paper_type: str) -> str:

    type_instruction = {
        "primary": (
            "This is a PRIMARY RESEARCH PAPER. Extract one sample entry per distinct "
            "sample or device reported. If a table contains multiple samples, create one "
            "entry per row. Omit review_outputs from your response entirely."
        ),
        "review": (
            "This is a REVIEW PAPER. The samples list should be empty []. "
            "Populate review_outputs with schema_evolution_proposals and "
            "primary_paper_queue only."
        ),
        "process_comparison": (
            "This is a PROCESS COMPARISON STUDY. Extract one sample entry per row "
            "in the comparison table. Each sample_id should reflect its table position "
            "e.g. 'Table I Row 3'. Omit review_outputs from your response entirely."
        ),
    }.get(paper_type, "Extract all samples found.")

    relevance_instruction = (
        "MEDIUM relevance: extract material properties only "
        "(Tc, RRR, sheet resistance, film thickness, deposition method). "
        "Do NOT extract device metrics unrelated to qubits."
        if relevance == "medium" else
        "HIGH relevance: extract all available fields."
    )

    return f"""
You are extracting structured materials characterization data from a scientific paper
for a database supporting superconducting qubit research.

---
PAPER TYPE: {type_instruction}
RELEVANCE:  {relevance_instruction}

---
EXTRACTION RULES
---

1. SPARSE OUTPUT — only include fields the paper actually reports.
   If a measurement is not in the paper, omit that field entirely.
   Do NOT include fields with null values — just leave them out.
   A short record with only real data is better than a long record full of nulls.

2. CONFIDENCE is mandatory for every field you include:
   - high:   value from a structured table with explicit units
   - medium: value from prose, clear unambiguous claim
   - low:    value inferred or calculated from other reported values
   If you are uncertain whether a value is correctly identified, use low confidence
   or omit the field entirely rather than guessing.

3. SOURCE is mandatory for every field: cite exactly where in the paper.
   "Table I column 3", "page 4 paragraph 2", "Figure 3 caption", "Abstract sentence 2"
   Never just say "paper" or "text."

4. NEVER INVENT VALUES. If you cannot confidently identify a value, leave the field out.

5. UNITS — extract values in schema units. If the paper uses different units,
   convert and note the conversion in the source field.
   e.g. "Table II row 3, converted from ms to µs"

6. CATCHALL — only include sections that have actual content.
   Omit empty sections entirely. See detailed catchall rules below.

7. For review_outputs: only include for review papers. Omit entirely for
   primary and process_comparison papers.

---
MATERIAL NAME STANDARDIZATION
---

For the film_material field, always use standard chemical abbreviations.
Never spell out element names. Follow these rules:

Single-element films:
  tantalum, Ta film, Ta metal      → Ta
  niobium, Nb film                 → Nb
  aluminum, Al film                → Al
  rhenium, Re film                 → Re

Compounds and alloys — use the chemical formula:
  niobium titanium nitride         → NbTiN
  niobium nitride                  → NbN
  titanium nitride                 → TiN
  tantalum nitride                 → TaN
  niobium selenide (2H phase)      → NbSe2
  platinum silicide                → PtSi
  vanadium trisulfide              → VS3
  lithium niobate                  → LiNbO3

Alloys with composition — keep composition but use symbols:
  Ta-Hf alloy (83% Ta, 17% Hf)    → Ta-Hf (83:17)
  Ta0.83Hf0.17                     → Ta-Hf (83:17)

Multi-layer or junction devices — describe concisely:
  Nb circuit layer with Al junctions  → Nb/Al
  Ta film with Al/AlOx junction       → Ta (with Al/AlOx junction)

Crystal phase — always include in film_crystal_phase field, not in film_material:
  alpha-Ta, bcc-Ta                 → film_material: Ta, film_crystal_phase: alpha-Ta (bcc)
  beta-Ta, tetragonal Ta           → film_material: Ta, film_crystal_phase: beta-Ta (tetragonal)

If the material is genuinely novel or not listed above, use the authors'
own notation but keep it concise — drop parenthetical element names.

---
KNOWN EXTRACTION ERRORS TO AVOID
---

These errors have been observed in testing — be especially careful:

- Tc and Qi confusion: Tc values (typically 1-10 K) and Qi values (typically 1e5-1e7)
  occupy very different numeric ranges, but ambiguous prose can cause confusion.
  Always check units and context before assigning a value to either field.

- RRR is dimensionless: if a paper reports a resistivity ratio with units, it is
  probably a different quantity. True RRR has no units.

- T1 units: T1 may be reported in ms in some papers. Always check and convert to µs.
  Note the conversion in the source field.

- Qi vs Qc confusion: Qi is the internal quality factor (loss in the resonator itself).
  Qc is the coupling quality factor (loss to the measurement circuit). They are different.
  Do not substitute one for the other.

- Figure vs table data: values extracted from figures should be marked medium confidence
  even if you are fairly certain of the value, because visual extraction is inherently
  less precise than tabular extraction.

---
R vs T CURVES — EXTRACT THESE IF PRESENT
---

Many papers report resistance vs temperature (R vs T) curves but do not explicitly
state the derived intrinsic properties we need. If an R vs T curve or table is present,
extract the following and include them in the sample record:

normal_state_resistance_Ohm:
  The resistance just above Tc (in the normal state, before the superconducting transition).
  Confidence: medium (read from figure) or high (stated in text/table).
  Source: cite the figure number and approximate temperature read point.
  Note: for patterned devices, this is the total measured resistance of the structure.

room_temperature_resistance_Ohm:
  The resistance at or near room temperature (~300K).
  Confidence: medium (read from figure) or high (stated in text/table).
  Source: cite the figure number.
  Note: used to compute RRR = R(300K) / R(Tc+) if RRR not directly reported.

measured_structure_width_um:
  Width of the patterned structure used for the resistance measurement, in microns.
  Required to convert measured resistance to sheet resistance.
  Source: methods section, figure caption, or fabrication table.

measured_structure_length_um:
  Length of the patterned structure used for the resistance measurement, in microns.
  Required to convert measured resistance to sheet resistance.
  Source: methods section, figure caption, or fabrication table.

WHY THESE MATTER:
  Sheet resistance Rs = R_normal × (width / length)   [Ω/□]
  RRR = R(300K) / R(Tc+)                              [dimensionless]
  Resistivity ρ = Rs × film_thickness_nm × 0.1        [µΩ·cm]

These are the intrinsic material properties that allow comparison across samples
with different device geometries. Always prefer directly reported sheet resistance
or RRR if available — only extract R vs T values if those are not reported.

Include these fields directly in the sample record alongside other measurements.
If you can clearly read both R(300K) and R(Tc+) from a figure, extract both even
if the paper does not explicitly state RRR — our derive module will compute it.

---
CATCHALL RULES — READ CAREFULLY
---

The catchall is a first-class scientific output, not a dumping ground.
Apply these rules to produce catchall entries that are genuinely useful:

ADDITIONAL MEASUREMENTS:
  - Include any measurement reported in the paper that has no schema field.
  - The suspected_relevance field is mandatory and must be specific.
    BAD:  "May be relevant to qubit performance"
    GOOD: "Mean free path l > coherence length xi confirms clean superconducting
           limit, meaning vortex motion (not pinning) is the dominant loss channel"
  - Use the domain glossary below to ground your suspected_relevance in known physics.
  - If you cannot identify a specific connection to qubit performance, still include
    the measurement but note "connection to qubit performance unclear" in suspected_relevance.

ANOMALOUS OBSERVATIONS:
  - Only include results the authors themselves flag as unexpected, or that clearly
    deviate from standard behavior (e.g. T1 much lower than Qi would predict).
  - The hypothesis field should capture the authors' explanation if stated,
    or your assessment if not — but label it clearly: "Author hypothesis:" or
    "Assessment (not stated by authors):"

CORRELATIONS OBSERVED:
  - CRITICAL: only include correlations the authors themselves stated or clearly implied.
  - Do NOT infer correlations from the data yourself — you are extracting author claims,
    not performing your own analysis.
  - Good: "Authors state higher annealing temperature correlates with improved Qi"
  - Bad: inferring from a table that sample C has better RRR and better Qi, therefore
    RRR correlates with Qi — the authors did not state this.

SCHEMA PROMOTION CANDIDATES:
  - Flag parameters that appear scientifically important but have no schema field.
  - The why_important field must be specific: what would be lost if we didn't track this?
    BAD:  "This parameter seems important"
    GOOD: "Vortex activation temperature directly characterizes the vortex motion loss
           channel that dominates in clean-limit Ta films — tracking this across samples
           would allow systematic comparison of loss mechanisms across centers"
  - Good candidates from prior ingestion: coherence length, mean free path, vortex
    activation temperature, crystal phase, lattice constant, annealing temperature

FREE NOTES:
  - Use for fabrication context, cross-sample observations, processing details that
    don't fit elsewhere. Think of this as the comments section of a lab notebook.
  - Examples: substrate supplier variation, cleanroom conditions, sample preparation
    sequence, relationship to companion samples in the same study.

---
{_DOMAIN_GLOSSARY}

---
AVAILABLE FIELDS — only return fields present in this paper:
{_SPARSE_SCHEMA_STR}

---
OUTPUT: Return ONLY raw valid JSON. No markdown fences. No text before or after.
""".strip()
