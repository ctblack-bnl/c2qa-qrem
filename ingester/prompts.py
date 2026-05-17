# ingester/prompts.py
# Prompt builders for the publications ingester.
# Three prompts are used per paper:
#   1. RELEVANCE CHECK — fast first pass: is this paper worth ingesting?
#   2. EXTRACTION — sparse extraction of only what the paper actually reports
#   3. SIMILARITY PROFILE — semantic profile for similarity search (Pass 3)
#
# Key design principle: SPARSE OUTPUT.
# Claude only returns fields that are actually present in the paper.
# Absence from the output means not reported — we never fill fields with null
# just to confirm they're absent. This keeps records small and meaningful.
#
# Version history:
#   v1 — initial sparse prompt, minimal guidance
#   v2 — enriched catchall guidance, error prevention, domain knowledge glossary
#   v3 — added Pass 3 similarity profile generation

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
  Qi (internal quality factor) → resonator photon lifetime (T1_resonator = Qi / 2πf)
    For resonator-only papers: Qi is a proxy for material loss tangents, not qubit T1.
    For qubit papers: Qi of the readout resonator is separate from qubit T1.
    Qubit T1 is set by pad and junction loss, not resonator Qi directly.
    The connection: resonator Qi → material loss tangents → pad loss → qubit T1 upper bound
    (requires geometry factors — participation ratios — to complete the chain).
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
            "Q_TLS_0": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "resonator_type": {"value": "<CPW | lumped_element | other>", "confidence": "<high|medium|low>", "source": "<location>"},
            "resonator_gap_width_um": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "p_MS_resonator": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "p_MS_pad": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "qubit_frequency_GHz": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "surface_oxide_thickness_nm": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "T1_us": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "T1_measurement_context": {"value": "<qubit_state | resonator_photon>", "confidence": "<high|medium|low>", "source": "<location>"},
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
            "entry per row. IMPORTANT: if the paper reports measurements on multiple qubits "
            "or resonators fabricated from the same film, extract each qubit or resonator "
            "as a separate sample record with its own measured T1, T2, Qi values. Do not "
            "collapse multiple characterized devices into a single representative sample. "
            "Omit review_outputs from your response entirely."
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

Multi-layer or junction devices — film_material is the superconducting
film identity ONLY. Junction material goes in junction_material field.
  Nb circuit layer with Al junctions  → film_material: Nb, junction_material: Al/AlOx/Al
  Ta film with Al/AlOx junction       → film_material: Ta, junction_material: Al/AlOx/Al
  Never put junction or encapsulation context in film_material parentheses.

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

 - Resonator T1 vs qubit T1: these are physically different quantities.
   Resonator T1 = Qi / (2π × f) — the lifetime of a microwave photon stored
   in the resonator. Qubit T1 = energy relaxation time of the qubit state.
   A resonator-only paper reporting "T1 = 50 µs" means photon lifetime, not
   qubit coherence. Always set T1_measurement_context to identify which is
   being reported. If the paper fabricated a qubit and measured its T1 directly
   → qubit_state. If T1 is derived from Qi or measured on a bare resonator
   → resonator_photon. When in doubt, check whether a Josephson junction
   and qubit readout circuit are present.

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
RESONATOR GEOMETRY — EXTRACT THESE IF PRESENT
---

These fields are critical for connecting resonator quality factor measurements
to qubit pad loss tangents. Without them, we cannot accurately convert a
reported Q_TLS,0 into a material loss tangent (tan_delta).

Q_TLS_0:
  The unsaturated TLS quality factor extracted from power and temperature sweeps
  of resonator Q_int. This is PREFERRED over raw Q_int because it is the
  single-photon regime value relevant to qubit operation.
  Often reported as "Q_TLS,0", "Q_TLS", or "inverse linear absorption from TLSs".
  Source: Table of resonator parameters, or stated in text after fitting Eq. S2 or similar.

resonator_type:
  The type of resonator used to measure Q_int or Q_TLS,0.
  Values: CPW (coplanar waveguide), lumped_element, other.
  Source: Methods or device description section.

resonator_gap_width_um:
  For CPW resonators: the gap width s between the center conductor and ground plane,
  in microns. This is the single most important geometric parameter for computing
  the surface participation ratio p_MS_resonator.
  Look for: "gap width s = X µm", "CPW with s = X µm", resonator geometry tables.
  For lumped element resonators: the capacitor gap width, in microns.
  Source: Methods section, device geometry table, or figure caption.

p_MS_resonator:
  The surface participation ratio of the metal-substrate interface for the resonator.
  This may be directly reported (computed from FEM simulation), or it can be looked
  up from a geometry table if the gap width is known.
  Often reported as "p_MS", "SPR", or "surface participation ratio".
  Look for: tables of resonator parameters listing p_MS alongside Q_TLS,0,
  plots of Q_TLS,0 vs p_MS (the slope gives tan_delta), FEM simulation results.
  Source: Supplementary Table, Figure caption (Q vs SPR plots), simulation section.

p_MS_pad:
  The surface participation ratio of the metal-substrate interface for the qubit
  capacitor pads. Physically distinct from p_MS_resonator — qubit pads are
  designed to have much lower p_MS than resonators.
  Often reported as "p_MS of the qubit", "qubit SPR", or stated as a design parameter.
  Look for: "qubits are designed with p_MS of X", HFSS simulation results for qubit geometry,
  tables comparing resonator and qubit participation ratios.
  Source: Main text, supplementary simulation section.
  
qubit_frequency_GHz:
  The qubit operating frequency in GHz. Required for pad TLS loss calculation.
  Look for: qubit characterization tables, frequency listed alongside T1/T2,
  "fq = X GHz", "qubit frequency X GHz", spectroscopy results.
  Source: Table of qubit parameters, main text, or figure caption.
  Note: this is the qubit transition frequency, not the readout resonator frequency.
  Convert MHz to GHz if needed.

WHY THESE MATTER:
  tan_delta = 1 / (Q_TLS,0 × p_MS_resonator)        [calibration from resonator]
  T1_pad_TLS = 1 / (p_MS_pad × tan_delta × 2π × f)   [applied to qubit pad]
  Without p_MS_resonator, Q_TLS,0 alone cannot give tan_delta.
  Without p_MS_pad, tan_delta alone cannot give qubit T1.
  A 6x range in p_MS_resonator (from CPW gap width variation) leads to 6x
  uncertainty in tan_delta — so capturing this geometry is high priority.

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


# =============================================================================
# PROMPT 3 — SIMILARITY PROFILE GENERATION
# =============================================================================
#
# Sent once per sample (not per paper) after Pass 2 extraction is complete.
# Input: the full extracted sample record including all structured fields
#        and the complete catchall.
# Output: a structured similarity_profile dict with controlled vocabulary.
#
# Design principles:
# - Every dimension uses a controlled vocabulary defined here.
# - Claude picks from the vocabulary; it does not invent new terms.
# - The profile version is embedded so we can detect stale profiles after
#   vocabulary updates and selectively re-run Pass 3.
# - Output is per-sample, not per-paper.

PROFILE_VERSION = "1.0"

_PROFILE_VOCAB = {
    "material_class": [
        # Simple elements
        "niobium", "aluminum", "tantalum", "rhenium", "titanium",
        "vanadium", "indium", "tin", "lead",
        # Nitrides
        "titanium_nitride", "niobium_nitride", "niobium_titanium_nitride", "tantalum_nitride",
        # Silicides
        "platinum_silicide", "cobalt_silicide", "vanadium_silicide",
        "molybdenum_silicide", "tungsten_silicide", "other_silicide",
        # Germanides
        "platinum_germanide", "cobalt_germanide", "other_germanide",
        # Alloys
        "niobium_titanium", "tantalum_hafnium", "aluminum_manganese", "other_alloy",
        # Oxides
        "indium_oxide", "other_oxide",
        # Catch-all
        "other"
    ],
    "transport_regime": [
        "clean_limit",    # mean free path l > coherence length xi; vortex motion dominant
        "dirty_limit",    # mean free path l < coherence length xi; different loss mechanisms
        "intermediate",   # l ~ xi; both mechanisms relevant
        "unknown"         # insufficient information to determine
    ],
    "loss_mechanisms": [
        # List field — pick all that apply
        "TLS_substrate",              # two-level systems in the substrate bulk
        "TLS_interface",              # TLS at metal-substrate or metal-vacuum interface
        "TLS_metal_vacuum",           # TLS at the metal-air interface specifically
        "TLS_unattributed",           # TLS dominant but interface not identified
        "quasiparticle",              # quasiparticle loss channel
        "vortex_motion",              # vortex motion loss (common in clean-limit films)
        "radiation",                  # radiative loss out of resonator/qubit
        "dielectric_substrate",       # bulk dielectric loss in substrate
        "surface_oxide",              # loss attributed to surface oxide layer
        "flux_noise",                 # flux noise driven dephasing
        "charge_noise",               # charge noise driven dephasing
        "unknown"                     # loss measured but mechanism not identified
    ],
    "device_type": [
        "film_only",                  # no patterned device; R vs T, XRD, surface characterization
        "resonator",                  # microwave resonator (coplanar waveguide, lumped element, etc.)
        "transmon",                   # transmon qubit
        "fluxonium",                  # fluxonium qubit
        "gatemon",                    # gatemon (semiconductor-based) qubit
        "kinetic_inductance_detector",# MKID or KID — not a qubit but related
        "junction_only",              # Josephson junction characterization without full qubit
        "multi_qubit_device",         # multi-qubit processor or array
        "unknown"
    ],
    "coherence_tier": [
        "not_applicable",             # film_only paper; no device performance measured
        "early_exploration",          # T1 < 10 µs or Qi < 1e5; material not yet optimized
        "competitive",                # T1 10-100 µs or Qi 1e5-1e6; solid but not leading
        "state_of_the_art"            # T1 > 100 µs or Qi > 1e6; among the best reported
    ],
    "science_focus": [
        # List field — pick all that apply
        "process_optimization",       # varying fabrication parameters to improve performance
        "loss_mechanism_identification", # decomposing loss budget, attributing dominant channel
        "materials_characterization", # characterizing film properties (RRR, Tc, crystal phase)
        "device_demonstration",       # demonstrating qubit or resonator performance
        "cross_platform_comparison",  # comparing different materials or processes side by side
        "noise_characterization",     # flux noise, charge noise, 1/f noise studies
        "surface_treatment",          # surface cleaning, passivation, etching studies
        "junction_engineering",       # Josephson junction optimization
        "scaling"                     # multi-qubit, yield, uniformity studies
    ],
    "growth_method": [
        "sputtering",                 # DC or RF magnetron sputtering
        "MBE",                        # molecular beam epitaxy
        "ALD",                        # atomic layer deposition
        "CVD",                        # chemical vapor deposition
        "evaporation",                # thermal or e-beam evaporation
        "other"
    ],
    "key_correlations": [
        # List field — pick all that the paper explicitly reports or implies.
        # These are drawn from the Block 5 domain knowledge glossary.
        # Only include if the paper presents evidence for the connection.
        "RRR_to_quasiparticle_density",
        "RRR_to_T1",
        "RRR_to_Qi",
        "Tc_to_operating_margin",
        "crystal_phase_to_loss",
        "anneal_to_crystal_phase",
        "anneal_to_RRR",
        "anneal_to_T1",
        "anneal_to_Qi",
        "surface_oxide_to_TLS",
        "surface_oxide_to_Qi",
        "surface_oxide_to_T1",
        "film_thickness_to_loss",
        "substrate_to_TLS",
        "clean_limit_to_vortex_loss",
        "dirty_limit_to_quasiparticle_loss",
        "mean_free_path_to_coherence_length",
        "deposition_conditions_to_film_purity",
        "loss_tangent_to_T1",
        "Qi_to_T1_upper_bound",
        "gate_fidelity_to_module_count"
    ]
}

_PROFILE_SCHEMA = {
    "sample_id": "<same sample_id as in the extraction record>",
    "material_class": "<single value from material_class vocabulary>",
    "transport_regime": "<single value from transport_regime vocabulary>",
    "loss_mechanisms": ["<one or more values from loss_mechanisms vocabulary>"],
    "device_type": "<single value from device_type vocabulary>",
    "coherence_tier": "<single value from coherence_tier vocabulary>",
    "science_focus": ["<one or more values from science_focus vocabulary>"],
    "growth_method": "<single value from growth_method vocabulary>",
    "key_correlations": ["<zero or more values from key_correlations vocabulary>"],
    "profile_notes": "<one or two sentences explaining any non-obvious choices, or null>"
}

_PROFILE_SCHEMA_STR = json.dumps(_PROFILE_SCHEMA, indent=2)
_PROFILE_VOCAB_STR  = json.dumps(_PROFILE_VOCAB,  indent=2)


def _flatten_sample_for_profile(sample: dict) -> dict:
    """
    Flatten confidence/source wrapper dicts to plain values for the profile prompt.
    {"value": "NbSe2", "confidence": "high", "source": "..."} → "NbSe2"
    """
    flattened = {}
    for k, v in sample.items():
        if isinstance(v, dict) and "value" in v:
            flattened[k] = v["value"]
        else:
            flattened[k] = v
    return flattened

def build_profile_prompt(sample_record: dict) -> str:
    """
    Build the Pass 3 prompt for a single extracted sample record.
    sample_record should be the full sample dict from the Pass 2 extraction,
    including all structured fields and the complete catchall.
    """
    if isinstance(sample_record, list):
        flattened = [_flatten_sample_for_profile(s) for s in sample_record]
    else:
        flattened = _flatten_sample_for_profile(sample_record)
    sample_json = json.dumps(flattened, indent=2)

    return f"""
You are generating a similarity profile for a single materials characterization sample.
This profile will be used to find scientifically similar samples across a large corpus
of superconducting qubit materials papers.

Your job is to read the full sample record below — including all structured fields
and the catchall — and assign values from the controlled vocabularies provided.

The profile must be:
  - Grounded in the sample record. Do not invent properties not supported by the data.
  - Concise. Pick the most specific applicable term, not multiple vague ones.
  - Honest about uncertainty. If a dimension cannot be determined from the record,
    use the appropriate "unknown" or "not_applicable" value.

---
CONTROLLED VOCABULARIES
---

These are the ONLY valid values for each dimension.
Do not use values outside these lists.

{_PROFILE_VOCAB_STR}

---
DIMENSION GUIDANCE
---

material_class:
  Pick the primary superconducting film material.
  Use the most specific term available — "platinum_silicide" not "other_silicide".
  For junction devices (e.g. Ta with Al/AlOx junction), use the primary film
  material (Ta → "tantalum"), not the junction material.

  Chemical formula → vocabulary term mapping:
    Nb, niobium film           → niobium
    Al, aluminum film          → aluminum
    Ta, tantalum film          → tantalum
    Re, rhenium film           → rhenium
    TiN                        → titanium_nitride
    NbN                        → niobium_nitride
    NbTiN                      → niobium_titanium_nitride
    TaN                        → tantalum_nitride
    Ta-Hf alloy                → tantalum_hafnium
    NbSe2, niobium diselenide  → niobium_diselenide
    PtSi, platinum silicide    → platinum_silicide
    Mo3Al2C                    → other (not yet in vocabulary)

transport_regime:
  Infer from RRR, mean free path vs coherence length ratio, crystal phase,
  and any explicit author statements.
  - High RRR (>50 for Ta/Nb) → clean_limit
  - Low RRR (<10) → dirty_limit
  - If not determinable → unknown
  For nitrides (TiN, NbTiN, NbN), dirty_limit is almost always correct.
  For silicides and germanides with limited data → unknown.

loss_mechanisms:
  List ALL loss channels the paper identifies or investigates, even if not dominant.
  Draw from the catchall correlations_observed and additional_measurements, not just
  the structured fields. If the paper measures Qi but does not attribute the loss → unknown.
  For film_only papers with no microwave measurement → omit (empty list is fine).

device_type:
  Use the most specific device actually fabricated and measured.
  film_only: R vs T, XRD, AFM, surface characterization — no patterned microwave device.
  If the paper does both film characterization AND resonator measurements → resonator.

coherence_tier:
  Base this on the best performance reported for this sample, not the paper average.
  Use the T1_measurement_context field to determine which thresholds apply:
    qubit_state T1 thresholds (direct qubit measurement — gold):
      not_applicable:    film_only — no device performance measured
      early_exploration: T1 < 10 µs
      competitive:       T1 10–100 µs
      state_of_the_art:  T1 > 100 µs
    resonator_photon thresholds (Qi — material proxy, not qubit T1):
      not_applicable:    film_only — no microwave device measured
      early_exploration: Qi < 1e5
      competitive:       Qi 1e5–1e6
      state_of_the_art:  Qi > 1e6
  Do NOT mix these: a resonator with Qi = 3e6 is state_of_the_art as a resonator,
  but this does NOT imply qubit T1 > 100 µs. The qubit T1 depends on pad and
  junction geometry in ways the resonator Qi does not capture directly.
  When T1_measurement_context is absent, infer from device_type:
    resonator → use Qi thresholds
    transmon / fluxonium / gatemon → use qubit T1 thresholds
    film_only → not_applicable

science_focus:
  Pick ALL that apply — this is a list field.
  Focus on what the paper is actually trying to answer, not just what it measures.
  A paper that varies anneal temperature and measures T1 is process_optimization
  AND materials_characterization, even if it also demonstrates a device.

growth_method:
  Use the primary deposition method for the superconducting film.
  If multiple methods are compared → pick the one for this specific sample.

key_correlations:
  Only include correlations the paper explicitly presents evidence for —
  either in the structured correlations_observed catchall entries, or clearly
  stated in the paper's conclusions.
  Do NOT infer correlations yourself. If no correlations are evidenced → empty list.

profile_notes:
  Use this to explain any non-obvious assignments — e.g. why you chose
  "dirty_limit" despite limited RRR data, or why a junction paper is classified
  as "film_only" for coherence_tier. Keep to one or two sentences. Null if not needed.

---
SAMPLE RECORD
---

{sample_json}

---
OUTPUT
---

Return a JSON array containing one profile object per sample in the record.
If the record contains multiple samples, return one object per sample,
each with its own sample_id matching the extraction record.

Return ONLY raw valid JSON — a JSON array. No markdown fences. No text before or after.

Example output for a two-sample record:
[
  {{ "sample_id": "Sample_A", "material_class": "tantalum", ... }},
  {{ "sample_id": "Sample_B", "material_class": "tantalum", ... }}
]

Schema for each object:
{_PROFILE_SCHEMA_STR}
""".strip()
