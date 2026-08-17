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
#   v4 — fabrication process chemistry fields and prompt section; new fabrication_details
#        catchall type; junction_oxidation_conditions → junction_oxidation_protocol;
#        junction_pre_deposition_clean → junction_pre_deposition_surface_treatment
#   v5-fabgroup (in progress, test_single validation only — not yet in the v5 bundle) —
#        FABRICATION GROUPING section added. New paper-level fabrication_groups array
#        (group_id, raw_label, member_sample_ids, basis, evidence, confidence, source)
#        and new per-sample fabrication_group_id reference field. Addresses July audit
#        finding #1 (pseudoreplication risk — e.g. one fab batch producing 57 "qubits"
#        counted as 57 independent samples in Phase A). group_id is paper-local
#        ("fab1", "fab2", ...), matching how sample_id is paper-local and display_name
#        is computed from it later — canonical fabrication_group_id namespacing is
#        Phase 5 build_sqlite.py work, not done here.
#   v5-fabgroup rev2 (test_single validation, iteration 2) — two fixes from first
#        test_single run against Bland/Olszewski/Joshi:
#          1. SAME PHYSICAL ORIGIN, NOT MERELY SAME RECIPE rule — Joshi run merged two
#             separate depositions (films F15, F16) into one group because they shared
#             a recipe description. Added explicit rule: same recipe on separate runs
#             is NOT sufficient evidence of a shared group; only same physical
#             wafer/run/batch is. Prefer splitting when ambiguous (cheaper error).
#          2. SELF-CONSISTENCY CHECK — Bland run's fab_UHV group evidence text named
#             two resonator samples as sharing that fab origin, but neither was added
#             to member_sample_ids. Added instruction to reconcile evidence text against
#             member_sample_ids before returning output.
#   v5-fabgroup rev3 (test_single validation, iteration 3) — rev2's two fixes did not
#        hold up on re-test: the resonators were STILL dropped (evidence used a
#        category phrase, "the resonator samples," not a literal sample_id, so there
#        was nothing concrete to self-check against), and Joshi's F15/F16 qubits
#        stayed merged (correctly — the paper never discloses which qubit came from
#        which film, so no split is actually derivable from the text). Concluded that
#        asking Claude to silently self-correct isn't reliable for these borderline
#        calls, and that some ambiguity (like Joshi F15/F16) is a genuine property of
#        the source paper, not a fixable extraction bug. Shifted the design goal from
#        "get it right" to "make every judgment call reviewable by a human":
#          - New excluded_candidates field per group: samples the evidence discusses
#            as plausibly related but not included as members, with a stated reason.
#            Required, not optional, whenever such a sample is mentioned.
#          - Evidence must cite exact sample_id strings, never category language
#            ("the resonator samples") — makes evidence mechanically checkable against
#            membership, both by Claude and by any later automated audit.
#          - New individual_assignment_disclosed (true/false) field — flags groups
#            where the paper only makes a set-level shared-origin claim without
#            stating which specific sample maps to which physical run (the Joshi
#            case), so a reviewer knows this group's confidence is capped by what the
#            paper reports, not by extraction quality.
#   v5-t2context (test_single validation, Phase 4 item #4) — new T2_unspecified_us
#        field. Previously, T2 values with no stated sequence type were defaulted
#        into T2_echo_us with medium confidence — a base-rate guess ("most modern
#        qubit papers default to echo") baked silently into a field meant to hold
#        confirmed echo measurements. Genuinely unlabeled T2 values now go into
#        T2_unspecified_us instead; T2_echo_us / T2_ramsey_us are only used when the
#        paper states the sequence somewhere, even a single global methods
#        statement. NOTE FOR build_sqlite.py (Phase 5, not yet built): derived_T2_us
#        should fall back to T2_unspecified_us as a third option (echo preferred,
#        then Ramsey, then unspecified) rather than excluding it, per explicit user
#        preference — these values should stay visible in the Explorer visualizer,
#        not silently drop out of "best available T2."
#   v5-fields (Phase 4 item #3, AVAILABLE_FIELDS reconciliation) — added 12 fields
#        that were fully documented in the schema doc and fully wired in
#        build_sqlite.py (real CREATE TABLE column + INSERT + gf() call) but
#        missing from this file's extraction schema — confirmed via direct
#        cross-check against build_sqlite.py before writing anything, not assumed
#        from the docs. Several had complete, correct prose elsewhere in this file
#        already instructing Claude to extract them as named fields (the "R vs T
#        CURVES" and tan_delta_effective_surface disambiguation sections) — the
#        prose was right, there was just nowhere for the answer to go. Fields
#        added: normal_state_resistivity_uOhm_cm, normal_state_resistance_Ohm,
#        room_temperature_resistance_Ohm, measured_structure_width_um,
#        measured_structure_length_um, loss_tangent_substrate_frequency_GHz,
#        loss_tangent_substrate_temperature_mK, loss_tangent_interface_type,
#        tan_delta_effective_surface, Qi_measurement_frequency_GHz,
#        Qi_measurement_temperature_mK, Qi_measurement_power_dBm. New prose added
#        only for loss_tangent_interface_type (a new enum) and a caution against
#        guessing which sweep condition pairs with an already-extracted Qi/loss-
#        tangent value. NOT wired: junction_material, junction_area_um2,
#        junction_fabrication_method, junction_resistance_normal_Ohm — confirmed
#        genuinely absent from BOTH this file and build_sqlite.py (no column at
#        all, not just a missing schema slot); deliberately treated as a separate,
#        larger sub-task since it needs build_sqlite.py work too, not folded in
#        here.
#   v5-fields rev2 (Phase 4 item #3, iteration 2) — two guidance fixes found by
#        checking real papers (Joshi 2026, Olszewski 2026) against the actual
#        extraction the v5-fields prompt produced, not by inspection alone:
#          1. BORROWED VALUES ACROSS SAMPLES — Joshi's normal_state_resistivity_uOhm_cm
#             was applied to three samples (a Hall bar it was measured on, a
#             resonator, and a qubit) from a single-value measurement described in
#             the main text without being tied to a specific film. One borrowed
#             application got a medium-confidence inferential caveat, the other did
#             not — same underlying situation, inconsistent treatment. Added an
#             explicit rule, reusing the same physical-origin-vs-shared-recipe
#             distinction already established for fabrication grouping: confidence
#             must be downgraded consistently every time a value is borrowed across
#             samples on shared-recipe (not confirmed shared-origin) grounds, not
#             just some of the times.
#          2. LOSS REPORTED INSTEAD OF Qi — Olszewski reports resonator performance
#             as loss (δ = 1/Qi, stated explicitly as Eq. 3) rather than as Qi
#             directly. Nothing told Claude to invert a reported low-power loss into
#             Qi_single_photon, so the new Qi_measurement_temperature_mK context
#             field populated from the paper's fridge table with no Qi value to
#             pair it with — a context field with nothing to give context to.
#             Added explicit conversion guidance, restricted to loss values the
#             paper itself identifies as the single-photon/sub-single-photon
#             regime, with an explicit instruction not to guess when the regime
#             isn't stated.
#        Not yet re-validated via test_single as of this edit.
#   v5-fields Pass B (junction identity fields) — added junction_material,
#        junction_fabrication_method, junction_area_um2,
#        junction_resistance_normal_Ohm. These were the 4 of 16 AVAILABLE_FIELDS
#        gap items confirmed missing from BOTH prompts.py and build_sqlite.py (not
#        just this file), so build_sqlite.py was updated in the same pass — new
#        CREATE TABLE columns, INSERT wiring, and confidence columns, verified by a
#        live SQL execution smoke test. Two of the four fields already had
#        orphaned, correct disambiguation prose elsewhere in this file (worked
#        examples assigning values to "junction_material" in the film_material vs
#        junction_material section) despite never having a schema slot — same
#        pattern as tan_delta_effective_surface and normal_state_resistivity_uOhm_cm
#        in Pass A. Also fixed a now-stale instruction this session had itself
#        introduced ("junction Rn values go in the catchall") since
#        junction_resistance_normal_Ohm is now a real field; added explicit
#        disambiguation against normal_state_resistance_Ohm (the film R-vs-T field,
#        typically Ohms) since junction resistance is typically kOhms and the two
#        are easy to confuse by name alone. Not yet test_single-validated.
#   v5-fields-passB + version lineage stamps (Phase 4 item #5) — added
#        SCHEMA_VERSION and EXTRACTION_PROMPT_VERSION constants below. No
#        change to prompt content or the extraction schema Claude sees —
#        these are pipeline-level provenance stamps attached by
#        pipeline_ingest.py, never sent to or returned by Claude, so this
#        entry does not itself represent a new prompt state. Kept here
#        (rather than in pipeline_ingest.py) because this file is the
#        natural single source of truth for both version numbers.
#   v5-range-consistency — added RANGE-TO-POINT ESTIMATE CONSISTENCY guidance
#        (junction area/resistance section), a companion rule to BORROWED
#        VALUES ACROSS SAMPLES. Fixes the Aug 11 Joshi finding: a paper-wide
#        target range converted to a point estimate (e.g. junction area
#        midpoint) was applied to only the first sample in the batch instead
#        of every sample the range covers, while a directly-analogous
#        resistance value from the same paper was applied correctly to all
#        11 qubits. test_single-validated against Joshi 2026 directly:
#        junction_area_um2 now lands on all 11 qubits, matching
#        junction_resistance_normal_Ohm's already-correct behavior.
#   v5-group-membership-exclusivity — added an explicit rule to FABRICATION
#        GROUPING: a sample_id cannot appear in both member_sample_ids and
#        excluded_candidates for the same group. Fixes an Aug 13 WangY 2026
#        finding from the first Phase 6 combined test: Re_film_characterization
#        was listed in excluded_candidates with reasoning that argued against
#        inclusion and then concluded "included/retained anyway" — but was
#        never actually added to member_sample_ids, leaving the sample's own
#        fabrication_group_id field, the group's member list, and the group's
#        excluded_candidates list disagreeing with each other about whether
#        it belongs. A genuine self-consistency failure (the model contradicted
#        its own conclusion within one output), not a defensible ambiguous-
#        evidence judgment call like the earlier Olszewski
#        individual_assignment_disclosed case — judged worth fixing directly
#        rather than logging as an accepted imperfection. test_single-validated
#        against WangY 2026 directly: no overlap between the two lists, and
#        the sample's own fabrication_group_id field now correctly agrees
#        with the group's excluded_candidates entry.
#   v5-cooldown-samples — added MULTIPLE COOLDOWNS OF THE SAME PHYSICAL DEVICE
#        guidance to KNOWN EXTRACTION ERRORS TO AVOID. Fixes an Aug 13 Nho 2026
#        finding: re-running the same paper under the current prompt produced
#        9 samples instead of the 12 already in records.db, silently dropping
#        real, materially different cooldown data for at least device B2
#        (T1/frequency/δΔ all differ between its 2022.12 and 2023.01 cooldowns
#        per the paper's own Table S1) with no trace anywhere that a second
#        cooldown existed. Verified against the actual paper (Table S1) before
#        writing this fix — multiple devices (B2, M2, M3, S1, S2) have
#        genuinely distinct per-cooldown values, not repeat measurements of
#        the same number. Note: even the original 12-sample records.db
#        extraction wasn't a complete capture either (it kept only 2 of M3's
#        5 documented cooldowns, 1 of S1's 3, 1 of S2's 2) — there was never
#        an explicit, consistently-applied rule here before this fix. Not yet
#        test_single-validated.
import json

# =============================================================================
# VERSION LINEAGE CONSTANTS
# =============================================================================
# Manual sync points, like the version-history comment block above:
#   SCHEMA_VERSION            — update whenever materials_characterization_schema_vNN.md's
#                                own front-matter version number changes. Tracks the
#                                doc's actively-changing version, not the frozen
#                                "Implementation Status (v0.8)" label.
#   EXTRACTION_PROMPT_VERSION — update whenever a change to this file's Pass 2
#                                extraction schema/prompt text is made — i.e. whenever
#                                a new entry is added to the version-history comment
#                                block above. Does NOT change for edits that don't
#                                touch prompt content (like this one).
SCHEMA_VERSION = "0.19"
EXTRACTION_PROMPT_VERSION = "v5-cooldown-samples"
# =============================================================================
# PROMPT 1 — RELEVANCE CHECK
# =============================================================================
_RELEVANCE_SCHEMA = {
    "relevance": "<high | medium | low>",
    "relevance_reason": "<one sentence explaining the relevance decision>",
    "funding_acknowledgments": "<any center/grant funding acknowledgments found, or null>",
    "device_performance_without_material_context": "<true if this paper reports real experimental superconducting device performance (T1, T2, gate fidelity, readout fidelity, Qi, etc.) but relevance is low or medium specifically because no material or fabrication context is documented for that device — false otherwise, including all theory/algorithm papers and all off-domain papers (NV centers, other qubit modalities, photonics, etc.) where the low/medium relevance has nothing to do with missing material context>",
    "paper_type": "<primary | review | process_comparison | unclear>",
    "paper_type_reason": "<one sentence explaining the type decision>",
    "doi": "<DOI string if found in paper, or null>",
    "arxiv_id": "<arXiv ID if found e.g. 2301.12345, or null>",
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
  4. What is the arXiv ID? (look for arXiv:XXXX.XXXXX on the first page header or footer)
---
RELEVANCE CRITERIA
---
To be HIGH or MEDIUM relevance, a paper must satisfy at least ONE of the
following ORIGINAL CONTENT criteria. A funding acknowledgment (C2QA or any
other center) alone does NOT satisfy any of these — note it in
funding_acknowledgments for downstream triage priority, but it does not by
itself make a paper eligible.

  1. Original superconducting material or interface characterization
     (e.g. Tc, RRR, crystal phase, surface/interface properties measured
     on a superconducting film)
  2. Original fabrication or process comparison (systematically varying
     a process parameter and reporting the resulting material or device
     properties)
  3. Original superconducting resonator loss measurement (Qi, Q_TLS,0,
     loss tangent, TLS density)
  4. Original qubit measurement (T1, T2, gate fidelity) reported with
     documented material or fabrication context
  5. Original Josephson junction material or process characterization

These criteria do NOT require the paper to be framed around qubits or
quantum computing explicitly — a paper reporting original superconducting
material properties is eligible even with no mention of qubits, so long
as it satisfies one of the five criteria above.

Note on review papers (paper_type = review): matching one of these
criteria on subject matter is sufficient even though the paper synthesizes
rather than originates the data. Pass 2 already produces zero sample
records for review papers regardless of relevance level, so there is no
risk of a review's compiled data being misattributed as this paper's own
measurement — reviews remain valuable for the primary-paper leads and
schema-evolution ideas they generate via review_outputs.

HIGH relevance:
  - Satisfies at least one of the five criteria above, AND
  - Reports on materials explicitly used in superconducting qubits:
    Ta, Nb, Al, TiN, NbTiN, TaN, NbN, Re, PtSi, or alloys thereof

MEDIUM relevance — ingest material properties only, flag application:
  - Satisfies at least one of the five criteria above, but either:
    - reports on a material not in the HIGH list, OR
    - the application is non-qubit (SNSPDs, accelerator cavities, TWPAs)

LOW relevance — skip entirely:
  - Does not satisfy any of the five criteria above, regardless of any
    funding acknowledgment present
  - Classical materials with no superconducting content
  - Superconducting power applications (motors, cables, magnets)
  - High-Tc superconductors not relevant to quantum circuits
  - Purely theoretical papers with no experimental measurements

DEVICE PERFORMANCE WITHOUT MATERIAL CONTEXT — a specific, narrow flag:
  Set device_performance_without_material_context to true ONLY when the
  paper reports real experimental performance data on an actual
  superconducting device (T1, T2, gate fidelity, readout fidelity, Qi,
  etc.) — real numbers, real hardware — but relevance came out low or
  medium specifically because no material or fabrication context is
  documented for that device. This is the "real data, no materials
  story" case, e.g. benchmarking on a public cloud backend, or a paper
  whose focus is control/readout engineering rather than materials, where
  device coherence numbers are reported incidentally.
  Do NOT set this true for:
    - Theory or algorithm papers with no experimental data at all
    - Papers about a different qubit modality (NV centers, spin qubits,
      trapped ions) — these are off-domain, not "missing material context"
    - Any other reason for low relevance unrelated to material context
  When in doubt, leave it false — this flag exists to surface a narrow,
  specific pattern for human review, not as a general "close call" flag.
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
            # --- Fabrication grouping (linkage, not a measurement — no confidence/source wrapper here.
            # The evidence for this link lives once on the fabrication_groups entry, not duplicated per sample.) ---
            "fabrication_group_id": "<group_id of the fabrication_groups entry (below) this sample belongs to — omit this field entirely if there is no paper evidence linking this sample's fabrication origin to any other sample>",
            # --- Block 2.5: Base-layer fabrication process chemistry ---
            "substrate_prep_before_deposition": {"value": "<free text: oxide removal chemistry, cleaning sequence, transfer time constraint, in situ heating context>", "confidence": "<high|medium|low>", "source": "<location>"},
            "in_situ_substrate_bake_temperature_C": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "film_deposition_conditions": {"value": "<free text: deposition rate, sputtering power, gas pressure, gas flow ratios, any other deposition parameters>", "confidence": "<high|medium|low>", "source": "<location>"},
            "film_etch_chemistry": {"value": "<free text: etch type, gas chemistry, ICP power, RF bias, chamber pressure, gas flows, chamber conditioning>", "confidence": "<high|medium|low>", "source": "<location>"},
            "resist_strip_chemistry": {"value": "<free text: solvent identity, temperature, duration, sonication sequence>", "confidence": "<high|medium|low>", "source": "<location>"},
            "post_fabrication_surface_treatment": {"value": "<free text: chemical identity, concentration, temperature, duration, sequence, or 'none'>", "confidence": "<high|medium|low>", "source": "<location>"},
            "dicing_protocol": {"value": "<free text: resist used, dicing parameters, strip chemistry after dicing>", "confidence": "<high|medium|low>", "source": "<location>"},
            # --- Block 2.3: Junction presence and properties ---
            "junction_present": {"value": "<true|false>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_material": {"value": "<free text, e.g. 'Al/AlOx/Al', 'Nb/AlOx/Nb' — junction material only, never the superconducting film material>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_fabrication_method": {"value": "<free text, e.g. 'double-angle evaporation', 'overlap junction', 'bridge-free junction'>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_area_um2": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_resistance_normal_Ohm": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            # --- Block 2.3 extensions: Junction fabrication process chemistry ---
            # Only populate these fields if junction_present is true
            "junction_pre_deposition_surface_treatment": {"value": "<free text: ex-situ treatments (BOE, descum) and/or in-situ treatments (ion mill: bias voltage, duration, angle)>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_developer": {"value": "<free text: developer composition, temperature, duration>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_chamber_vacuum": {"value": "<free text: HV/UHV, base pressure, system name if stated>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_oxidation_protocol": {"value": "<free text: oxidation step(s): pressure, time, gas; multi-step sequences common e.g. '50 mbar O2 15 min + 10 mbar O2 20 min'>", "confidence": "<high|medium|low>", "source": "<location>"},
            "junction_liftoff_chemistry": {"value": "<free text: solvent, temperature, duration, sonication steps>", "confidence": "<high|medium|low>", "source": "<location>"},
            # --- Block 3: Structured measurements ---
            "Tc_K": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "RRR": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "sheet_resistance_Ohm_sq": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "normal_state_resistivity_uOhm_cm": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            # --- R vs T measurement geometry — enables sheet resistance / RRR derivation
            # when not directly reported. See "R vs T CURVES" prose section below, which
            # already fully specifies how to read these; this schema addition just gives
            # that existing guidance somewhere to actually write its answer. ---
            "normal_state_resistance_Ohm": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "room_temperature_resistance_Ohm": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "measured_structure_width_um": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "measured_structure_length_um": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "loss_tangent_substrate": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "loss_tangent_substrate_frequency_GHz": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "loss_tangent_substrate_temperature_mK": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "loss_tangent_interface": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "loss_tangent_interface_type": {"value": "<metal_substrate | metal_vacuum | substrate_vacuum>", "confidence": "<high|medium|low>", "source": "<location>"},
            "tan_delta_effective_surface": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "TLS_density_per_GHz_per_um2": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "Qi_internal_quality_factor": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "Qi_single_photon": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "Qi_measurement_frequency_GHz": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "Qi_measurement_temperature_mK": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "Qi_measurement_power_dBm": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
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
            "T2_ramsey_us": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
            "T2_unspecified_us": {"value": "<number>", "confidence": "<high|medium|low>", "source": "<location>"},
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
                "fabrication_details": [
                    {"description": "<specific fabrication step or process detail not captured in named fields>",
                     "source": "<location in paper>"}
                ],
                "schema_promotion_candidates": [
                    {"parameter": "<parameter name>", "description": "<what it measures and its units>",
                     "why_important": "<specific scientific reason this should be a structured field>",
                     "source": "<location>"}
                ],
                "free_notes": "<cross-sample observations, processing context not captured elsewhere>"
            }
        }
    ],
    "fabrication_groups": [
        {
            "group_id": "<paper-local identifier, e.g. 'fab1', 'fab2' — assign sequentially by order of first appearance in the paper. Paper-local, like sample_id; not a corpus-wide identifier>",
            "raw_label": "<the paper's own stated identifier for this batch/wafer/run, e.g. 'wafer W1', or null if the paper never used an explicit identifier>",
            "member_sample_ids": ["<sample_id>", "<sample_id>", "..."],
            "excluded_candidates": [
                {"sample_id": "<a sample_id the evidence text discusses as plausibly sharing this fabrication origin, but that you decided NOT to include as a member>",
                 "reason": "<why you excluded it — e.g. 'paper states this device shares the same film deposition but does not confirm it came from the same physical run as the qubits'>"}
            ],
            "individual_assignment_disclosed": "<true | false — true only if the paper states which specific sample_id(s) map to which specific physical run/wafer/film within this group. false if the paper only asserts a set-level relationship (e.g. '11 qubits across films F15 and F16') without saying which qubit came from which film — in that case member_sample_ids may still include all of them, but this flag tells a reviewer the per-sample mapping is not independently verifiable from the text>",
            "basis": "<explicit | implicit_inferred>",
            "evidence": "<the specific paper language supporting this grouping — quote or close paraphrase. MUST reference member sample_ids by their exact string when discussing which samples belong (not a category description like 'the resonator samples') — e.g. 'Methods states devices D1-D14 were fabricated from a single wafer W1' or 'Methods describes one fabrication process producing qubit_1 through qubit_45, each then characterized separately; no per-device process variation is mentioned'>",
            "confidence": "<high | medium | low>",
            "source": "<location in paper>"
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
            "If a paper reports film characterization data (Tc, RRR, grain size, "
            "roughness) in one table AND resonator or device measurements (loss tangent, "
            "Qi, Q_TLS,0) in a separate table, extract BOTH as separate sample records — "
            "one per film condition AND one per resonator chip. Do not collapse film "
            "characterization data into resonator records or vice versa. "
            "AFTER you have listed every sample, apply the FABRICATION GROUPING guidance "
            "below to determine whether any of these samples share a fabrication origin. "
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
            "e.g. 'Table I Row 3'. Process comparison studies commonly involve two or "
            "more distinct fabrication batches (e.g. a two-wafer comparison) — after "
            "listing every sample, apply the FABRICATION GROUPING guidance below; expect "
            "multiple fabrication_groups entries, one per compared process/batch, not one "
            "group for the whole paper. Omit review_outputs from your response entirely."
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
- loss_tangent_interface vs tan_delta_effective_surface: these are different fields.
  loss_tangent_interface is for a per-interface loss tangent (MS, SA, or MA separately).
  tan_delta_effective_surface is the COLLAPSED effective surface loss tangent extracted
  from fitting Q_TLS,0 vs p_MS across multiple resonators — the slope of that line.
  If a paper reports a single "surface loss tangent" or "tan delta" from a Q_TLS,0 vs SPR
  fit, put it in tan_delta_effective_surface, NOT loss_tangent_interface.
  PARTICIPATION MATRIX PAPERS:
  Some papers extract loss factors Γ_i using participation matrix inversion rather than
  Q_TLS,0 vs p_MS fits. In these papers, Γ_surf (or Γ_surface) IS the effective surface
  loss tangent — extract it as tan_delta_effective_surface.
  The formula is: Γ_surf = tan_delta_effective_surface (dimensionless, ~1e-4 to 1e-3).
  Look for: Tables titled "Loss factors", "Loss contributions", or "Loss budget" that list
  Γ_surf, Γ_surface, or "surface loss factor" alongside participation ratios.
  Note: Γ_surf from participation matrix papers uses a COLLAPSED surface participation
  (p_surf = p_MA + p_MS + p_SA summed), not per-interface breakdown.
  Examples:
    "tan δ = 1.6e-3 from fitting QTLS,0 vs pMS"  → tan_delta_effective_surface
    "Γ_surf = 3.6×10⁻⁴ from participation matrix inversion" → tan_delta_effective_surface
    "surface loss factor Γ_surface = 3.4×10⁻⁴" → tan_delta_effective_surface
    "tan δMS = 8e-4 at the metal-substrate interface" → loss_tangent_interface (type: metal_substrate)
loss_tangent_interface_type:
  Which of the three canonical TLS-loss interfaces a loss_tangent_interface value
  belongs to: metal_substrate (MS), metal_vacuum (MA, sometimes called metal-air),
  or substrate_vacuum (SA, sometimes called substrate-air). Populate whenever
  loss_tangent_interface is populated — the number alone isn't usable without
  knowing which interface it describes. If a paper reports per-interface loss
  tangents without collapsing them (the loss_tangent_interface case above, not
  tan_delta_effective_surface), it is telling you which interface each number
  belongs to at the same time — extract both together.
MEASUREMENT CONTEXT FOR Qi AND LOSS TANGENT VALUES — DO NOT GUESS THE PAIRING:
  Qi_measurement_frequency_GHz / Qi_measurement_temperature_mK / Qi_measurement_power_dBm
  and loss_tangent_substrate_frequency_GHz / loss_tangent_substrate_temperature_mK
  record the specific frequency, temperature, and power at which the paired
  Qi_single_photon or loss_tangent_substrate value was measured. Papers frequently
  report Qi or loss tangent as a function of power or frequency (a sweep), with one
  particular point — usually the single-photon or lowest-power point — singled out
  as "the" reported value. Only populate these context fields when you can identify
  the specific condition that produced the specific number you extracted — if a
  paper shows a sweep and it's unclear which point is "the" reported value, or the
  measurement conditions for that specific point aren't stated, leave the context
  fields blank rather than pairing the value with an arbitrary or averaged
  condition. A missing context field is honest; a guessed one is not.
- MULTIPLE COOLDOWNS OF THE SAME PHYSICAL DEVICE — each cooldown is its own
  sample, not a duplicate to collapse. Superconducting qubits and resonators
  routinely give materially different values (T1, T2, frequency, δΔ, etc.)
  from one cooldown to the next, even with no fabrication change — thermal
  cycling, trapped flux, and TLS environment all shift between cooldowns.
  If a paper's data table reports a device across multiple cooldowns with
  distinct measured values (not just repeating the same numbers), give each
  cooldown its own sample_id (e.g. "B2_cooldown_2022.12", "B2_cooldown_2023.01")
  rather than picking one cooldown and silently dropping the others — a
  dropped cooldown's values are real reported data, not noise. Link cooldowns
  of the same physical device to each other via fabrication_group_id, since
  they share a physical origin even though they are not independent
  measurements of it. Do not collapse cooldowns into a single sample_id
  even when it would simplify the record — a single averaged or
  most-recent-only value hides real reported measurements from the record.
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
normal_state_resistivity_uOhm_cm:
  The normal-state (or residual) resistivity of the film, in µΩ·cm.
  Extract this DIRECTLY into the sample record as a named field — NOT into the catchall.
  Look for: "ρn = X µΩ cm", "residual resistivity X µΩ·cm", "normal state resistivity X µΩ cm",
  "ρ0 = X µΩ cm", or resistivity reported in a fabrication table alongside Tc and RRR.
  Units: always convert to µΩ·cm before reporting.
    µΩ·cm — use as-is
    mΩ·cm — multiply by 1000
    Ω·cm  — multiply by 1,000,000
  Confidence: high if stated in text or table; medium if read from a figure.
  Source: cite the table row, figure, or text location.
  Note: this is the intrinsic film resistivity, NOT junction normal-state resistance.
  Junction normal-state resistance goes in junction_resistance_normal_Ohm (see Block
  2.3 above) — do not confuse the two. They are easy to mix up by name alone, so use
  scale and context to tell them apart: film normal_state_resistivity_uOhm_cm and
  normal_state_resistance_Ohm (R vs T section below) come from a four-probe
  measurement on a Hall bar or similar patterned film structure, typically small
  (single-digit to low tens of Ohms for resistance). junction_resistance_normal_Ohm
  is the room-temperature resistance measured directly across a Josephson junction
  itself — typically kOhms, often reported as part of junction fabrication/test
  data (e.g. "target junction resistance of 5-10 kΩ", "Rn = 8.2 kΩ"), sometimes used
  via the Ambegaokar-Baratoff relation to estimate critical current. If a resistance
  value is described as being measured across a junction, or reported alongside
  junction fabrication parameters (test junctions, overlap area, oxidation
  conditions), it belongs in junction_resistance_normal_Ohm, not here.
BORROWED VALUES ACROSS SAMPLES — APPLY THE SAME CONFIDENCE RULE EVERY TIME:
  Papers commonly measure a film property (resistivity, Tc, RRR, thickness) on one
  dedicated structure — a Hall bar, a witness sample — and then state that other
  samples (resonators, qubits) were fabricated from "the same process" or "the same
  deposition." When you apply that measured value to a sample it was not directly
  measured on, this is exactly the same physical-origin-vs-shared-recipe distinction
  used for fabrication grouping elsewhere in this prompt — the value is only as
  trustworthy as the paper's evidence that the two samples actually share a physical
  origin. Apply this consistently across every sample you populate the value for,
  not just some:
    - If the paper confirms the borrowed-from structure and this sample are the same
      physical film/wafer/run (explicit shared identifier, or a single dedicated
      characterization sample that the resonator/qubit samples are explicitly stated
      to be diced from) → confidence can stay as it would be for a direct measurement.
    - If the paper only states a shared process or recipe, without confirming shared
      physical origin (e.g. several samples described as using "the same deposition
      process" but fabricated as separate runs, or a witness sample whose specific
      film isn't identified among several similar films) → downgrade confidence at
      least one level from what the source measurement itself would justify, and say
      so explicitly in the source field (e.g. "borrowed from the Hall bar
      measurement; paper does not confirm this qubit's film is the same physical
      deposition"). Do this for every sample the value is borrowed onto, not only the
      first or the most obviously uncertain one — a value copied across five samples
      should get the same caveat five times, not once.
---
RANGE-TO-POINT ESTIMATE CONSISTENCY — APPLY THE SAME CONVERSION TO EVERY SAMPLE:
  Some papers state a single fabrication target as a range rather than a per-device
  measurement — e.g. "junction area targeted at 0.04-0.18 um^2" or "resistance
  targeted at 5-10 kOhm across the batch" — without reporting a distinct value for
  each device. When you convert a stated range to a point estimate (typically the
  midpoint, unless the paper indicates otherwise), that estimate describes the whole
  batch the range applies to, not just one representative device. Apply it to every
  sample the range covers, the same way a borrowed measured value gets applied to
  every sample it covers (see BORROWED VALUES ACROSS SAMPLES above) — do not
  populate the field for only the first sample in the batch and leave the rest
  blank. This is a distinct situation from a borrowed direct measurement: there the
  question is whether two samples share a physical origin; here the question is
  simply whether a paper-wide target applies to a paper-wide set of samples, which
  it does unless the paper states a per-device exception.
---
LOSS REPORTED INSTEAD OF Qi — CONVERT WHEN THE PAPER DEFINES THE RELATIONSHIP:
---
Some papers report resonator performance as a loss (δ or tan δ) rather than as a
quality factor, and explicitly define loss as the reciprocal of Qi (a common
convention: δ = tan δ = 1/Qi). When a paper does this explicitly, convert:
Qi_single_photon = 1 / (low-power loss value), but ONLY when the low-power value
is specifically identified as the single-photon or sub-single-photon regime — look
for the paper's own definition of that regime (e.g. "low power (LP) loss" defined
as average loss below 1 photon, or an explicitly stated photon-number threshold).
Do NOT convert a high-power (HP), saturated, or unspecified-power loss value into
Qi_single_photon — that is a physically different regime and would misrepresent
what was measured. If a paper reports loss without ever defining the power regime
each value corresponds to, or without stating the δ = 1/Qi relationship explicitly,
leave Qi_single_photon blank rather than assuming which value is the single-photon
one. Record the conversion basis in the source field so it's clear a computed
value, not a directly-stated one, is being reported (e.g. "computed as 1/δ_LP;
paper defines δ_LP as average loss below 1 photon and states δ ≈ tan δ = 1/Qi").
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
  Look for:
    - "qubits are designed with p_MS of X" (design parameter statement)
    - HFSS or Maxwell simulation results for qubit geometry
    - Tables of participations listing values for multiple devices including the transmon
      (e.g. "Participation, p_i ... Transmon" columns — the p_MS or p_MS_resonator row
      for the transmon column is p_MS_pad)
    - Supplementary tables of device participations (look for "Transmon" column)
  Note: in participation tables, p_MS for the transmon column IS p_MS_pad.
  Typical values: 1e-4 to 3e-4 for optimized 2D transmon designs.
  Source: Main text, supplementary simulation section, participation tables.
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
FABRICATION PROCESS CHEMISTRY — EXTRACT THESE IF PRESENT
---
Fabrication process details can appear anywhere in the paper — Methods,
Supplementary Material, Appendix, figure captions, or inline in the results
discussion. Common section titles include "Device Fabrication", "Sample
Preparation", "Nanofabrication", and "Experimental Methods", but do not
limit your search to these. Process flow figures are also useful sources.
Fabrication process details — from deposition conditions through resist strip
chemistry, post-fabrication surface treatment, junction deposition vacuum,
and dicing — have all been shown to directly influence qubit T1 and T2.
Extract them into the named fields below when reported.
The junction/non-junction boundary matters here. Separate:
  - Base-layer processing (substrate prep → film deposition → film etch →
    resist strip → post-fab surface treatment → dicing) → named fields below
  - Junction-specific processing (pre-deposition surface treatment →
    developer → deposition → liftoff) → junction extension fields below
substrate_prep_before_deposition:
  The complete sequence of steps applied to the substrate immediately before
  loading into the film deposition chamber. Critical because it sets the
  metal-substrate interface quality — a primary TLS loss driver.
  Include: oxide removal chemistry (HF, BOE, piranha), cleaning sequence,
  time constraint on transfer to deposition chamber, getter steps.
  Note: in situ heating immediately before deposition goes in
  in_situ_substrate_bake_temperature_C (numeric) AND may also be noted
  here for context.
  Examples:
    "10:1 BOE 60s + DI rinse + N2 dry; transfer to loadlock within 15 min"
    "Piranha (2:1 H2SO4:H2O2) 20 min + HF 2 min; transfer within 15 min"
    "Piranha 20 min + 1200C anneal 1hr O2 atmosphere; 400C dehydration bake in chamber"
in_situ_substrate_bake_temperature_C:
  Temperature of in situ substrate heating inside the deposition chamber
  immediately before film deposition, in °C. This is a pre-deposition bake
  for surface desorption — distinct from deposition_temperature_C (the
  substrate temperature held during film growth).
  Look for: "in situ heating at X°C before deposition", "substrate heated
  to X°C in chamber prior to deposition", "pre-deposition anneal at X°C".
  Note: some papers use substrate-dependent temperatures for different
  substrate materials in the same study — extract per sample if values differ.
film_deposition_conditions:
  Detailed conditions for the superconducting film deposition step. Captures
  parameters not covered by the existing deposition_method and
  deposition_pressure_torr fields.
  Include: deposition rate (nm/s or nm/min), sputtering power (W), gas
  pressure, gas flow ratios, any other reported deposition parameters.
  Examples:
    "DC magnetron sputtering; 200W, 3 mTorr Ar, 0.5 nm/s"
    "RF sputtering; 150W, 5 mTorr Ar/N2 4:1, rate 0.2 nm/s"
    "Ebeam evaporation; 0.1 nm/s, base pressure 2e-8 Torr"
film_etch_chemistry:
  The etch process used to pattern the superconducting film into the device
  geometry. Include: etch type (dry/wet), gas chemistry, ICP power, RF bias
  voltage, chamber pressure, gas flow ratios, and any chamber conditioning
  run before the etch. Capture all parameters reported — etch conditions
  affect surface quality and residue chemistry.
  Note: halogen-based dry etches (BCl3, Cl2) leave residues on the substrate
  surface that affect resist strip requirements — capturing etch chemistry in
  context with what follows it is scientifically valuable.
  Examples:
    "Cl2/Ar ICP-RIE (500W ICP, 50W RF, 5.4 mTorr, 20 sccm Cl2 / 5 sccm Ar);
     1hr chamber conditioning before etch"
    "BCl3/Cl2/Ar dry etch (300W ICP, 30W RF, 8 mTorr)"
    "SF6 RIE preceded by O2 plasma 2 min"
    "Al wet etch type A"
resist_strip_chemistry:
  The solvent/chemical process used to remove photoresist after patterning
  the superconducting film. This is resist removal after a subtractive
  (dry etch) patterning step — distinct from junction_liftoff_chemistry.
  Include: solvent identity, temperature, duration, sonication steps,
  O2 plasma descum.
  Note: different strip chemistries vary substantially in their ability to
  remove halogen etch residues from the substrate surface — the choice of
  strip bath has been shown to directly determine Qi in some material systems.
  Examples:
    "AZ300T 70C bath + IPA sonication + DI rinse + O2 plasma descum"
    "MICROPOSIT 1165 + acetone + IPA sonication + O2 plasma descum"
    "Remover PG 80C 1hr + acetone sonication 2 min + IPA sonication 2 min"
    "NMP sonication + acetone + IPA + DI rinse"
post_fabrication_surface_treatment:
  The final surface treatment applied after patterning and resist strip,
  before measurement or junction fabrication. Often the step authors cite
  when explaining performance differences. Always extract if stated —
  "none" is a valid and important value.
  Include: chemical identity, concentration, temperature, duration,
  full sequence.
  Note: this step is material-specific — some superconducting films tolerate
  aggressive treatments (piranha, BOE) while others do not. Authors sometimes
  explicitly flag a substitute chemistry when their material cannot survive
  the standard treatment, and this is scientifically significant. Always
  extract the actual chemistry used, not what would be standard.
  Examples:
    "Piranha (2:1 H2SO4:H2O2) 20 min + 10:1 BOE 20 min"
    "O2 plasma descum 1 min + vapor HF 1 min"
    "H2SO4 100C 20 min + 10:1 BOE 5 min"
    "none"
dicing_protocol:
  The dicing process and associated wet chemistry. Dicing is the last wet
  environment the device sees before measurement — resist identity and strip
  chemistry here are scientifically relevant.
  Include: resist used for dicing protection, dicing parameters if stated,
  strip chemistry used after dicing.
  Examples:
    "AZ4620 protective coat; diced with diamond blade; AZ300T strip + IPA rinse"
    "Shipley 1813 coat; diced; acetone + IPA strip"
    "no dicing — individual chips cleaved"
junction_pre_deposition_surface_treatment:
  Surface preparation of the patterned chip immediately before junction metal
  deposition. Two categories — capture both if present:
  Ex-situ treatments: performed outside the deposition chamber (BOE dip,
    O2 plasma descum, solvent clean). Include chemistry, concentration,
    duration.
  In-situ treatments: performed inside the deposition chamber immediately
    before evaporation (Ar ion milling). Include bias voltage, duration,
    angle if stated.
  Note: explicit absence is scientifically notable — "no ion milling" or
  "no surface treatment" is a valid and important value, not the same as
  not reported. If the paper explicitly states no treatment was performed,
  extract that.
  Examples:
    "10:1 BOE 60s + DI rinse (ex-situ)"
    "Ar ion mill +-45 degrees, 150V bias, 20s each angle (in-situ)"
    "O2 plasma descum 30s (ex-situ) + Ar ion mill 100V 15s (in-situ)"
    "no surface treatment"
junction_developer:
  The resist developer used for EBL patterning of the junction bilayer
  resist. Two distinct approaches appear in the literature: room-temperature
  MIBK:IPA (conventional) and cold IPA:DI water (sub-zero to ~6°C), the
  latter chosen for controlled undercut in the bilayer resist stack.
  Include: developer composition, temperature, duration.
  Examples:
    "MIBK:IPA 1:3, room temperature, 50s"
    "1:3 DI:IPA at -10C, 150s + IPA rinse 15s"
    "3:1 IPA:DI at 6C, 90s"
junction_chamber_vacuum:
  The vacuum quality of the chamber used for junction metal evaporation.
  Junction deposition vacuum quality (HV vs UHV) has been shown to be a
  primary determinant of T2E — always extract if stated.
  Include: vacuum level (HV/UHV), base pressure if stated, system name
  if stated.
  Note: "follows [Reference] methods without modification" is a valid
  extractable value — cite the reference so the reader can look it up.
  Examples:
    "UHV, base 3e-10 Torr (Plassys MEB550S)"
    "HV, base <2e-8 Torr"
    "UHV (follows methods of [cited paper] without modification)"
junction_oxidation_protocol:
  The oxidation step(s) used to form the tunnel barrier. Multi-step
  oxidation sequences are common — capture the full sequence.
  Include: gas (O2, air), pressure, duration, temperature if stated.
  Examples:
    "50 mbar O2 15 min + 10 mbar O2 20 min"
    "Static O2 200 mTorr 10 min"
    "Dynamic O2 flow 1 Torr 3 min"
junction_liftoff_chemistry:
  Resist removal after junction evaporation (liftoff). Physically distinct
  from resist_strip_chemistry — liftoff dissolves resist under unwanted
  metal rather than stripping resist from an etched surface.
  Include: solvent, temperature, duration, sonication steps.
  Note: temperature and aggressiveness vary widely across labs and may
  affect junction barrier integrity — both the chemistry and conditions
  are worth capturing.
  Examples:
    "Remover PG 120C 3hr + acetone sonication + IPA"
    "NMP 80C 1hr + NMP + acetone + IPA + DI rinse"
    "Acetone room temperature 12hr + acetone sonication 1 min + IPA"
All other fabrication details should go in the fabrication_details catchall
section. This includes: resist brands and stack compositions (including any
unusual interlayer materials such as Ge layers), spin parameters, bake
temperatures, anti-charging agents, HMDS adhesion promoter steps, ion mill
bias details beyond what fits in the named field, sonication sequences not
part of the named steps above, and dicing resist identity if not captured
above.
Also capture here: measurement packaging — the enclosure used when the
device is measured at millikelvin temperatures. Include commercial package
name and model (e.g. QCage, SCALINQ SC-3D) or a brief description of
custom packaging if stated. Package type may correlate with microwave
environment and IR shielding quality.
---
FABRICATION GROUPING — DETERMINE THIS AFTER LISTING ALL SAMPLES
---
Many papers report several samples that share a common fabrication origin —
e.g. 14 qubits diced from a single wafer, or a resonator chip and a qubit
chip from the same deposition run. Treated as fully independent, these look
like many separate tests of a hypothesis when they are much closer to one
test of a fabrication process, replicated N times. This matters enormously
for downstream statistical analysis of the corpus.
This is a judgment call, not a lookup — make it only after you have already
listed every sample_id for this paper. The evidence for a shared origin
usually appears in two different places that do not co-occur, so check both:
  - wherever individual sample/device IDs are introduced (a table, a device
    list, "devices D1 through D14")
  - the fabrication/methods section, wherever it describes the process
    (do not assume it is under a section literally titled "Fabrication" —
    it may be Methods, Supplementary Material, or inline in Results)
Sometimes the link is stated explicitly: "samples D1-D14 were fabricated
from wafer W1." More often it is implicit: "we fabricated 14 nominally
identical devices using the process described above, then characterized
each individually" — no batch identifier is used, but the shared-origin
claim is unambiguous. Both cases are worth capturing, with different
confidence.
For each distinct fabrication event you can identify, create one entry in
fabrication_groups (top-level, alongside samples — NOT nested inside any
sample) listing every member sample_id, and set each member sample's
fabrication_group_id field to that group's group_id. A paper can have more
than one group (e.g. a two-wafer process comparison has two groups).
CONFIDENCE AND BASIS — use this rubric, not the general confidence rule
used elsewhere in this prompt. This is a judgment about the strength of
evidence that samples share an origin, not about whether a reported number
was read correctly:
  basis: explicit, confidence: high —
    the paper directly ties an identifier to the samples ("D1-D14 from
    wafer W1"), or a table column shares a batch/wafer/chip ID across rows.
  basis: implicit_inferred, confidence: medium —
    the paper uses the standard "we fabricated N devices via [process],
    then characterized each" pattern. No explicit batch language, but the
    pattern is unambiguous.
  basis: implicit_inferred, confidence: low —
    plausible but genuinely underdetermined — e.g. multiple sample sets
    described with similar but not identical process language, and it is
    unclear whether that reflects a real batch split or incidental
    per-device notes.
DO NOT force a grouping. If the paper says nothing about shared fabrication
origin for a given sample, simply do not include that sample_id in any
fabrication_groups entry and do not add a fabrication_group_id field to it
— leaving it out means "no evidence of a shared origin," which is the
correct default. Do not invent a group to avoid leaving this blank, and do
not assume co-located samples in a table share an origin without textual
evidence — proximity in a table is not evidence of shared fabrication.
SAME PHYSICAL ORIGIN, NOT MERELY SAME RECIPE — a group means samples that
share the same physical fabrication event (one wafer, one deposition run,
one batch processed together) — NOT samples that merely used the same
process parameters on separate occasions. These are different claims.
"Same recipe" only controls the variables the authors chose to report
(power, pressure, rate, target material). It says nothing about whatever
varies run-to-run and goes unreported — target erosion state, chamber
conditioning history, operator variation, drift over time. A paper stating
two films were deposited via the same recipe, on different days or in
separate runs, is NOT sufficient evidence they share a fabrication group —
each run gets its own group_id.
  Example: "Films F15 and F16 were both deposited using the room-temperature
  process described in Section S1" describes ONE RECIPE used for TWO
  SEPARATE DEPOSITIONS. If the paper also states which specific samples came
  from F15 versus F16, split into two groups (one per film). If the paper
  does NOT disclose that per-sample assignment (e.g. "11 qubits across films
  F15 and F16," with no statement of which qubit is which), you cannot
  manufacture a split the source material does not support — it is fine to
  keep them as one group, but set individual_assignment_disclosed: false so
  a reviewer knows this group's membership reflects a set-level claim, not a
  verified physical-run assignment.
  Contrast with: "devices D1-D14 were fabricated from wafer W1" — this
  describes ONE PHYSICAL WAFER shared by all 14 devices, with explicit
  per-device assignment. This is one group with individual_assignment_
  disclosed: true.
  When in doubt whether a shared description refers to one physical run or
  multiple, and the paper DOES give you enough to assign samples
  individually, prefer treating it as multiple (separate groups) — an
  unnecessary split only slightly understates a real correlation, but an
  incorrect merge erases real degrees of freedom from downstream analysis
  and is the more costly error.
EVIDENCE MUST NAME EXACT SAMPLE_IDs, NOT CATEGORIES — when evidence
discusses which samples belong to a group, refer to them by their literal
sample_id string ("qubit_1 through qubit_45"), never by an unresolved
category label ("the resonator samples", "the qubit devices"). Category
language hides exactly the cases a human reviewer most needs to check, and
makes it impossible to verify your evidence against your own
member_sample_ids list.
EXCLUDED CANDIDATES — REQUIRED, NOT OPTIONAL — this is the main defense
against silently dropping a sample. While writing a group's evidence, you
will sometimes notice a sample that plausibly shares this fabrication
origin but that you decide not to include as a member (uncertain per-device
assignment, weaker textual support than the included members, etc). Do NOT
just omit it silently. Add it to that group's excluded_candidates with a
one-sentence reason. A human reviewer needs to see what you considered and
rejected, not only what you accepted — an omitted candidate is invisible to
review, an excluded one is not. Before finalizing your output, check: does
any group's evidence text reference a sample_id that is not in that group's
member_sample_ids AND not in its excluded_candidates? If so, resolve it —
that sample_id belongs in exactly one of those two lists, never in neither.
A SAMPLE CANNOT BE IN BOTH LISTS AT ONCE — a member_sample_ids entry and an
excluded_candidates entry for the same sample_id in the same group directly
contradict each other (one says "this sample belongs here," the other says
"this sample was considered and rejected") and corrupt any downstream query
against either list. If your own reasoning while drafting excluded_candidates
concludes that a sample should actually be included after all, that is a
decision to make BEFORE finalizing output, not a nuance to preserve in the
excluded_candidates text: move the sample_id into member_sample_ids and
delete its excluded_candidates entry entirely. Do not write reasoning that
argues against inclusion and then concludes "included/retained anyway" —
if you find yourself writing that, the sample_id must actually move.
Single-sample papers do not need a fabrication_groups entry at all.
---
GATE FIDELITY — EXTRACT THESE AS NAMED FIELDS
---
single_qubit_gate_fidelity_pct:
  Single-qubit gate fidelity as a percentage (0-100).
  Extract DIRECTLY into the sample record as a named field — NOT into the catchall.
  Look for: "single-qubit gate fidelity X%", "average Clifford gate fidelity X%",
  "1Q fidelity X%", "single-qubit gate error X" (convert: fidelity = (1 - error) × 100).
  Randomized benchmarking (RB) is the standard measurement method — extract the result.
  Units: always report as percentage. Convert gate error to fidelity if needed:
    gate error 6.4×10⁻⁵  → fidelity = (1 - 6.4e-5) × 100 = 99.9936%
    gate error 3.9×10⁻³  → fidelity = (1 - 3.9e-3) × 100 = 99.61%
  Confidence: high if from RB table; medium if from prose or figure.
  Source: cite the table, figure, or text location.
  Note: this is single-qubit gate fidelity ONLY. Two-qubit gate fidelity goes in
  two_qubit_gate_fidelity_pct. Readout fidelity goes in the catchall.
two_qubit_gate_fidelity_pct:
  Two-qubit gate fidelity as a percentage (0-100).
  Extract DIRECTLY into the sample record as a named field — NOT into the catchall.
  Look for: "two-qubit gate fidelity X%", "CZ fidelity X%", "CNOT fidelity X%",
  "ECR gate fidelity X%", "2Q gate error X" (convert: fidelity = (1 - error) × 100),
  "average Clifford fidelity" for two-qubit RB.
  Units: always report as percentage. Convert gate error to fidelity if needed.
  Confidence: high if from RB table; medium if from prose or figure.
  Source: cite the table, figure, or text location.
  Note: do NOT put readout fidelity here. Readout fidelity goes in the catchall.
IMPORTANT DISTINCTIONS:
  - Gate fidelity (single or two-qubit) → named schema fields above
  - Readout/state assignment fidelity → catchall (no named schema field)
  - Bell state fidelity → catchall
  - Process fidelity → catchall
--
T2 COHERENCE TIMES — EXTRACT BOTH VARIANTS AS NAMED FIELDS
---
Many papers measure both T2 echo and T2 Ramsey on the same qubit.
Extract BOTH as named fields — do NOT put either in the catchall.
T2_echo_us:
  T2 measured with a Hahn echo sequence (also called T2E, T2^E, T2,echo).
  Echo refocuses low-frequency dephasing noise — always >= T2_Ramsey.
  Units: µs. Convert from ms if needed and note the conversion.
  Source: qubit characterization table, or text stating "T2 echo = X µs".
T2_ramsey_us:
  T2 measured with a Ramsey sequence (also called T2*, T2^R, T2,Ramsey, T2R).
  Captures total dephasing including low-frequency noise that echo refocuses.
  Always <= T2_echo for the same qubit.
  Extract DIRECTLY into the sample record as a named field — NOT into the catchall.
  Look for: "T2* = X µs", "T2^R = X µs", "T2R = X µs", "Ramsey coherence time X µs",
  "T2 Ramsey = X µs", or Ramsey values in a qubit characterization table.
  Units: µs. Convert from ms if needed.
  Confidence: high if from table; medium if from prose or figure.
  Source: cite the table row or text location.
T2_unspecified_us:
  T2 reported simply as "T2 = X µs" with no sequence type stated anywhere in
  the paper — not in the value itself, not in the methods, not implied by
  reporting both an echo and a Ramsey number elsewhere (which would confirm
  which is which). Use this field rather than guessing which sequence was
  used — a base-rate assumption about what's typical in the field is not
  the same kind of evidence this prompt otherwise requires, and silently
  filing an unconfirmed value under T2_echo_us would make it
  indistinguishable from a value the paper actually confirmed as echo.
  Units: µs. Convert from ms if needed.
DISAMBIGUATION:
  T2_echo_us   → Hahn echo, spin echo, T2E, T2^E — always use this field
  T2_ramsey_us → Ramsey, T2*, T2^R, T2R, T2,Ramsey — always use this field
  If a paper reports only "T2" without specifying the sequence type:
    - First check whether the methods state a sequence used for T2
      measurements generally (even a single global statement, not repeated
      per value, is legitimate grounds to use T2_echo_us or T2_ramsey_us —
      cite that methods statement as the source).
    - If the paper never states the sequence anywhere, use T2_unspecified_us
      with medium confidence — do NOT default to T2_echo_us based on what is
      typical for the field in general. That is a guess about convention,
      not information from this paper, and belongs in a field that makes
      the guess visible rather than hidden inside a "confirmed echo" bucket.
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
- Loss budget percentages are high-value correlations. If authors calculate
    what fraction of T1 or relaxation rate comes from each loss channel
    (e.g. "Al junction leads contribute 27% of TLS loss", "pad TLS accounts
    for 73% of relaxation rate"), always capture these as correlation items.
    measurement_a: the loss channel or component (e.g. "Al junction leads TLS loss")
    measurement_b: the total qubit relaxation rate or T1
    nature: the calculated percentage contribution
    description: include the specific geometry assumed (e.g. "for 70 µm gap Ta-on-Si qubit")
FABRICATION DETAILS:
  - Capture any fabrication step or process detail not covered by the named fabrication
    fields above. This is the destination for the long tail of process information.
  - Include: resist brands and stack compositions (including unusual interlayer materials
    such as Ge hard mask layers), spin parameters, bake temperatures, anti-charging
    agents, HMDS adhesion promoter steps, sonication sequences not captured in named
    fields, ion mill bias details beyond the named field, dicing resist identity.
  - Also capture: measurement packaging — the enclosure used at millikelvin temperatures.
    Include commercial package name and model (e.g. QCage, SCALINQ SC-3D) or description
    of custom packaging. Package type may correlate with microwave environment quality.
  - Each entry needs a description and source. No suspected_relevance required —
    relevance of fabrication details will be assessed during corpus mining.
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
  - Use for cross-sample observations and processing context not captured elsewhere.
  - Fabrication details go in the fabrication_details catchall section, not here.
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
    Build the Pass 3 prompt for one chunk of extracted sample records
    (see call_profile_generation, which chunks large sample lists before
    calling this — chunk_size samples per call, not the full paper at once).
    sample_record should be the full sample dict (or list of dicts) from the
    Pass 2 extraction, including all structured fields and the complete
    catchall.
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
