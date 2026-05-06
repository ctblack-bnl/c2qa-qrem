# Materials Characterization Data Schema
## Five-Center Materials Working Group — Superconducting Systems
### Version 0.6 — Similarity Profiles, Hybrid Search, Explorer Material Classes

**Date:** April 27, 2026
**Prepared by:** C2QA
**Status:** Active — ingester operational, Explorer live at https://c2qa-materials-explorer.onrender.com
**Scope:** Superconducting qubit and resonator systems (neutral atom schema to follow)

---

## Purpose and Philosophy

This schema defines a standard format for reporting materials characterization data across the five DOE quantum centers. Two goals are held together:

**Goal 1 — Interoperability.** Common format enables aggregation and comparison across centers.

**Goal 2 — Computational utility.** Where the connection between a material property and device performance is known, the schema captures it explicitly — so a measurement doesn't just tell you what a material is, it tells you what that material enables computationally.

### Records as Portable Units of Knowledge (PUKs)

Each schema record is self-contained: provenance, measured properties with confidence levels, derived quantities, catchall observations, device performance implications, and a semantic similarity profile. The six-block structure captures everything about a sample in one place.

The QREM pipeline can project any record into a hardware profile on demand. The similarity profile enables semantic search across the corpus. Both are derived from the record — the record is always the source of truth.

### The Catch-All

The catch-all is mandatory and is a first-class scientific output. It captures knowledge not yet formalized into schema fields and drives schema evolution. The ~31 author-stated correlations in the current corpus are particularly valuable — they form the evidence base for the QREM mapping layer.

---

## Implementation Status (v0.6)

### How Records Are Created

**Direct submission** — a scientist fills in schema fields manually. Highest-quality records.

**Publications ingester** — AI-assisted tool reads PDFs and automatically extracts schema-compatible records via three passes:
- Pass 1 — Relevance check
- Pass 2 — Full structured extraction → PUK
- Pass 3 — Similarity profile generation → appended to PUK

Ingested records carry per-field confidence levels (`high`/`medium`/`low`) and source references, and start with `human_reviewed: false`, `human_approved: false`.

### Current Database State (April 27, 2026)

| Metric | Value |
|---|---|
| Papers processed | 97 |
| Papers ingested | ~56 |
| Skip rate | ~44% |
| Samples extracted | 155 |
| Catchall items | ~1,300 |
| Similarity profiles | 155 (100%) |
| Coverage: Tc | 56% |
| Coverage: RRR | 32% |
| Coverage: Qi | 19% |
| Coverage: T1 | 12% |

### QREM Hardware Profile Generation

Records with device performance data (T1, T2, gate fidelity) can be projected into QREM qubit hardware profiles. Triggered via the Explorer UI "Generate Qubit Profile" button. Measured fields are labeled `[MEASURED]`; unmeasured fields use defaults from `transmon_baseline_2026.yaml`, labeled `[ASSUMED]`.

**Near-term architecture:** profiles are generated as YAML files consumed by QREM. **Target architecture:** QREM queries the database directly, generating profiles in memory. The record remains the source of truth in both cases.

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

Crystal phase always goes in `film_crystal_phase`, never in `film_material`.

### Display Names

Each sample: `{first_author}_{year}_{sample_id}` (e.g. `Wang_2026_Transmon_1`).

### Candidate Schema Promotion Fields

| Parameter | Appeared in | Suspected relevance |
|---|---|---|
| Coherence length (ξ, nm) | Multiple papers | Clean vs dirty limit; vortex pinning and loss |
| Mean free path (l, nm) | Multiple papers | ξ/l ratio determines superconducting limit |
| Vortex activation temperature (K) | Ta papers | Vortex motion loss channel in resonators |
| Lattice constant (Å) | Multiple papers | Deviation from bulk → strain/defect density |
| Upper critical field Hc2 (T) | Multiple papers | Operating field margin; coherence length derivation |
| Normal resistivity at 5K (µΩ·cm) | Multiple papers | Defect density indicator |
| Viscous drag coefficient η | Ta vortex papers | Energy dissipation from vortex motion |

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
| `schema_version` | string | Yes | e.g. `0.6` |
| `sample_id` | string | Yes | Center-internal sample identifier |
| `extraction_method` | enum | No | One of: `direct_submission`, `literature_ingestion` |
| `source_doi` | string | No | DOI of source paper |
| `source_reference` | string | No | Specific location e.g. "Table I row 3" |
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
| `film_material` | enum | Yes | Standard abbreviation: `Nb`, `NbTiN`, `NbN`, `Al`, `TiN`, `Ta`, `Re`, `other`. Never spell out. |
| `film_material_other` | string | If other | Chemical formula e.g. `Ta-Hf (83:17)`, `TaN` |
| `film_crystal_phase` | string | No | e.g. `alpha-Ta (bcc)`, `beta-Ta (tetragonal)`. Always here, never in `film_material`. |
| `film_thickness_nm` | float | Yes | Film thickness in nanometers |
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
| `junction_material` | string | If yes | e.g. `Al/AlOx/Al`, `Nb/AlOx/Nb` |
| `junction_fabrication_method` | string | If yes | e.g. `double-angle evaporation`, `overlap junction` |
| `junction_area_um2` | float | If yes | Junction area in square microns |
| `junction_oxidation_conditions` | string | If yes | Pressure, time, temperature of oxidation step |
| `junction_resistance_normal_Ohm` | float | If yes | Normal-state resistance in Ohms |

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

### 3.3 Microwave Performance

| Field | Type | Units | Mapping | Downstream Device Parameter |
|---|---|---|---|---|
| `Qi_internal_quality_factor` | float | dimensionless | `well_known` | Resonator loss; T1. Do not confuse with Qc (coupling). |
| `Qi_measurement_power_dBm` | float | dBm | — | Single-photon regime should be noted |
| `Qi_measurement_frequency_GHz` | float | GHz | — | Required for context |
| `Qi_measurement_temperature_mK` | float | mK | — | Required for context |
| `Qi_single_photon` | float | dimensionless | `well_known` | Most relevant for qubit operating conditions |
| `Qc_coupling_quality_factor` | float | dimensionless | `well_known` | Resonator-qubit coupling design |
| `microwave_loss_mechanism` | string | — | `approximate` | Dominant loss: `TLS`, `quasiparticle`, `vortex_motion`, `radiation` |

### 3.4 Qubit Performance (device-level measurement)

| Field | Type | Units | Mapping | Downstream Device Parameter |
|---|---|---|---|---|
| `T1_us` | float | µs | `well_known` | Gate fidelity; code distance. Note: T1 may be reported in ms — always convert to µs. |
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

Every record must include at least a note in this block. The catch-all is a primary scientific output and the primary source for schema evolution and QREM mapping layer development.

### Guidance

**Additional measurements:** Any measurement with no schema field. `suspected_relevance` must cite specific physics.

**Anomalous observations:** Only results the authors flag as unexpected. Label whether hypothesis is from authors or your own assessment.

**Correlations observed:** Only author-stated correlations. Do not infer from data.

**Schema promotion candidates:** Flag important parameters with no schema field.

### Known Materials-to-Device Connections (for suspected_relevance)

```
Film purity and crystallinity:
  RRR → quasiparticle density → T1 relaxation time
  Mean free path (l) → clean vs dirty superconducting limit → vortex behavior
  Crystal phase (alpha vs beta Ta) → defect density → coherence and loss
  Grain size → surface roughness → TLS density at interfaces
  Lattice constant deviation from bulk → strain / defect density → loss

Surface and interface quality:
  Surface oxide thickness → TLS density → T2 dephasing and Qi
  Loss budget decomposition (metal-air, metal-substrate, substrate-air) → dominant loss channel identification

Superconducting properties:
  Tc → operating temperature margin; quasiparticle density at operating temp
  T/Tc ratio → quasiparticle population at operating temperature
  xi < l (clean limit) → vortex motion is primary loss channel
  xi > l (dirty limit) → different loss mechanisms dominate
  Vortex activation temperature → characterizes vortex motion loss channel

R vs T measurements:
  Normal state resistance + geometry → sheet resistance → kinetic inductance
  R(300K) / R(Tc+) → RRR → quasiparticle loss → T1

Microwave and device performance:
  Qi → resonator loss → directly sets T1 upper bound
  Loss tangent → dielectric contribution to T1
  T1 → gate fidelity upper bound (decoherence-limited); actual fidelity also depends on control errors
  Two-qubit gate fidelity: 99.5% → ~16 modules; 99.9% → ~2 modules (representative circuit)

Inter-module links:
  Raw link fidelity → purification rounds needed → effective entanglement rate and latency
  Slowdown factor = effective inter-module gate time / local gate time
    85% raw → 5,200× slowdown; 92% → 1,100×; 99% → 550×
  Each purification round boundary is a threshold: crossing it halves the slowdown factor
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

**Version:** `profile_version: "1.0"` — bump when vocabulary changes. Stale profiles (version mismatch) should be regenerated via backfill.

**Generation:** Automatic at ingestion time. Can be regenerated for existing records via `backfill_similarity_profiles.py`.

**Scoring:** Explorer similarity search combines profile score (75%) and numeric field distance (25%). Profile dimensions use binary match (single fields) or Jaccard similarity (list fields).

### Profile Fields and Controlled Vocabularies

| Field | Type | Vocabulary |
|---|---|---|
| `material_class` | single | `niobium`, `aluminum`, `tantalum`, `rhenium`, `titanium_nitride`, `niobium_nitride`, `niobium_titanium_nitride`, `tantalum_nitride`, `tantalum_hafnium`, `other` (and others — see prompt) |
| `transport_regime` | single | `clean_limit`, `dirty_limit`, `intermediate`, `unknown` |
| `loss_mechanisms` | list | `TLS_substrate`, `TLS_interface`, `TLS_metal_vacuum`, `TLS_unattributed`, `quasiparticle`, `vortex_motion`, `radiation`, `dielectric_substrate`, `surface_oxide`, `flux_noise`, `charge_noise`, `unknown` |
| `device_type` | single | `film_only`, `resonator`, `transmon`, `fluxonium`, `gatemon`, `junction_only`, `multi_qubit_device`, `unknown` |
| `coherence_tier` | single | `not_applicable`, `early_exploration`, `competitive`, `state_of_the_art` |
| `science_focus` | list | `process_optimization`, `loss_mechanism_identification`, `materials_characterization`, `device_demonstration`, `cross_platform_comparison`, `noise_characterization`, `surface_treatment`, `junction_engineering`, `scaling` |
| `growth_method` | single | `sputtering`, `MBE`, `ALD`, `CVD`, `evaporation`, `other` |
| `key_correlations` | list | `RRR_to_T1`, `anneal_to_crystal_phase`, `surface_oxide_to_Qi`, `thickness_to_loss`, `substrate_to_TLS`, `crystal_phase_to_loss`, `RRR_to_Qi`, `deposition_temp_to_phase`, `mean_free_path_to_vortex`, `Tc_to_gap`, `roughness_to_TLS`, `film_thickness_to_loss`, `interface_loss_to_T1`, `junction_quality_to_T1`, `annealing_to_RRR`, `film_stress_to_loss`, `impurity_to_loss`, `grain_size_to_loss`, `oxidation_to_Qi`, `surface_treatment_to_loss`, `substrate_treatment_to_TLS` |
| `profile_notes` | string | Free text — Claude's reasoning for non-obvious assignments |
| `profile_version` | string | e.g. `"1.0"` |

**Explorer integration:** The `material_class` field populates the sidebar filter in the Explorer, replacing the unwieldy per-material-string list with a stable set of ~10 categories.

---

## AI Review Process

The catch-all corpus is reviewed periodically:
- Fields appearing repeatedly → schema promotion candidates
- Author-stated correlations → QREM mapping layer evidence base
- Anomalous observations at multiple centers → systematic effects worth investigating

**Review cadence:** Quarterly, aligned with working group meetings.

---

## Schema Governance

| Role | Responsibility |
|---|---|
| Working group co-leads | Approve schema version changes |
| C2QA QREM team | Maintain ingester, Explorer, AI review; propose schema candidates |
| Each center | Submit records; populate catch-all diligently |
| All centers jointly | Approve or defer schema evolution proposals |

**Schema versioning:** Minor versions add optional fields. Major versions change required fields and require record migration.

**Changes in v0.6 (April 27, 2026):**
- Added Block 6 — Similarity Profile (Pass 3, AI-generated semantic tags)
- Updated corpus stats (97 papers, 155 samples, 100% profile coverage)
- Explorer sidebar now filters by `material_class` (Block 6) rather than exact film_material string
- Hybrid similarity scoring: 75% profile, 25% numeric field distance
- Pass 3 integrated into `pipeline_ingest.py` — profiles generated automatically at ingestion

**Changes in v0.5:** QREM Hardware Profile Generation; purification model in Block 3.6; Block 4 direct field mappings; public Explorer URL.

**Changes in v0.4:** R vs T geometry fields promoted to Block 2.4; T/Tc ratio added to Block 5.

**Changes in v0.3:** Display names; material name standardization; annealing fields promoted from catchall.

---

*End of Schema Document v0.6*
*Updated April 27, 2026.*
*Proposed for discussion at Five-Center Materials Working Group*
*Contact: C2QA QREM Team*
