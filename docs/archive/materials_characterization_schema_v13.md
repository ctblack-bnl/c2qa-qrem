# Materials Characterization Data Schema
### Version 0.13 — T2_ramsey_us promoted to named column; Explorer enhancements (May 2026)
**Date:** May 20, 2026
**Status:** Active — ingester operational, Explorer live at https://c2qa-materials-explorer.onrender.com
**Scope:** Superconducting qubit and resonator systems (neutral atom schema to follow)

---

## Purpose and Philosophy

This schema defines a standard format for reporting materials characterization data across the five DOE quantum centers. Two goals are held together:

**Goal 1 — Interoperability.** Common format enables aggregation and comparison across centers.

**Goal 2 — Computational utility.** Where the connection between a material property and device performance is known, the schema captures it explicitly — so a measurement doesn't just tell you what a material is, it tells you what that material enables computationally.

### Records as Portable Units of Knowledge (PUKs)

Each schema record is self-contained: provenance, measured properties with confidence levels, derived quantities, catchall observations, device performance implications, and a semantic similarity profile. The six-block structure captures everything about a sample in one place.

The QREM pipeline can project any record into a hardware profile on demand. The similarity profile enables semantic search across the corpus. The corpus mining pipeline extracts materials-to-device connection hypotheses from the full record corpus. All are derived from the record — the record is always the source of truth.

### The Catch-All

The catch-all is mandatory and is a first-class scientific output. It captures knowledge not yet formalized into schema fields and drives schema evolution. The 41 author-stated correlations in the current corpus are the primary evidence base for the QREM mapping layer, processed by the corpus mining pipeline.

**Catch-all types:**
- `additional_measurement` — any measurement without a named schema field. Includes both routine measurements and observations the community keeps making repeatedly (the latter are schema promotion candidates identified by frequency analysis).
- `anomalous_observation` — results the authors flag as unexpected.
- `correlation` — author-stated connections between two measurements. Never inferred from data.

Note: the former `schema_candidate` type has been merged into `additional_measurement`. Schema promotion decisions are now driven by measurement frequency across the corpus, not per-paper AI judgment.

---

## Implementation Status (v0.8)

### How Records Are Created

**Direct submission** — a scientist fills in schema fields manually. Highest-quality records.

**Publications ingester** — AI-assisted tool reads PDFs and automatically extracts schema-compatible records via three passes:
- Pass 1 — Relevance check
- Pass 2 — Full structured extraction → PUK
- Pass 3 — Similarity profile generation → appended to PUK

Ingested records carry per-field confidence levels (`high`/`medium`/`low`) and source references, and start with `human_reviewed: false`, `human_approved: false`.

### Current Database State

See Explorer header for live counts — corpus stats are not maintained in this document.

### Corpus Mining Pipeline

The corpus mining pipeline (Phase A → B → C) operates over all ingested records to extract, reason about, and formalize materials-to-device connection hypotheses. Results are reviewed by human scientists and approved findings are written to `findings.jsonl`.

**Current mining results:** See `findings.jsonl` for approved findings. 1 positive finding to date: Tc_K vs deposition_temperature in Ta-Hf (83:17), confidence 0.72. Remaining findings inconclusive — expected at current corpus size.

Mining runs as Stage 4 of the ingestion pipeline UI (`ingest_pipeline.html`).

### Schema Evolution — Frequency-Driven Promotion

Fields are promoted from `additional_measurements` catchall to named schema columns based on measurement frequency across the corpus. A field appearing in >5% of materials samples is a promotion candidate. Promotion requires:
1. Named column added to `build_sqlite.py`, reading value from `catchall_items.value`
2. Human approval via Stage 4 schema evolution UI (auto-patches `pipeline_mining.py` FIELD_MAP and NAMED_COLUMNS)

No prompt changes required — Claude already extracts these values during Pass 2; they simply need a named column to become queryable.

**Fields promoted (May 9, 2026):** ✅ All three fields below are now operational named columns.

| Field | Frequency | Units | Notes |
|---|---|---|---|
| `kinetic_inductance_sheet_pH_sq` | 49× | pH/sq | Sheet (per-square) only — geometry-independent. Normalize all values to pH/sq. |
| `mean_free_path_nm` | 9× | nm | Direct measurement; 8 of 9 entries clean numeric |
| `vortex_activation_temperature_K` | 11× | K | Intrinsic material property |

**Domain rule — geometry independence:** Only intrinsic (geometry-independent) properties are promotable. Sheet kinetic inductance (Lk,sq) yes; total kinetic inductance (Lk) no. Critical current density (Jc-material, Jc-junction) yes; critical current (Ic) no. See Ic/Jc note below.

### Ic/Jc Disambiguation — Planned

Two physically distinct quantities are both called Jc and currently conflated in the catchall:

- **Material Jc** — bulk film critical current density. Intrinsic material property. Derivable from Ic_film / (film_width × film_thickness). Units: A/m². Relevant to vortex loss modeling.
- **Junction Jc** — Josephson junction critical current density. Device property. Derivable from Ic_junction / junction_area_um2. Units: µA/µm². Relevant to EJ calculation and transmon design.

Future schema additions: `derived_material_Jc_A_m2` and `derived_junction_Jc_uA_um2` (new `derive.py` functions). New Block 2 fields needed: `film_width_um` for material Jc derivation (already added in v0.7).

### QREM Hardware Profile Generation

Records with device performance data (T1, T2, gate fidelity) can be projected into QREM qubit hardware profiles via the Explorer UI "Generate Qubit Profile" button. Measured fields labeled `[MEASURED]`; unmeasured fields use defaults from `transmon_baseline_2026.yaml`, labeled `[ASSUMED]`.

### Derived Normalization Fields (Explorer Display)

`build_sqlite.py` computes three normalization columns at build time for Explorer filtering and grouping. These are display/navigation aids — not schema fields in the PUK sense.

| Column | Source field | Canonical values | Notes |
|---|---|---|---|
| `derived_material` | `film_material` | Ta, Nb, Al, Re, TiN, NbN, NbTiN, TaN, NbSe2, PtSi, Ta-Hf, Mo3Al2C, other, unknown | Drives Phase A per-material stratification. Strips parentheticals before matching KNOWN_MATERIALS whitelist. |
| `derived_substrate` | `substrate_material` | Silicon, Sapphire, Silicon Carbide, Diamond, Other | Explorer sidebar filter. Collapses vendor/grade/orientation variants. |
| `derived_deposition_method` | `deposition_method` | DC Sputtering, RF Sputtering, Ebeam Evaporation, Thermal Evaporation, MBE, ALD, CVD, PLD, Other | Explorer group-by. Handles capitalization variants; filters patterning methods (EBL) to Other. |
| `derived_Qi` | `Qi_single_photon`, `Qi_internal_quality_factor` | Single-photon Qi preferred (qubit operating regime, TLS unsaturated); falls back to internal Qi. Explorer default y-axis. |
| `derived_T2_us` | `T2_echo_us`, `T2_ramsey_us` | Echo preferred (refocuses low-frequency noise); falls back to Ramsey. |
| `derived_tan_delta` | `tan_delta_effective_surface`, `loss_tangent_interface`, `loss_tangent_substrate` | Best available surface loss tangent. tan_delta_effective_surface preferred (fitted from Q_TLS,0 vs p_MS); falls back to per-interface, then bulk substrate. Explorer y-axis for loss tangent plots. |
| `derived_resistivity_uOhm_cm` | geometry derivation → `normal_state_resistivity_uOhm_cm` | Geometry derivation (R vs T fields) attempted first; falls back to directly reported resistivity. Currently fires only for NbSe2/NbN (geometry path). Bahrami/Yang values in catchall pending prompt fix. |

**Explorer dropdown rationalization (May 19):** Raw Qi variants (`Qi_internal`, `Qi_single_photon`) and raw loss tangent variants (`loss_tangent_substrate`, `loss_tangent_interface`) were removed from the Explorer measurement dropdown — they are superseded by `derived_Qi` and `derived_tan_delta` respectively. Raw values remain accessible in the detail drawer when clicking any data point. `Q_TLS_0` added as a separate plottable field ("Q_TLS,0 (unsaturated TLS Q)") — it is physically distinct from Qi and should not be folded into `derived_Qi`.

### Manual Exclusions

Some records pass relevance classification but are subsequently found to be inappropriate (theory proposals, non-superconducting systems, C2QA acknowledgment false positives). These are excluded post-hoc via `data/ingested/exclusions.json` without modifying the JSONL.

`build_sqlite.py` reads `exclusions.json` at build time and skips matching records. Match priority: DOI → arXiv ID → filename. Each entry requires a human-readable `reason`.

**Current exclusions (May 19):** Hays 2026 (theory proposal, unbuilt "harmonium" qubit — T1=3×10⁹µs is a noise model estimate); Marcenac 2026 (NV center / FPGA control, not superconducting); WangX 2026 (ZnO semiconductor donor, not superconducting). All had C2QA acknowledgments causing false high-relevance.

**Rule:** A C2QA acknowledgment alone is not sufficient for relevance. The paper must report superconducting materials characterization data. Papers where only DFT calculations or instrumentation work was C2QA-funded should be classified low.

**Planned:** Exclusions management UI in the pipeline interface.


### Material Name Standardization

Standard chemical abbreviations enforced at extraction time:

| Paper description | Extracted as |
|---|---|
| tantalum, Ta film | Ta |
| niobium, Nb film | Nb |
| niobium titanium nitride | NbTiN |
| tantalum nitride | TaN |
| rhenium, Re film | Re |
| Ta-Hf alloy (83% Ta, 17% Hf) | Ta-Hf (83:17) |
| molybdenum aluminum carbide | Mo3Al2C |
| niobium diselenide | NbSe2 |
| platinum silicide | PtSi |

Crystal phase always goes in `film_crystal_phase`, never in `film_material`.

**Critical rule (enforced in Pass 2 prompt since May 9):** `film_material` is the superconducting film identity only. Junction materials (e.g. Al/AlOx/Al) go in `junction_material`. Parenthetical qualifiers like "(with Al/AlOx junction)" must never appear in `film_material`. Existing records with parenthetical `film_material` values are handled by the `normalize_film_material()` function in `build_sqlite.py` which strips the parenthetical before KNOWN_MATERIALS lookup.

### Display Names

Each sample: `{first_author}_{year}_{sample_id}` (e.g. `Bahrami_2026_D1`).

---

## Schema Structure Overview

```
[1] RECORD METADATA         — who, where, when, what sample
[2] SAMPLE DESCRIPTION      — what material, how made, R vs T geometry
[3] STRUCTURED MEASUREMENTS — defined fields with known device mappings
[4] DEVICE PERFORMANCE IMPLICATIONS — what measurements mean computationally
[5] CATCH-ALL               — everything else, free-form but guided
[6] SIMILARITY PROFILE      — semantic tags for corpus search (AI-generated, Pass 3)
```

---

## Block 1 — Record Metadata

| Field | Type | Required | Description |
|---|---|---|---|
| `record_id` | string | Yes | Format: `{CENTER}-{YYYYMMDD}-{SEQ}` |
| `center` | enum | Yes | One of: `C2QA`, `SQMS`, `Q-NEXT`, `QSA`, `QED-C` |
| `submitting_lab` | string | Yes | Institution and lab name |
| `submitter` | string | Yes | Name of responsible scientist |
| `date_measured` | date | Yes | ISO format: YYYY-MM-DD |
| `date_submitted` | date | Yes | ISO format: YYYY-MM-DD |
| `schema_version` | string | Yes | e.g. `0.8` |
| `sample_id` | string | Yes | Center-internal sample identifier |
| `extraction_method` | enum | No | One of: `direct_submission`, `literature_ingestion` |
| `source_doi` | string | No | DOI of source paper |
| `source_reference` | string | No | Specific location e.g. "Table I row 3" |
| `source_files` | list | No | e.g. `[main, SI]` — for records extracted from multiple files |
| `human_reviewed` | boolean | No | Whether a scientist has reviewed this record |
| `human_approved` | boolean | No | Whether a scientist has approved this record for use |
| `exchange_sample` | boolean | No | True if shared sample from another center |
| `origin_center` | enum | No | If exchange sample, which center provided it |
| `related_records` | list | No | Record IDs of related measurements on same sample |
| `notes` | string | No | Administrative notes |

---

## Block 2 — Sample Description

### 2.1 Substrate

| Field | Type | Required | Description |
|---|---|---|---|
| `substrate_material` | enum | Yes | One of: `silicon`, `sapphire`, `silicon_carbide`, `diamond`, `other` |
| `substrate_material_other` | string | If other | Specify material |
| `substrate_orientation` | string | No | e.g. `(100)`, `(0001)`, `c-axis` |
| `substrate_resistivity` | float | No | Ohm·cm |
| `substrate_supplier` | string | No | Commercial supplier or growth lab |
| `substrate_thickness_um` | float | No | Substrate thickness in microns |
| `substrate_surface_treatment` | string | No | e.g. `epi-polish`, `CMP`, `HF etch`, `none` |
| `substrate_cleaning_protocol` | string | No | Cleaning steps applied before deposition |

### 2.2 Superconducting Film

| Field | Type | Required | Description |
|---|---|---|---|
| `film_material` | enum | Yes | Standard abbreviation: `Nb`, `NbTiN`, `NbN`, `Al`, `TiN`, `Ta`, `Re`, `other`. Never spell out. Superconducting film identity only — never include junction or encapsulation materials here. |
| `film_material_other` | string | If other | Chemical formula e.g. `Ta-Hf (83:17)`, `TaN`, `NbSe2`, `PtSi`, `Mo3Al2C` |
| `film_crystal_phase` | string | No | e.g. `alpha-Ta (bcc)`, `beta-Ta (tetragonal)`. Always here, never in `film_material`. |
| `film_thickness_nm` | float | Yes | Film thickness in nanometers |
| `film_width_um` | float | No | Width of film structure in microns. Required for material Jc derivation. |
| `deposition_method` | enum | Yes | One of: `sputtering`, `evaporation`, `MBE`, `ALD`, `CVD`, `other` |
| `deposition_method_other` | string | If other | e.g. `UHV dc magnetron sputtering` |
| `deposition_temperature_C` | float | No | Substrate temperature during deposition |
| `deposition_pressure_torr` | float | No | Chamber pressure during deposition |
| `deposition_gas` | string | No | e.g. `Ar`, `Ar/N2`, `N2` |
| `annealing_temperature_C` | float | No | Post-deposition anneal temperature in Celsius |
| `annealing_duration_s` | float | No | Post-deposition anneal duration in seconds |
| `annealing_protocol` | string | No | Full anneal conditions if not captured above |
| `patterning_method` | string | No | e.g. `optical lithography`, `EBL`, `none` |
| `etch_method` | string | No | e.g. `RIE`, `wet etch`, `none` |

### 2.3 Josephson Junction (if applicable)

| Field | Type | Required | Description |
|---|---|---|---|
| `junction_present` | boolean | Yes | Whether record includes a Josephson junction |
| `junction_material` | string | If yes | e.g. `Al/AlOx/Al`, `Nb/AlOx/Nb`. Junction material goes here, never in `film_material`. |
| `junction_fabrication_method` | string | If yes | e.g. `double-angle evaporation`, `overlap junction` |
| `junction_area_um2` | float | If yes | Junction area in square microns. Required for junction Jc derivation. |
| `junction_oxidation_conditions` | string | If yes | Pressure, time, temperature of oxidation step |
| `junction_resistance_normal_Ohm` | float | If yes | Normal-state resistance in Ohms |
| `junction_vacuum_condition` | string | No | e.g. `HV`, `UHV` — deposition vacuum quality |

### 2.4 R vs T Measurement Geometry

These fields enable derivation of intrinsic material properties (sheet resistance, RRR, resistivity) from resistance measurements on patterned structures.

| Field | Type | Required | Description |
|---|---|---|---|
| `normal_state_resistance_Ohm` | float | No | Resistance just above Tc. With geometry, enables sheet resistance derivation. |
| `room_temperature_resistance_Ohm` | float | No | Resistance at ~300K. With normal state R, enables RRR derivation. |
| `measured_structure_width_um` | float | No | Width of patterned structure in microns |
| `measured_structure_length_um` | float | No | Length of patterned structure in microns |

Sheet resistance Rs = Rn × (width/length) [Ω/□]; RRR = R(300K)/R(Tc+). The `derive.py` module computes these automatically when geometry is available.

---

## Block 3 — Structured Measurements

Defined measurement fields with known or approximate connections to device performance.

**Mapping status:** `well_known` — established in literature | `approximate` — directionally understood | `open_research` — suspected but not established

### 3.1 Superconducting Properties

| Field | Type | Units | Mapping | Downstream Device Parameter |
|---|---|---|---|---|
| `Tc_K` | float | K | `well_known` | Operating temperature margin; quasiparticle density |
| `Tc_uniformity_pct` | float | % std dev | `approximate` | Fabrication yield; qubit frequency uniformity |
| `RRR` | float | dimensionless | `well_known` | Film purity; quasiparticle loss. Dimensionless — if units are reported it is a different quantity. |
| `sheet_resistance_Ohm_sq` | float | Ω/□ | `well_known` | Kinetic inductance; qubit frequency |
| `kinetic_inductance_sheet_pH_sq` | float | pH/sq | `well_known` | Resonator frequency; superinductor performance. Sheet (per-square) value only — geometry-independent. ✅ Promoted May 2026. |
| `mean_free_path_nm` | float | nm | `well_known` | Clean vs dirty superconducting limit; vortex behavior. l > ξ → clean limit, vortex motion dominant. ✅ Promoted May 2026. |
| `vortex_activation_temperature_K` | float | K | `approximate` | Vortex motion loss channel; microwave loss at operating temperature. Corpus finding: dirty-limit Ta films show ~10× higher Tact than clean-limit films. ✅ Promoted May 2026. |
| `London_penetration_depth_nm` | float | nm | `approximate` | Surface loss contribution |
| `upper_critical_field_T` | float | T | `well_known` | Operating field margin; used to derive coherence length |

### 3.2 Dielectric and Surface Loss

| Field | Type | Units | Mapping | Downstream Device Parameter |
|---|---|---|---|---|
| `loss_tangent_substrate` | float | dimensionless | `well_known` | T1 (dielectric loss) |
| `loss_tangent_substrate_frequency_GHz` | float | GHz | — | Measurement frequency (required for context) |
| `loss_tangent_substrate_temperature_mK` | float | mK | — | Measurement temperature (required for context) |
| `loss_tangent_interface` | float | dimensionless | `approximate` | T1 (interface loss) |
| `loss_tangent_interface_type` | enum | — | — | One of: `metal_substrate`, `metal_vacuum`, `substrate_vacuum` |
| `TLS_density_per_GHz_per_um2` | float | GHz⁻¹·μm⁻² | `well_known` | T2 dephasing; resonator quality factor |
| `TLS_coupling_strength_MHz` | float | MHz | `approximate` | Individual TLS-qubit interaction strength |
| `TLS_measurement_protocol` | string | — | — | Reference to protocol used |
| `surface_oxide_thickness_nm` | float | nm | `approximate` | TLS density; interface loss |
| `surface_oxide_composition` | string | — | `open_research` | TLS species identification |
| `surface_participation_ratio` | float | dimensionless | `approximate` | Fraction of electric field energy in lossy surface region |

### 3.3 Microwave Performance

| Field | Type | Units | Mapping | Downstream Device Parameter |
|---|---|---|---|---|
| `Qi_internal_quality_factor` | float | dimensionless | `well_known` | Resonator photon loss. Qi/ω gives resonator photon lifetime (T1_resonator) — a material proxy, not qubit T1. Qi feeds the loss tangent extraction step in the mapping layer. Do not confuse with Qc (coupling quality factor). |
| `Qi_measurement_power_dBm` | float | dBm | — | Single-photon regime should be noted |
| `Qi_measurement_frequency_GHz` | float | GHz | — | Required for context |
| `Qi_measurement_temperature_mK` | float | mK | — | Required for context |
| `Qi_single_photon` | float | dimensionless | `well_known` | Most relevant for qubit operating conditions |
| `Qc_coupling_quality_factor` | float | dimensionless | `well_known` | Resonator-qubit coupling design |
| `microwave_loss_mechanism` | string | — | `approximate` | Dominant loss: `TLS`, `quasiparticle`, `vortex_motion`, `radiation` |
| `Q_TLS_0` | float | dimensionless | `well_known` | Unsaturated TLS quality factor — extracted from power+temperature sweeps of Q_int. Preferred over raw Qi for loss model input: Q_TLS,0 is the single-photon regime value, free of TLS saturation. Often reported as "Q_TLS,0", "inverse linear absorption from TLSs". |
| `resonator_type` | enum | — | — | One of: `CPW`, `lumped_element`, `other`. Required for p_MS_resonator lookup. |
| `resonator_gap_width_um` | float | µm | — | CPW gap width s, or LE capacitor gap. Primary determinant of p_MS_resonator. Varies 2-16 µm in typical CPW resonators; p_MS_resonator varies 6x over this range. |
| `p_MS_resonator` | float | dimensionless | `well_known` | Surface participation ratio of the metal-substrate interface for the resonator. Required to invert Q_TLS,0 → tan_delta: tan_delta = 1/(Q_TLS,0 × p_MS_resonator). From FEM simulation or geometry lookup. Joshi 2026 Table S4: s=2µm → 2.2e-3; s=6µm → 8.6e-4; s=16µm → 3.7e-4. |
| `p_MS_pad` | float | dimensionless | `well_known` | Surface participation ratio of the qubit capacitor pads. Required to convert tan_delta → T1_pad_TLS: T1_pad_TLS = 1/(p_MS_pad × tan_delta × 2πf). Much smaller than p_MS_resonator by design. Joshi 2026: 1.3e-4. Bland 2025: 1.0-2.6e-4 depending on gap size and trench depth. From HFSS simulation. |


### 3.4 Qubit Performance (device-level measurement)

| Field | Type | Units | Mapping | Downstream Device Parameter |
|---|---|---|---|---|
| `T1_us` | float | µs | `well_known` | Qubit state energy relaxation time. Gate fidelity; code distance. Note: T1 may be reported in ms — always convert to µs. Only populate from direct qubit measurements — not from Qi/ω of a bare resonator, which is a physically distinct quantity (resonator photon lifetime). See T1_measurement_context. |
| `T1_measurement_context` | enum | — | — | One of: `qubit_state` (direct qubit T1 measurement), `resonator_photon` (T1 = Qi/ω, photon lifetime in bare resonator — material proxy, not qubit coherence). Always populate when T1_us is present. |
| `T1_std_us` | float | µs | `well_known` | Fabrication variability; yield modeling |
| `T2_echo_us` | float | µs | `well_known` | Dephasing; gate fidelity for longer sequences |
| `T2_ramsey_us` | float | µs | `well_known` | Low-frequency noise environment |
| `T1_measurement_protocol` | string | — | — | Reference to protocol used |
| `qubit_frequency_GHz` | float | GHz | `well_known` | Operating point; collision avoidance |
| `qubit_frequency_std_GHz` | float | GHz | `approximate` | Frequency crowding in scaled systems |
| `anharmonicity_MHz` | float | MHz | `well_known` | Gate speed limit; leakage rate |
| `single_qubit_gate_fidelity_pct` | float | % | `well_known` | Error correction overhead (local gates) |
| `single_qubit_gate_time_ns` | float | ns | `well_known` | Circuit runtime; coherence budget |
| `two_qubit_gate_fidelity_pct` | float | % | `well_known` | Error correction overhead (dominant cost). 0.4% improvement (99.5%→99.9%) reduces module count ~8× for representative circuits. |
| `two_qubit_gate_time_ns` | float | ns | `well_known` | Circuit runtime; coherence budget |
| `readout_fidelity_pct` | float | % | `well_known` | Syndrome measurement accuracy in QEC |
| `readout_time_ns` | float | ns | `well_known` | QEC cycle time |

### 3.5 Noise Characterization

| Field | Type | Units | Mapping | Downstream Device Parameter |
|---|---|---|---|---|
| `flux_noise_amplitude_uPhi0_per_sqrtHz` | float | μΦ₀/√Hz | `well_known` | T2 dephasing in flux-tunable qubits |
| `charge_noise_amplitude_e_per_sqrtHz` | float | e/√Hz | `approximate` | Charge noise sensitivity |
| `noise_exponent_1f` | float | dimensionless | `approximate` | 1/f noise character; long-sequence fidelity |
| `quasiparticle_density_per_um3` | float | μm⁻³ | `well_known` | T1 quasiparticle loss channel |
| `quasiparticle_parity_switching_rate_kHz` | float | kHz | `well_known` | Parity error rate in error correction |

### 3.6 Inter-Module / Interconnect Properties

| Field | Type | Units | Mapping | Downstream Device Parameter |
|---|---|---|---|---|
| `intermodule_link_type` | enum | — | — | One of: `microwave_photonic`, `optical_photonic`, `direct_wire`, `other` |
| `intermodule_link_fidelity_pct` | float | % | `well_known` | Raw Bell pair fidelity. Below ~99% requires purification. |
| `intermodule_entanglement_rate_Hz` | float | Hz | `well_known` | Raw Bell pairs per second |
| `intermodule_link_latency_us` | float | µs | `well_known` | One-way classical signal travel time |
| `transduction_efficiency_pct` | float | % | `well_known` | Microwave-to-optical conversion efficiency |
| `transduction_added_noise_quanta` | float | quanta | `approximate` | Noise added by transduction |
| `purification_overhead_ratio` | float | dimensionless | `approximate` | Raw pairs consumed per purified pair |

**Purification model (implemented in QREM interconnect profiles):**
- 85% raw fidelity → 2 purification rounds → 99.7% effective, 5,200× slowdown vs local gate
- 92% raw fidelity → 1 purification round → 99.3% effective, 1,100× slowdown
- 99% raw fidelity → 0 purification rounds → direct use, 550× slowdown

---

## Block 4 — Device Performance Implications

The computational bridge between material measurements and QREM hardware profile parameters. **Partially auto-populated by QREM from Block 3 inputs.**

### Connection to QREM Hardware Profiles

| Block 3/4 Field | QREM Hardware Profile Parameter |
|---|---|
| `T1_us` (Block 3) | `coherence.T1_us` — direct |
| `T2_echo_us` (Block 3) | `coherence.T2_us` — direct |
| `two_qubit_gate_fidelity_pct` (Block 3) | `gates.two_qubit_fidelity_pct` — direct, primary driver of code distance |
| `intermodule_link_fidelity_pct` (Block 3) | `intermodule.link_fidelity_pct` — direct |
| `implied_T1_from_loss_tangent_us` (Block 4) | `coherence.T1_us` — via mapping layer |
| `implied_code_distance` (Block 4) | Error correction layer |
| `implied_physical_per_logical_qubit` (Block 4) | Physical qubit overhead |
| `implied_module_count_benchmark` (Block 4) | Module count estimate |

**Planned — QREM Stage 4 (Loss Mechanism Attribution):** Block 4 will be extended with per-channel T1 breakdown once the QREM Stage 4 backend is implemented. Channels: TLS substrate, TLS interface, quasiparticle, vortex motion, radiation. Each channel computed from Block 3 inputs via Tier 2 physics formulas (Qi → T1_TLS, Tc → T1_QP, mean free path → T1_vortex) and labeled with individual provenance tier.

| Field | Type | Units | Source | Description |
|---|---|---|---|---|
| `implied_T1_from_loss_tangent_us` | float | µs | computed | T1 ≈ Q_TLS / (2π·f). Valid only where TLS is dominant loss. |
| `implied_T1_uncertainty_us` | float | µs | computed | Uncertainty bound on implied T1 |
| `implied_code_distance` | integer | — | computed | Minimum surface code distance d for 10⁻⁶ logical error rate |
| `implied_physical_per_logical_qubit` | integer | — | computed | Physical qubit overhead = 2d²-1 |
| `implied_module_count_benchmark` | integer | — | computed | Estimated modules for standard benchmark circuit |
| `coherence_budget_breakdown` | dict | % | computed | T1 loss attribution: `TLS_substrate`, `TLS_interface`, `quasiparticle`, `vortex_motion`, `radiation`, `unknown` |
| `mapping_confidence` | enum | — | human | `high`, `medium`, `low`, `not_computable` |
| `mapping_notes` | string | — | human | Assumptions made in computing implied values |

---

## Block 5 — Catch-All (Mandatory)

Every record must include at least a note in this block. The catch-all is a primary scientific output — it feeds the corpus mining pipeline and drives schema evolution.

### Guidance

**Additional measurements:** Any measurement with no schema field. `suspected_relevance` must cite specific physics, not generic statements. This includes routine measurements that happen to lack a named column — both everyday and novel. Fields appearing in >5% of materials samples are promoted to named columns via the schema evolution process.

**Anomalous observations:** Only results the authors flag as unexpected. Label whether hypothesis is from authors or your own assessment.

**Correlations observed:** Only author-stated correlations. Do not infer from data. These are processed by the corpus mining pipeline to produce materials-to-device connection hypotheses.

### Known Materials-to-Device Connections (for suspected_relevance)

```
Film purity and crystallinity:
  RRR → quasiparticle density → T1 relaxation time
  Mean free path (l) → clean vs dirty superconducting limit → vortex behavior
    l > ξ (clean limit) → vortex motion is primary loss channel
    l < ξ (dirty limit) → different loss mechanisms dominate
  Crystal phase (alpha vs beta Ta) → defect density → coherence and loss
  Grain size → surface roughness → TLS density at interfaces
  Lattice constant deviation from bulk → strain / defect density → loss

Surface and interface quality:
  Surface oxide thickness → TLS density → T2 dephasing and Qi
  Surface participation ratio → fraction of energy in lossy surface region
  Loss budget decomposition (metal-air, metal-substrate, substrate-air) → dominant loss channel

Superconducting properties:
  Tc → operating temperature margin; quasiparticle density at operating temp
  T/Tc ratio → quasiparticle population at operating temperature
  Vortex activation temperature → characterizes vortex motion loss channel
    Corpus finding (May 2026): dirty-limit Ta films show ~10× higher Tact than clean-limit films
  Sheet kinetic inductance → resonator frequency; superinductor applications

R vs T measurements:
  Normal state resistance + geometry → sheet resistance → kinetic inductance
  R(300K) / R(Tc+) → RRR → quasiparticle loss → T1

Microwave and device performance:
  Q_TLS,0 + p_MS_resonator → tan_delta = 1/(Q_TLS,0 × p_MS_res) → intrinsic surface loss tangent
  tan_delta + p_MS_pad → T1_pad_TLS = 1/(p_MS_pad × tan_delta × 2πf) → qubit pad TLS lifetime
  Note: Qi/ω gives resonator photon lifetime only — NOT qubit T1. The two-step inversion above
  is required. Validated by Bland 2025 Figure S5 (transmon Q lies on same line as resonator
  Q_TLS,0 vs p_MS). TLS saturation at qubit operating power means measured T1 may exceed
  single-photon model prediction — expected behavior, not a model failure.
  Loss tangent → dielectric contribution to T1
  T1 → gate fidelity upper bound (decoherence-limited); actual fidelity also depends on control errors
  Two-qubit gate fidelity: 99.5% → ~16 modules; 99.9% → ~2 modules (representative circuit)

Inter-module links:
  Raw link fidelity → purification rounds needed → effective entanglement rate and latency
  Slowdown factor = effective inter-module gate time / local gate time
    85% raw → 5,200× slowdown; 92% → 1,100×; 99% → 550×
  Each purification round boundary is a threshold: crossing it roughly halves the slowdown factor
```

### Catch-All Structure

```yaml
additional_measurements:
  - description: "..."
    value: ...
    units: "..."
    measurement_conditions: "..."
    suspected_relevance: "<specific physics connection>"

anomalous_observations:
  - description: "..."
    conditions: "..."
    hypothesis: "Author hypothesis: ... / Assessment: ..."

fabrication_notes: "..."

correlations_observed:
  - description: "..."
    measurement_a: "..."
    measurement_b: "..."
    nature: "..."

free_notes: "..."
```

---

## Block 6 — Similarity Profile (AI-generated, Pass 3)

Every ingested record includes a similarity profile generated by Claude (Pass 3) from the completed PUK. The profile enables semantic similarity search in the Explorer — matching samples by scientific character rather than numeric field overlap alone.

**Version:** `profile_version: "1.0"` — bump when vocabulary changes. Stale profiles regenerated via `backfill_similarity_profiles.py --filter <pattern>`.

**Scoring:** Explorer similarity search combines profile score (75%) and numeric field distance (25%). Profile dimensions use binary match (single fields) or Jaccard similarity (list fields).

**Known limitation:** `sim_material_class` assignment can be unreliable for less common materials (NbSe2, PtSi) — cosmetic Explorer sidebar issue only. Mining pipeline uses `derived_material` (deterministic) rather than `sim_material_class` for Phase A stratification.

### Profile Fields and Controlled Vocabularies

| Field | Type | Vocabulary |
|---|---|---|
| `material_class` | single | `niobium`, `aluminum`, `tantalum`, `rhenium`, `titanium_nitride`, `niobium_nitride`, `niobium_titanium_nitride`, `tantalum_nitride`, `tantalum_hafnium`, `niobium_diselenide`, `platinum_silicide`, `molybdenum_aluminum_carbide`, `other` |
| `transport_regime` | single | `clean_limit`, `dirty_limit`, `intermediate`, `unknown` |
| `loss_mechanisms` | list | `TLS_substrate`, `TLS_interface`, `TLS_metal_vacuum`, `TLS_unattributed`, `quasiparticle`, `vortex_motion`, `radiation`, `dielectric_substrate`, `surface_oxide`, `flux_noise`, `charge_noise`, `unknown` |
| `device_type` | single | `film_only`, `resonator`, `transmon`, `fluxonium`, `gatemon`, `junction_only`, `multi_qubit_device`, `unknown` |
| `coherence_tier` | single | `not_applicable`, `early_exploration`, `competitive`, `state_of_the_art` |
| `science_focus` | list | `process_optimization`, `loss_mechanism_identification`, `materials_characterization`, `device_demonstration`, `cross_platform_comparison`, `noise_characterization`, `surface_treatment`, `junction_engineering`, `scaling` |
| `growth_method` | single | `sputtering`, `MBE`, `ALD`, `CVD`, `evaporation`, `other` |
| `key_correlations` | list | `RRR_to_T1`, `anneal_to_crystal_phase`, `surface_oxide_to_Qi`, `thickness_to_loss`, `substrate_to_TLS`, `crystal_phase_to_loss`, `RRR_to_Qi`, `deposition_temp_to_phase`, `mean_free_path_to_vortex`, `Tc_to_gap`, `roughness_to_TLS`, `film_thickness_to_loss`, `interface_loss_to_T1`, `junction_quality_to_T1`, `annealing_to_RRR`, `film_stress_to_loss`, `impurity_to_loss`, `grain_size_to_loss`, `oxidation_to_Qi`, `surface_treatment_to_loss`, `substrate_treatment_to_TLS`, `kinetic_inductance_to_loss` |
| `profile_notes` | string | Free text — Claude's reasoning for non-obvious assignments |
| `profile_version` | string | e.g. `"1.0"` |

**Explorer integration:** The `material_class` field populates the sidebar filter in the Explorer. Note: Explorer sidebar uses `sim_material_class`; chart group-by and Phase A mining use `derived_material`. These may disagree for uncommon materials — `derived_material` is authoritative for scientific purposes.

---

## AI Review Process

The catch-all corpus is reviewed by the corpus mining pipeline (Phase A → B → C):
- Correlation items → hypothesis evidence tables → AI reasoning → structured findings
- Measurement frequency analysis → schema promotion candidates
- Anomalous observations → systematic effects worth investigating

Human scientists review mining findings via the ingestion pipeline UI (Stage 4). Approved findings enter `findings.jsonl` — the canonical, append-only mapping layer evidence ledger.

**Cadence:** Mining runs after each significant ingestion batch. Schema promotion reviewed quarterly.

---

## Schema Governance

| Role | Responsibility |
|---|---|
| Working group co-leads | Approve schema version changes |
| C2QA QREM team | Maintain ingester, Explorer, mining pipeline; propose schema candidates |
| Each center | Submit records; populate catch-all diligently |
| All centers jointly | Approve or defer schema evolution proposals |

**Schema versioning:** Minor versions add optional fields. Major versions change required fields and require record migration.

**Changes in v0.13 (May 2026):**
- `T2_ramsey_us` promoted from schema-defined field to named DB column. Was always in Block 3.4; now queryable and plottable in Explorer. Extraction prompt updated with explicit T2 echo vs Ramsey disambiguation.
- Explorer: per-point symbol encoding (solid/open circles) for derived best-available fields; variant legend inside chart when both variants present. Sidecar download button (MD/JSON). Strip plot jitter fix (range-relative). Dropdown reordered into logical groups.
- Manual exclusions expanded; corpus cleaned of non-superconducting systems and theory proposals with C2QA acknowledgments.

**Changes in v0.12 (May 2026):**
- Added `derived_tan_delta` derived column: `tan_delta_effective_surface` → `loss_tangent_interface` → `loss_tangent_substrate` priority.
- Added `Q_TLS_0` as plottable field in Explorer — physically distinct from Qi, not folded into `derived_Qi`.
- Removed raw Qi variants and raw loss tangent variants from Explorer dropdown — superseded by derived best-available fields.
- Added `derived_resistivity_uOhm_cm` fallback to `normal_state_resistivity_uOhm_cm` named field.
- Added manual exclusions mechanism: `exclusions.json` + `build_sqlite.py` support. JSONL unchanged.

**Changes in v0.11 (May 2026):**
- Added resonator geometry fields to Block 3.3: `Q_TLS_0`, `resonator_type`, `resonator_gap_width_um`, `p_MS_resonator`, `p_MS_pad` — enabling correct tan_delta extraction from resonator measurements.
- Added extraction prompt guidance for two-step Joshi inversion (Q_TLS,0 + p_MS_resonator → tan_delta → p_MS_pad → T1_pad_TLS).
- Updated Known Materials-to-Device Connections: replaced simple Qi/ω formula with correct two-step inversion; added TLS saturation note.

**Changes in v0.10 (May 2026):**
- Added `derived_Qi` column: `Qi_single_photon` → `Qi_internal_quality_factor` priority.
- Added `derived_T2_us` column: `T2_echo_us` → `T2_ramsey_us` priority.
- Established `derived_X` pattern for fields with multiple measurement variants.
- Multi-device extraction prompt fix: each characterized qubit/resonator extracted as a separate sample record.

**Changes in v0.7 (April 2026):**
- Promoted three fields to Block 3.1: `kinetic_inductance_sheet_pH_sq`, `mean_free_path_nm`, `vortex_activation_temperature_K`.
- Added `surface_participation_ratio` to Block 3.2; `film_width_um` to Block 2.2; `junction_vacuum_condition` to Block 2.3; `source_files` to Block 1.
- Retired `schema_candidate` catchall type — merged into `additional_measurement`; schema promotion now frequency-driven.
- Added `niobium_diselenide` and `platinum_silicide` to Block 6 `material_class` vocabulary; added `kinetic_inductance_to_loss` to `key_correlations`.

**Changes in v0.6:** Block 6 similarity profiles; hybrid similarity scoring; Explorer material class sidebar.

**Changes in v0.5:** QREM Hardware Profile Generation; purification model in Block 3.6; Block 4 direct field mappings.

**Changes in v0.4:** R vs T geometry fields promoted to Block 2.4.

**Changes in v0.3:** Display names; material name standardization; annealing fields promoted from catchall.

---

*End of Schema Document v0.13*
*Updated May 20, 2026.*
*Proposed for discussion at Five-Center Materials Working Group*
*Contact: C2QA QREM Team*
