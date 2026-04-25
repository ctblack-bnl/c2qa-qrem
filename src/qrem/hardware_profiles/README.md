# Hardware Profiles

Modular profile system for the QREM pipeline. Each aspect of the hardware is
a separate YAML file that can be mixed and matched independently.

## Directory Structure

```
hardware_profiles/
  qubits/               — Qubit coherence and gate performance
  interconnects/        — Inter-module link properties
  modules/              — Module architecture and capacity
  error_correction/     — QEC code and target logical error rate
```

## How to Use

The QREM estimator loads one profile from each directory and merges them.
In the UI, each directory corresponds to a dropdown selector.

```python
profile = load_profile(
    qubits='transmon_baseline_2026',
    interconnect='microwave_photonic_85pct',
    module='module_1000q_nearest_neighbor',
    error_correction='surface_code_1e6'
)
```

## Generating Qubit Profiles from the Materials Database

The Hardware Profile Updater (planned) reads a single sample record from the
materials database and generates a new file in `qubits/`. Measured fields are
used directly; unmeasured fields fall back to documented defaults. The
`provenance` block in each qubit profile records which fields came from the
corpus vs which were assumed.

## Profile Files

### qubits/
| File | Description |
|---|---|
| `transmon_baseline_2026.yaml` | Hand-tuned baseline, current state-of-the-art |

### interconnects/
| File | Description |
|---|---|
| `microwave_photonic_85pct.yaml` | Conservative baseline — current demonstrated |
| `microwave_photonic_92pct.yaml` | Near-term target — optimistic 2-3 year horizon |
| `microwave_photonic_99pct.yaml` | Aspirational — upper bound for sensitivity analysis |

### modules/
| File | Description |
|---|---|
| `module_1000q_nearest_neighbor.yaml` | 1000-qubit chip, nearest-neighbor grid |

### error_correction/
| File | Description |
|---|---|
| `surface_code_1e6.yaml` | Surface code, 10⁻⁶ logical error rate target |

## Adding New Profiles

- **New qubit material:** generate via Hardware Profile Updater, or copy
  `transmon_baseline_2026.yaml` and edit. Populate the `provenance` block.
- **New interconnect:** copy the nearest tier and adjust values.
- **New platform (neutral atom):** add files to each directory with
  `platform: neutral_atom` tag.

## Known Limitations

- SWAP routing overhead not yet modeled — physical qubit counts are lower bounds
- Magic state factory model is simplified
- Inter-module gates use same code distance as local gates (conservative)
- Neutral atom profiles not yet implemented
