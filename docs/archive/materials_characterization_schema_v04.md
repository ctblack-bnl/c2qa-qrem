# Materials Characterization Data Schema
## Five-Center Materials Working Group — Superconducting Systems
### Version 0.4 — R vs T Fields Added, Corpus Updated

**Date:** April 25, 2026
**Prepared by:** C2QA
**Status:** Active — publications ingester operational, corpus at scale, Explorer UI live
**Scope:** Superconducting qubit and resonator systems (neutral atom schema to follow)

---

## Purpose and Philosophy

This schema defines a standard format for reporting materials characterization data across the five DOE quantum centers. Two goals are held together:

**Goal 1 — Interoperability.** Common format enables aggregation and comparison across centers.

**Goal 2 — Computational utility.** Where the connection between a material property and device performance is known, the schema captures it explicitly — so a measurement doesn't just tell you what a material is, it tells you what that material enables computationally.

### The Catch-All Field

Not everything important is known in advance. The schema includes a mandatory `additional_observations` field for every record. Periodically, an AI review process examines the catch-all corpus looking for patterns — repeated measurements, emerging correlations, properties multiple centers track informally. When a pattern is identified it becomes a candidate for promotion into the formal schema.

The catch-all is not optional and not a dumping ground — it is a first-class scientific input and the primary source for identifying candidate materials-to-device connections for the QREM mapping layer.

---

## Implementation Status (v0.4)

### How Records Are Created

**Direct submission** — a scientist fills in schema fields manually. Highest-quality records.

**Publications ingester** — an AI-assisted tool reads scientific papers (PDFs) and automatically extracts schema-compatible records. See the Publications Ingester Specification for full details.

### Distinguishing Ingested from Submitted Records

Ingested records carry:
- `extraction_method: literature_ingestion`
- Every field has a `confidence` level (`high` / `medium` / `low`) and a `source` reference
- `human_reviewed: false` and `human_approved: false` until reviewed
- Sparse population — only fields actually reported in the paper are present

### Current Database State (April 25, 2026)

| Metric | Value |
|---|---|
| Papers processed | 85 |
| Papers ingested | ~50 |
| Skip rate | ~44% |
| Samples extracted | 130 |
| Catchall items | 1,169 |
| Coverage: Tc | 56% |
| Coverage: RRR | 32% |
| Coverage: Qi | 19% |
| Coverage: T1 | 12% |

### Display Names

Each sample gets a compound identifier: `{first_author}_{year}_{sample_id}` (e.g. `Bahrami_2026_D1`). This is a display layer addition — the original `sample_id` is preserved.

### Material Name Standardization

Standard chemical abbreviations are enforced at extraction time:

| Paper description | Extracted as |
|---|---|
| tantalum, Ta film, Ta metal | Ta |
| niobium, Nb film | Nb |
| niobium titanium nitride | NbTiN |
| tantalum nitride | TaN |
| Ta-Hf alloy (83% Ta, 17% Hf) | Ta-Hf (83:17) |

Crystal phase always goes in `film_crystal_phase`, never in `film_material` (e.g. alpha-Ta → `film_material: Ta`, `film_crystal_phase: alpha-Ta (bcc)`).

### Candidate Schema Promotion Fields (Updated v0.4)

The following parameters appear repeatedly in the catchall and are candidates for Block 3 promotion:

| Parameter | Appeared in | Suspected relevance |
|---|---|---|
| Coherence length (ξ, nm) | Multiple papers | Determines clean vs dirty limit; affects vortex pinning and loss |
| Mean free path (l, nm) | Multiple papers | ξ/l ratio determines superconducting limit classification |
| Vortex activation temperature (K) | Ta papers | Characterizes vortex motion loss channel in resonators |
| Lattice constant (Å) | Multiple papers | Deviation from bulk indicates strain/defect density |
| Upper critical field Hc2 (T) | Multiple papers | Operating magnetic field margin; used to compute coherence length |
| Normal resistivity at 5K (µΩ·cm) | Multiple papers | Indicator of defect density; related to but distinct from RRR |
| Viscous drag coefficient η | Ta vortex papers | Quantifies energy dissipation from vortex motion |

Note: `annealing_temperature_C` and `annealing_duration_s` (v0.2 candidates) and R vs T measurement fields (v0.4) have been promoted to structured fields.

---

## Schema Structure Overview

```
[1] RECORD METADATA         — who, where, when, what sample
[2] SAMPLE DESCRIPTION      — what material, how made, R vs T geometry
[3] STRUCTURED MEASUREMENTS — defined fields with known device mappings
[4] DEVICE PERFORMANCE IMPLICATIONS — what measurements mean computationally
[5] CATCH-ALL               — everything else, free-form but guided
```

---

## Block 1 — Record Metadata

| Field | Type | Required | Description |
|---|---|---|---|
| `record_id` | string | Yes | Format: `{CENTER}-{YYYYMMDD}-{SEQ}` e.g. `C2QA-20260415-001` |
| `center` | enum | Yes | One of: `C2QA`, `SQMS`, `Q-NEXT`, `QSA`, `QED-C` |
| `submitting_lab` | string | Yes | Institution and lab name |
| `submitter` | string | Yes | Name of responsible scientist |
| `date_measured` | date | Yes | ISO format: YYYY-MM-DD |
| `date_submitted` | date | Yes | ISO format: YYYY-MM-DD |
| `schema_version` | string | Yes | e.g. `0.4` |
| `sample_id` | string | Yes | Center-internal sample identifier |
| `extraction_method` | enum | No | One of: `direct_submission`, `literature_ingestion` |
| `source_doi` | string | No | DOI of source paper (for literature_ingestion records) |
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
| `film_material` | enum | Yes | Standard chemical abbreviation: `Nb`, `NbTiN`, `NbN`, `Al`, `TiN`, `Ta`, `Re`, `other`. Never spell out element names. |
| `film_material_other` | string | If other | Chemical formula e.g. `Ta-Hf (83:17)`, `TaN` |
| `film_crystal_phase` | string | No | e.g. `alpha-Ta (bcc)`, `beta-Ta (tetragonal)`. Always use this field for crystal phase — never include in `film_material`. Critical for Ta films. |
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

### 2.4 R vs T Measurement Geometry (Added v0.4)

These fields enable derivation of intrinsic material properties (sheet resistance, RRR, resistivity) from resistance measurements on patterned structures. They should be extracted whenever an R vs T curve is reported.

| Field | Type | Required | Description |
|---|---|---|---|
| `normal_state_resistance_Ohm` | float | No | Resistance just above Tc (normal state). With geometry, enables sheet resistance derivation. |
| `room_temperature_resistance_Ohm` | float | No | Resistance at ~300K. With normal state R, enables RRR derivation. |
| `measured_structure_width_um` | float | No | Width of patterned structure used for resistance measurement, in microns |
| `measured_structure_length_um` | float | No | Length of patterned structure used for resistance measurement, in microns |

**Why these matter:** Sheet resistance Rs = Rn × (width/length) [Ω/□]; RRR = R(300K)/R(Tc+). These are the intrinsic properties that allow comparison across samples with different device geometries. The `derive.py` module computes these automatically when geometry is available.

---

## Block 3 — Structured Measurements

Defined measurement fields with known or approximate connections to device performance.

**Mapping status values:**
- `well_known` — relationship to device performance established in literature
- `approximate` — understood directionally but quantitative mapping uncertain
- `open_research` — connection suspected but not yet established

### 3.1 Superconducting Properties

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `Tc_K` | float | Kelvin | `well_known` | Operating temperature margin; quasiparticle density |
| `Tc_uniformity_pct` | float | % std dev | `approximate` | Fabrication yield; qubit frequency uniformity |
| `RRR` | float | dimensionless | `well_known` | Film purity; quasiparticle loss. Note: RRR is dimensionless — if units are reported it is a different quantity. |
| `sheet_resistance_Ohm_sq` | float | Ω/□ | `well_known` | Kinetic inductance; qubit frequency |
| `London_penetration_depth_nm` | float | nm | `approximate` | Surface loss contribution |
| `upper_critical_field_T` | float | Tesla | `well_known` | Operating magnetic field margin; used to derive coherence length |

### 3.2 Dielectric and Surface Loss

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `loss_tangent_substrate` | float | dimensionless | `well_known` | T1 coherence time (dielectric loss) |
| `loss_tangent_substrate_frequency_GHz` | float | GHz | — | Measurement frequency (required for context) |
| `loss_tangent_substrate_temperature_mK` | float | mK | — | Measurement temperature (required for context) |
| `loss_tangent_interface` | float | dimensionless | `approximate` | T1 coherence time (interface loss) |
| `loss_tangent_interface_type` | enum | — | — | One of: `metal_substrate`, `metal_vacuum`, `substrate_vacuum` |
| `TLS_density_per_GHz_per_um2` | float | GHz⁻¹·μm⁻² | `well_known` | T2 dephasing; resonator quality factor |
| `TLS_coupling_strength_MHz` | float | MHz | `approximate` | Individual TLS-qubit interaction strength |
| `TLS_measurement_protocol` | string | — | — | Reference to protocol used |
| `surface_oxide_thickness_nm` | float | nm | `approximate` | TLS density; interface loss |
| `surface_oxide_composition` | string | — | `open_research` | TLS species identification |

### 3.3 Microwave Performance

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `Qi_internal_quality_factor` | float | dimensionless | `well_known` | Resonator loss; T1. Note: Qi is internal quality factor — do not confuse with Qc (coupling). |
| `Qi_measurement_power_dBm` | float | dBm | — | Single-photon regime should be noted |
| `Qi_measurement_frequency_GHz` | float | GHz | — | Required for context |
| `Qi_measurement_temperature_mK` | float | mK | — | Required for context |
| `Qi_single_photon` | float | dimensionless | `well_known` | Most relevant for qubit operating conditions |
| `Qc_coupling_quality_factor` | float | dimensionless | `well_known` | Resonator-qubit coupling design |
| `microwave_loss_mechanism` | string | — | `approximate` | Dominant loss: `TLS`, `quasiparticle`, `vortex_motion`, `radiation` |

### 3.4 Qubit Performance (if device-level measurement)

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `T1_us` | float | µs | `well_known` | Gate fidelity; error correction code distance. Note: T1 may be reported in ms — always convert to µs. |
| `T1_std_us` | float | µs | `well_known` | Fabrication variability; yield modeling |
| `T2_echo_us` | float | µs | `well_known` | Dephasing; gate fidelity for longer sequences |
| `T2_ramsey_us` | float | µs | `well_known` | Low-frequency noise environment |
| `T1_measurement_protocol` | string | — | — | Reference to protocol used |
| `qubit_frequency_GHz` | float | GHz | `well_known` | Operating point; collision avoidance |
| `qubit_frequency_std_GHz` | float | GHz | `approximate` | Frequency crowding in scaled systems |
| `anharmonicity_MHz` | float | MHz | `well_known` | Gate speed limit; leakage rate |
| `single_qubit_gate_fidelity_pct` | float | % | `well_known` | Error correction overhead (local gates) |
| `single_qubit_gate_time_ns` | float | ns | `well_known` | Circuit runtime; coherence budget |
| `two_qubit_gate_fidelity_pct` | float | % | `well_known` | Error correction overhead (dominant cost). A 0.4% improvement (99.5% → 99.9%) can reduce module count by 8× for representative circuits. |
| `two_qubit_gate_time_ns` | float | ns | `well_known` | Circuit runtime; coherence budget |
| `readout_fidelity_pct` | float | % | `well_known` | Syndrome measurement accuracy in QEC |
| `readout_time_ns` | float | ns | `well_known` | QEC cycle time |

### 3.5 Noise Characterization

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `flux_noise_amplitude_uPhi0_per_sqrtHz` | float | μΦ₀/√Hz | `well_known` | T2 dephasing in flux-tunable qubits |
| `charge_noise_amplitude_e_per_sqrtHz` | float | e/√Hz | `approximate` | Charge noise sensitivity |
| `noise_exponent_1f` | float | dimensionless | `approximate` | 1/f noise character; long-sequence fidelity |
| `quasiparticle_density_per_um3` | float | μm⁻³ | `well_known` | T1 quasiparticle loss channel |
| `quasiparticle_parity_switching_rate_kHz` | float | kHz | `well_known` | Parity error rate in error correction |

### 3.6 Inter-Module / Interconnect Properties

These fields are specifically relevant to modular architectures and map directly to QREM hardware profile parameters without requiring the predictor or mapping layer.

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `intermodule_link_type` | enum | — | — | One of: `microwave_photonic`, `optical_photonic`, `direct_wire`, `other` |
| `intermodule_link_fidelity_pct` | float | % | `well_known` | Inter-module gate error correction overhead |
| `intermodule_entanglement_rate_Hz` | float | Hz | `well_known` | Inter-module communication throughput |
| `intermodule_link_latency_us` | float | µs | `well_known` | QEC syndrome propagation delay across modules |
| `transduction_efficiency_pct` | float | % | `well_known` | Microwave-to-optical conversion loss |
| `transduction_added_noise_quanta` | float | quanta | `approximate` | Noise added by transduction process |
| `intermodule_entanglement_fidelity_pct` | float | % | `well_known` | Raw Bell pair quality before purification |
| `purification_overhead_ratio` | float | dimensionless | `approximate` | Raw pairs needed per high-fidelity pair |

---

## Block 4 — Device Performance Implications

The computational bridge — translates structured measurements into device-level parameters that feed directly into QREM. **May be partially auto-populated by the QREM tool from Block 3 inputs.**

### Connection to QREM Hardware Profiles

| Block 4 Field | QREM Hardware Profile Parameter |
|---|---|
| `implied_T1_from_loss_tangent_us` | `coherence.T1_us` |
| `implied_code_distance` | Error correction layer |
| `implied_physical_per_logical_qubit` | Physical qubit overhead |
| `implied_module_count_benchmark` | Module count estimate |
| `intermodule_link_fidelity_pct` (Block 3) | `intermodule.link_fidelity_pct` |
| `transduction_efficiency_pct` (Block 3) | `intermodule.transduction_efficiency_pct` |

| Field | Type | Units | Source | Description |
|---|---|---|---|---|
| `implied_T1_from_loss_tangent_us` | float | µs | computed | T1 ≈ Q_TLS / (2π·f). Valid only where TLS is dominant loss mechanism. |
| `implied_T1_uncertainty_us` | float | µs | computed | Uncertainty bound on implied T1 |
| `implied_code_distance` | integer | — | computed | Minimum surface code distance d for 10⁻⁶ logical error rate. Null if gate fidelity not measured. |
| `implied_physical_per_logical_qubit` | integer | — | computed | Physical qubit overhead = 2d²-1. Null if code distance not computable. |
| `implied_module_count_benchmark` | integer | — | computed | Estimated modules for standard benchmark circuit. Enables cross-center comparison. |
| `coherence_budget_breakdown` | dict | % | computed | T1 loss attribution: `TLS_substrate`, `TLS_interface`, `quasiparticle`, `vortex_motion`, `radiation`, `unknown` |
| `mapping_confidence` | enum | — | human | Overall confidence: `high`, `medium`, `low`, `not_computable` |
| `mapping_notes` | string | — | human | Assumptions made in computing implied values |

---

## Block 5 — Catch-All (Mandatory)

Every record must include at least a note in this block. The catch-all is a primary scientific output — it captures knowledge not yet formalized into schema fields and drives schema evolution.

### Guidance for Populating the Catch-All

**Additional measurements:** Any measurement with no schema field. `suspected_relevance` must cite specific physics — not generic statements.

**Anomalous observations:** Only results the authors flag as unexpected. Label whether the hypothesis is from the authors or your own assessment.

**Correlations observed:** Only correlations the authors themselves stated or clearly implied. Do not infer correlations from data.

**Schema promotion candidates:** Flag important parameters with no schema field. Explain what would be lost without tracking it.

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
  Native oxide regrowth rate → processing sensitivity → yield

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
  T1 → gate fidelity → error correction code distance → module count
  Two-qubit gate fidelity: 99.5% → ~16 modules; 99.9% → ~2 modules
```

### 5.1 Additional Measurements

```yaml
additional_measurements:
  - description: "..."
    value: ...
    units: "..."
    measurement_conditions: "..."
    suspected_relevance: "<specific physics connection>"
```

### 5.2 Anomalous Observations

```yaml
anomalous_observations:
  - description: "..."
    conditions: "..."
    hypothesis: "Author hypothesis: ... / Assessment: ..."
```

### 5.3 Fabrication Notes

```yaml
fabrication_notes: "..."
```

### 5.4 Correlations Observed

```yaml
correlations_observed:
  - description: "..."
    measurement_a: "..."
    measurement_b: "..."
    nature: "..."
```

### 5.5 Free Notes

```yaml
free_notes: "..."
```

---

## AI Review Process

The catch-all corpus is reviewed periodically using AI-assisted pattern analysis:

- Fields appearing repeatedly → candidates for structured field promotion
- Correlations between catch-all and structured fields → QREM mapping layer candidates
- Anomalous observations at multiple centers → systematic effects worth investigating
- Author-stated materials-to-device connections → evidence base for QREM mapping layer

**Review cadence:** Quarterly, aligned with working group meetings.
**Output:** Schema evolution proposal document. Working group approves or defers each candidate.

---

## Schema Governance

| Role | Responsibility |
|---|---|
| Working group co-leads | Approve schema version changes |
| C2QA QREM team | Maintain AI review process; propose schema candidates; maintain publications ingester |
| Each center | Submit records; populate catch-all diligently |
| All centers jointly | Approve or defer schema evolution proposals |

**Schema versioning:** Semantic versioning. Minor versions add optional fields. Major versions change required fields or semantics and require migration of existing records.

**Changes in v0.4:**
- Updated corpus stats to reflect current database (85 records, 130 samples, 1169 catchall items)
- Added Block 2.4 — R vs T Measurement Geometry (new structured fields: `normal_state_resistance_Ohm`, `room_temperature_resistance_Ohm`, `measured_structure_width_um`, `measured_structure_length_um`)
- Removed "crystal phase" from schema promotion candidates — already captured in `film_crystal_phase`
- Added T/Tc ratio and R vs T connections to Block 5 domain knowledge glossary
- Streamlined Implementation Status section
- Added note to Block 3.6 that inter-module fields map directly to QREM without requiring predictor

**Changes in v0.3:**
- Added `display_name` concept for cross-paper sample identification
- Added material name standardization — abbreviations enforced at extraction time
- Updated schema promotion candidates based on larger corpus
- Added extraction error warnings to Block 3 field descriptions
- Promoted `annealing_temperature_C` and `annealing_duration_s` from catchall to Block 2

---

*End of Schema Document v0.4*
*Original document produced April 2026. Updated April 25, 2026.*
*Proposed for discussion at Five-Center Materials Working Group*
*Contact: C2QA QREM Team*
