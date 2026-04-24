# Materials Characterization Data Schema
## Five-Center Materials Working Group — Superconducting Systems
### Version 0.3 — Active, Corpus at Scale

**Date:** April 23, 2026
**Prepared by:** C2QA
**Status:** Active — publications ingester operational, corpus at scale, Explorer UI live
**Scope:** Superconducting qubit and resonator systems (neutral atom schema to follow)

---

## Purpose and Philosophy

This schema defines a standard format for reporting materials characterization data across the five DOE quantum centers. It has two goals that are deliberately held together:

**Goal 1 — Interoperability.** When all centers report data in a common format, results can be aggregated, compared, and jointly analyzed regardless of which center produced them.

**Goal 2 — Computational utility.** Where the connection between a material property and device performance is known, the schema captures it explicitly. This allows characterization data to feed directly into resource estimation tools — so a measurement doesn't just tell you what a material is, it tells you what that material enables computationally.

### The Catch-All Field

Not everything important is known in advance. The schema includes a mandatory unstructured `additional_observations` field for every record. This field accepts any measurement, observation, or note that doesn't fit the defined fields.

Periodically, an AI review process will examine the corpus of catch-all entries across all centers, looking for patterns — measurements that appear repeatedly, correlations that emerge, properties that multiple centers are tracking informally. When a pattern is identified, it becomes a candidate for promotion into the formal schema. This means the schema is explicitly designed to evolve as the field's understanding matures.

The catch-all is not optional and not a dumping ground — it is a first-class scientific input. It is also the primary source for identifying candidate materials-to-device connections for the QREM mapping layer (see Section: Connection to QREM).

---

## Implementation Status (Updated v0.3)

### How Records Are Created

Records in the materials characterization database can be created in two ways:

**Direct submission** — a scientist fills in schema fields manually from their own experimental data. This produces the highest-quality records with the deepest context.

**Publications ingester** — an AI-assisted tool reads scientific papers (PDFs) and automatically extracts schema-compatible records. This approach populates the database at scale without requiring scientists to fill out forms separately from their publication workflow. See the Publications Ingester Specification for full details.

### Distinguishing Ingested from Submitted Records

Records created by the ingester are distinguished from directly submitted records by:

- `extraction_method: literature_ingestion` flag in Block 1
- Every extracted field carries a `confidence` level (`high` / `medium` / `low`) and a `source` reference (e.g. "Table I column 3")
- `human_reviewed: false` and `human_approved: false` flags until reviewed by a scientist
- Sparse population — only fields actually reported in the paper are present

Records created by direct submission are assumed to be high confidence throughout unless otherwise noted.

### Current Database State (April 23, 2026)

The publications ingester has been run against C2QA center publications at scale:

- 62 papers processed
- ~35 papers ingested (remainder correctly skipped as not relevant — ~44% skip rate)
- 150+ samples extracted (estimate — run in progress)
- Catchall items: 1000+ (estimate)

Previous corpus (18 papers) showed coverage: Tc 57%, RRR 33%, Qi 18%, T1 13%. The Qi and T1 coverage improvement over the initial corpus (6% and 5% respectively) reflects deliberate addition of device performance papers alongside materials characterization papers.

### Display Names for Cross-Paper Identification

A key addition in v0.3 is the `display_name` field in the SQLite database layer. Each sample gets a compound identifier of the form:

```
{first_author}_{year}_{sample_id}
```

Examples: `Bahrami_2026_D1`, `Yang_2026_Ta-Hf_1ks_750C`, `Bøttcher_2025_NbN_CPW_resonators_ALE`

This makes samples unambiguous across papers when browsing the database. The original `sample_id` from the paper is preserved — `display_name` is a display layer addition, not a replacement.

### Material Name Standardization (Added v0.3)

Material name consistency is now enforced at extraction time via the ingester prompt. Claude is instructed to use standard chemical abbreviations for the `film_material` field:

| Paper description | Extracted as |
|---|---|
| tantalum, Ta film, Ta metal | Ta |
| niobium, Nb film | Nb |
| niobium titanium nitride | NbTiN |
| tantalum nitride | TaN |
| Ta-Hf alloy (83% Ta, 17% Hf) | Ta-Hf (83:17) |

Crystal phase always goes in `film_crystal_phase`, never in `film_material`:
- alpha-Ta → `film_material: Ta`, `film_crystal_phase: alpha-Ta (bcc)`

This prevents the normalization problem where "Tantalum (Ta)" and "tantalum (Ta)" appear as separate categories in analysis. The prompt-level fix requires no ongoing human maintenance.

### Candidate Schema Promotion Fields (Updated v0.3)

The following parameters appeared repeatedly in the catchall across the ingested corpus and are candidates for promotion to Block 3 structured fields. This list has been updated from v0.2 based on the larger corpus:

| Parameter | Appeared in | Suspected relevance |
|---|---|---|
| Coherence length (ξ, nm) | Multiple papers | Determines clean vs dirty limit; affects vortex pinning and loss |
| Mean free path (l, nm) | Multiple papers | ξ/l ratio determines superconducting limit classification |
| Vortex activation temperature (K) | Ta papers | Characterizes vortex motion loss channel in resonators |
| Crystal phase (alpha vs beta Ta) | Multiple Ta papers | Alpha-Ta has significantly better qubit performance than beta-Ta |
| Lattice constant (Å) | Multiple papers | Deviation from bulk indicates strain/defect density |
| Upper critical field Hc2 (T) | Multiple papers | Operating magnetic field margin; used to compute coherence length |
| Normal resistivity at 5K (µΩ·cm) | Multiple papers | Indicator of defect density; related to but distinct from RRR |
| Viscous drag coefficient η | Ta vortex papers | Quantifies energy dissipation from vortex motion |

Note: `annealing_temperature_C` and `annealing_duration_s` from the v0.2 candidate list have been promoted to Block 2 structured fields in this version.

---

## Schema Structure Overview

Each characterization record consists of five blocks:

```
[1] RECORD METADATA        — who, where, when, what sample
[2] SAMPLE DESCRIPTION     — what material, how made
[3] STRUCTURED MEASUREMENTS — defined fields with known device mappings
[4] DEVICE PERFORMANCE IMPLICATIONS — what these measurements mean computationally
[5] CATCH-ALL               — everything else, free-form but guided
```

---

## Block 1 — Record Metadata

Administrative fields that identify the record and enable cross-center aggregation.

| Field | Type | Required | Description |
|---|---|---|---|
| `record_id` | string | Yes | Unique identifier. Format: `{CENTER}-{YYYYMMDD}-{SEQ}` e.g. `C2QA-20260415-001` |
| `center` | enum | Yes | One of: `C2QA`, `SQMS`, `Q-NEXT`, `QSA`, `QED-C` |
| `submitting_lab` | string | Yes | Institution and lab name |
| `submitter` | string | Yes | Name of responsible scientist |
| `date_measured` | date | Yes | ISO format: YYYY-MM-DD |
| `date_submitted` | date | Yes | ISO format: YYYY-MM-DD |
| `schema_version` | string | Yes | Version of this schema used e.g. `0.3` |
| `sample_id` | string | Yes | Center-internal sample identifier |
| `extraction_method` | enum | No | One of: `direct_submission`, `literature_ingestion`. Default: `direct_submission` |
| `source_doi` | string | No | DOI of source paper (for literature_ingestion records) |
| `source_reference` | string | No | Specific location in source paper e.g. "Table I row 3" |
| `human_reviewed` | boolean | No | For ingested records: whether a scientist has reviewed this record |
| `human_approved` | boolean | No | For ingested records: whether a scientist has approved this record for use |
| `exchange_sample` | boolean | No | True if this is a shared sample from another center |
| `origin_center` | enum | No | If exchange sample, which center provided it |
| `related_records` | list | No | Record IDs of related measurements on same sample |
| `notes` | string | No | Any administrative notes |

---

## Block 2 — Sample Description

Describes the material and fabrication context. Precise sample description is essential for results to be comparable across centers.

### 2.1 Substrate

| Field | Type | Required | Description |
|---|---|---|---|
| `substrate_material` | enum | Yes | One of: `silicon`, `sapphire`, `silicon_carbide`, `diamond`, `other` |
| `substrate_material_other` | string | If other | Specify material |
| `substrate_orientation` | string | No | Crystal orientation e.g. `(100)`, `(0001)`, `c-axis` |
| `substrate_resistivity` | float | No | Ohm·cm. For silicon: high resistivity (>10kΩ·cm) should be noted |
| `substrate_resistivity_units` | string | No | Always `Ohm·cm` |
| `substrate_supplier` | string | No | Commercial supplier or growth lab |
| `substrate_thickness_um` | float | No | Substrate thickness in microns |
| `substrate_surface_treatment` | string | No | e.g. `epi-polish`, `CMP`, `HF etch`, `none` |
| `substrate_cleaning_protocol` | string | No | Cleaning steps applied before deposition |

### 2.2 Superconducting Film

| Field | Type | Required | Description |
|---|---|---|---|
| `film_material` | enum | Yes | Standard chemical abbreviation: `Nb`, `NbTiN`, `NbN`, `Al`, `TiN`, `Ta`, `Re`, `other`. Use symbol, not spelled-out element name. |
| `film_material_other` | string | If other | Specify using chemical formula e.g. `Ta-Hf (83:17)`, `TaN` |
| `film_crystal_phase` | string | No | e.g. `alpha-Ta (bcc)`, `beta-Ta (tetragonal)`, `fcc`. Always use this field for crystal phase — never include phase in `film_material`. Particularly important for Ta films where phase strongly affects qubit performance. |
| `film_thickness_nm` | float | Yes | Film thickness in nanometers |
| `deposition_method` | enum | Yes | One of: `sputtering`, `evaporation`, `MBE`, `ALD`, `CVD`, `other` |
| `deposition_method_other` | string | If other | Specify method e.g. `UHV dc magnetron sputtering` |
| `deposition_temperature_C` | float | No | Substrate temperature during deposition in Celsius |
| `deposition_pressure_torr` | float | No | Chamber pressure during deposition |
| `deposition_gas` | string | No | e.g. `Ar`, `Ar/N2`, `N2` |
| `annealing_temperature_C` | float | No | Post-deposition anneal temperature in Celsius. Promoted from catchall in v0.2. |
| `annealing_duration_s` | float | No | Post-deposition anneal duration in seconds. Promoted from catchall in v0.2. |
| `annealing_protocol` | string | No | Full anneal conditions if not captured by temperature/duration fields |
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

---

## Block 3 — Structured Measurements

Defined measurement fields with known or approximate connections to device performance. Each field includes a `mapping_status` indicating confidence in the downstream connection.

**Mapping status values:**
- `well_known` — relationship to device performance is established in literature
- `approximate` — relationship is understood directionally but quantitative mapping has uncertainty
- `open_research` — connection to device performance is suspected but not yet established

---

### 3.1 Superconducting Properties

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `Tc_K` | float | Kelvin | `well_known` | Operating temperature margin; affects quasiparticle density |
| `Tc_uniformity_pct` | float | % std dev across wafer | `approximate` | Fabrication yield; qubit frequency uniformity |
| `RRR` | float | dimensionless | `well_known` | Film purity; correlates with quasiparticle loss. Note: RRR is dimensionless — if units are reported it is a different quantity. |
| `sheet_resistance_Ohm_sq` | float | Ohm/square | `well_known` | Kinetic inductance; qubit frequency |
| `London_penetration_depth_nm` | float | nm | `approximate` | Surface loss contribution |
| `upper_critical_field_T` | float | Tesla | `well_known` | Operating magnetic field margin |

### 3.2 Dielectric and Surface Loss

These are among the most important parameters for qubit coherence and are a primary focus of the working group.

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `loss_tangent_substrate` | float | dimensionless | `well_known` | T1 coherence time (dielectric loss contribution) |
| `loss_tangent_substrate_frequency_GHz` | float | GHz | — | Measurement frequency (required for context) |
| `loss_tangent_substrate_temperature_mK` | float | mK | — | Measurement temperature (required for context) |
| `loss_tangent_interface` | float | dimensionless | `approximate` | T1 coherence time (interface loss contribution) |
| `loss_tangent_interface_type` | enum | — | — | One of: `metal_substrate`, `metal_vacuum`, `substrate_vacuum` |
| `TLS_density_per_GHz_per_um2` | float | GHz⁻¹·μm⁻² | `well_known` | T2 dephasing; low-frequency noise; resonator quality factor |
| `TLS_coupling_strength_MHz` | float | MHz | `approximate` | Individual TLS-qubit interaction strength |
| `TLS_measurement_protocol` | string | — | — | Reference to protocol used |
| `surface_oxide_thickness_nm` | float | nm | `approximate` | TLS density; interface loss |
| `surface_oxide_composition` | string | — | `open_research` | TLS species identification |

### 3.3 Microwave Performance

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `Qi_internal_quality_factor` | float | dimensionless | `well_known` | Resonator loss; T1 coherence time. Note: Qi is the internal quality factor — do not confuse with Qc (coupling quality factor). |
| `Qi_measurement_power_dBm` | float | dBm | — | Single-photon regime should be noted |
| `Qi_measurement_frequency_GHz` | float | GHz | — | Required for context |
| `Qi_measurement_temperature_mK` | float | mK | — | Required for context |
| `Qi_single_photon` | float | dimensionless | `well_known` | Most relevant for qubit operating conditions |
| `Qc_coupling_quality_factor` | float | dimensionless | `well_known` | Resonator-qubit coupling design |
| `microwave_loss_mechanism` | string | — | `approximate` | Dominant loss attribution e.g. `TLS`, `quasiparticle`, `vortex_motion`, `radiation` |

### 3.4 Qubit Performance (if device-level measurement)

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `T1_us` | float | microseconds | `well_known` | Physical gate fidelity; error correction code distance. Note: T1 may be reported in ms in papers — always convert to µs. |
| `T1_std_us` | float | microseconds | `well_known` | Fabrication variability; yield modeling |
| `T2_echo_us` | float | microseconds | `well_known` | Dephasing; gate fidelity for longer sequences |
| `T2_ramsey_us` | float | microseconds | `well_known` | Low-frequency noise environment |
| `T1_measurement_protocol` | string | — | — | Reference to protocol used |
| `qubit_frequency_GHz` | float | GHz | `well_known` | Operating point; collision avoidance in multi-qubit systems |
| `qubit_frequency_std_GHz` | float | GHz | `approximate` | Frequency crowding in scaled systems |
| `anharmonicity_MHz` | float | MHz | `well_known` | Gate speed limit; leakage rate |
| `single_qubit_gate_fidelity_pct` | float | % | `well_known` | Error correction overhead (local gates) |
| `single_qubit_gate_time_ns` | float | ns | `well_known` | Circuit runtime; coherence budget |
| `two_qubit_gate_fidelity_pct` | float | % | `well_known` | Error correction overhead (dominant cost). A 0.4% improvement (99.5% → 99.9%) can reduce module count by 8x for representative circuits. |
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

### 3.6 Inter-Module / Interconnect Properties (Modular Architecture Specific)

These fields are specifically relevant to modular architectures and are a distinctive focus of C2QA's QREM effort.

| Field | Type | Units | Mapping Status | Downstream Device Parameter |
|---|---|---|---|---|
| `intermodule_link_type` | enum | — | — | One of: `microwave_photonic`, `optical_photonic`, `direct_wire`, `other` |
| `intermodule_link_fidelity_pct` | float | % | `well_known` | Inter-module gate error correction overhead |
| `intermodule_entanglement_rate_Hz` | float | Hz | `well_known` | Inter-module communication throughput; circuit runtime |
| `intermodule_link_latency_us` | float | microseconds | `well_known` | QEC syndrome propagation delay across modules |
| `transduction_efficiency_pct` | float | % | `well_known` | Microwave-to-optical conversion loss |
| `transduction_added_noise_quanta` | float | quanta | `approximate` | Noise added by transduction process |
| `intermodule_entanglement_fidelity_pct` | float | % | `well_known` | Raw Bell pair quality before purification |
| `purification_overhead_ratio` | float | dimensionless | `approximate` | Raw pairs needed per high-fidelity pair |

---

## Block 4 — Device Performance Implications

This block is the computational bridge — it translates structured measurements into device-level parameters that feed directly into the QREM resource estimation tool.

**This block may be partially auto-populated by the QREM tool from Block 3 inputs.**

### Connection to QREM Hardware Profiles

| Block 4 Field | QREM Hardware Profile Parameter |
|---|---|
| `implied_T1_from_loss_tangent_us` | `coherence.T1_us` |
| `implied_code_distance` | Used in error correction layer |
| `implied_physical_per_logical_qubit` | Physical qubit overhead calculation |
| `implied_module_count_benchmark` | Module count estimate |
| `intermodule_link_fidelity_pct` (Block 3) | `intermodule.link_fidelity_pct` |
| `transduction_efficiency_pct` (Block 3) | `intermodule.transduction_efficiency_pct` |

| Field | Type | Units | Source | Description |
|---|---|---|---|---|
| `implied_T1_from_loss_tangent_us` | float | microseconds | computed | Estimated T1 from dielectric loss tangent. Formula: T1 ≈ Q_TLS / (2π·f). Applicable only where TLS is dominant loss mechanism. |
| `implied_T1_uncertainty_us` | float | microseconds | computed | Uncertainty bound on implied T1 |
| `implied_code_distance` | integer | dimensionless | computed | Minimum surface code distance d to achieve 10⁻⁶ logical error rate given measured gate fidelities. Null if gate fidelity not measured. |
| `implied_physical_per_logical_qubit` | integer | dimensionless | computed | Physical qubit overhead = 2d²-1. Null if code distance not computable. Formula uses 2d²-1 (not d²) to account for syndrome measurement ancilla qubits. |
| `implied_module_count_benchmark` | integer | dimensionless | computed | Estimated modules needed for a standard benchmark circuit. Enables direct cross-center comparison. |
| `coherence_budget_breakdown` | dict | % | computed | Fractional attribution of T1 loss to: `TLS_substrate`, `TLS_interface`, `quasiparticle`, `vortex_motion`, `radiation`, `unknown` |
| `mapping_confidence` | enum | — | human | Overall confidence in Block 4 values: `high`, `medium`, `low`, `not_computable` |
| `mapping_notes` | string | — | human | Explanation of any assumptions made in computing implied values |

---

## Block 5 — Catch-All (Mandatory)

This block captures everything that doesn't fit the structured fields above. It is **mandatory** — every record must include at least a note in this block.

The catch-all serves two purposes: it captures scientific knowledge that hasn't been formalized into schema fields, and it is the primary data source for the AI review process that drives schema evolution. It is also the primary source for mining author-stated materials-to-device connections for the QREM mapping layer.

### Guidance for Populating the Catch-All

**Additional measurements:** Include any measurement that has no schema field. The `suspected_relevance` entry must be specific — cite known physics, not generic statements. Use the domain knowledge connections listed below.

**Anomalous observations:** Only include results the authors flag as unexpected, or that clearly deviate from standard behavior. Label whether the hypothesis is from the authors or your own assessment.

**Correlations observed:** Only include correlations the authors themselves stated or clearly implied. Do not infer correlations from data — you are recording author claims, not performing your own analysis.

**Schema promotion candidates:** Flag parameters that appear important but have no schema field. Explain specifically what would be lost if we didn't track it.

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
  xi < l (clean limit) → vortex motion is primary loss channel
  xi > l (dirty limit) → different loss mechanisms dominate
  Vortex activation temperature → characterizes vortex motion loss channel

Microwave and device performance:
  Qi → resonator loss → directly sets T1 upper bound
  Loss tangent → dielectric contribution to T1
  T1 → gate fidelity → error correction code distance → module count
  Two-qubit gate fidelity: 99.5% → ~16 modules; 99.9% → ~2 modules
```

### 5.1 Additional Measurements

```
additional_measurements:
  - description: "..."
    value: ...
    units: "..."
    measurement_conditions: "..."
    suspected_relevance: "<specific physics connection, not generic statement>"
```

### 5.2 Anomalous Observations

```
anomalous_observations:
  - description: "..."
    conditions: "..."
    hypothesis: "Author hypothesis: ... / Assessment (not stated by authors): ..."
```

### 5.3 Fabrication Notes

```
fabrication_notes: "..."
```

### 5.4 Correlations Observed

```
correlations_observed:
  - description: "..."
    measurement_a: "..."
    measurement_b: "..."
    nature: "..."
```

### 5.5 Free Notes

```
free_notes: "..."
```

---

## AI Review Process

The catch-all corpus across all centers will be reviewed periodically using AI-assisted pattern analysis:

- Fields appearing repeatedly → candidates for promotion to structured fields
- Correlations between catch-all and structured fields → candidates for QREM mapping relationships
- Anomalous observations at multiple centers → systematic effects worth investigating
- Fabrication parameters correlating with performance variation → Block 2 addition candidates
- Author-stated materials-to-device connections → evidence base for QREM mapping layer

**Review cadence:** Proposed quarterly, aligned with working group meetings.

**Output:** Schema evolution proposal document. Working group approves or defers each candidate.

---

## Schema Governance

| Role | Responsibility |
|---|---|
| Working group co-leads | Approve schema version changes |
| C2QA QREM team | Maintain AI review process; propose schema evolution candidates; maintain publications ingester |
| Each center | Submit records; populate catch-all diligently |
| All centers jointly | Approve or defer AI-identified schema evolution proposals |

**Schema versioning:** Semantic versioning (major.minor). Minor versions add optional fields. Major versions change required fields or field semantics and require migration of existing records.

**Changes in v0.3:**
- Updated Implementation Status section to reflect corpus at scale (62 papers)
- Added `display_name` concept for cross-paper sample identification
- Added material name standardization section — abbreviations enforced at extraction time
- Updated candidate schema promotion fields based on larger corpus
- Added `upper_critical_field_T`, `normal_resistivity`, and `viscous_drag_coefficient` as new candidates
- Added domain knowledge connections to Block 5 guidance
- Added extraction error warnings to Block 3 field descriptions (RRR units, T1 unit conversion, Qi vs Qc)
- Updated Block 4 QREM connection table

---

*End of Schema Document v0.3*
*Original document produced April 2026. Updated April 23, 2026.*
*Proposed for discussion at Five-Center Materials Working Group*
*Contact: C2QA QREM Team*
