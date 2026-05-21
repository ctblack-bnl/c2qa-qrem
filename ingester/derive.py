# ingester/derive.py
# Computes derived quantities from extracted schema fields.
# Called by build_sqlite.py after loading each sample record.
#
# Design principles:
#   - Pure Python arithmetic — no API calls, no uncertainty
#   - Never derive a quantity the paper already reports
#   - Sanity check every result — flag physically unreasonable values
#   - Every derived value carries full provenance (formula, inputs used)
#   - Adding a new derivation = adding one function + one line in derive_all()
#
# Derived quantities appear in the SQLite samples table with a derived_ prefix.
# They never appear in the JSONL — the JSONL is the pure extracted record.

import re
import math
from typing import Optional


# ── Physical constants ─────────────────────────────────────────────────────
kB_eV   = 8.617333e-5   # Boltzmann constant in eV/K
kB_meV  = kB_eV * 1000  # Boltzmann constant in meV/K
hbar_eV = 6.582119e-16  # hbar in eV·s
mu0     = 1.2566e-6     # permeability of free space (H/m)


# ── Sanity bounds ──────────────────────────────────────────────────────────
# Physically reasonable ranges for derived quantities.
# Values outside these bounds are flagged rather than silently used.
SANITY_BOUNDS = {
    'derived_resistivity_uOhm_cm':      (0.05,  500.0),   # µΩ·cm — typical SC films
    'derived_BCS_gap_meV':              (0.01,    3.0),   # meV — conventional SCs
    'derived_coherence_length_nm':      (1.0,  10000.0),  # nm
    'derived_kinetic_inductance_pH_sq': (0.01,  1000.0),  # pH/□
}


# ── Value extraction helper ────────────────────────────────────────────────

def get_value(sample: dict, field: str) -> Optional[float]:
    """
    Safely extract a numeric value from a sample's extracted field.
    Handles both dict format {"value": "4.33", ...} and raw values.
    Strips units, uncertainty notation, and other non-numeric text.
    Returns float or None.
    """
    field_data = sample.get(field)
    if field_data is None:
        return None

    # Handle nested dict format from extraction
    if isinstance(field_data, dict):
        raw = field_data.get('value')
    else:
        raw = field_data

    if raw is None:
        return None

    # Try direct conversion first
    try:
        return float(raw)
    except (ValueError, TypeError):
        pass

    # Strip common extras: "142.3 ± 5", "~140", "4.33 K", "1.2e6", etc.
    match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', str(raw))
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass

    return None


def is_already_reported(sample: dict, field: str) -> bool:
    """
    Check if a field is already reported in the extracted data.
    If so, we should not derive it — the reported value takes priority.
    """
    val = get_value(sample, field)
    return val is not None


def make_derived(value: float, field: str,
                 derived_from: list, formula: str,
                 note: str = None) -> Optional[dict]:
    """
    Create a derived quantity entry with full provenance.
    Returns None if the value fails sanity checks.
    """
    # Sanity check
    bounds = SANITY_BOUNDS.get(field)
    if bounds:
        lo, hi = bounds
        if not (lo <= value <= hi):
            return {
                'value': None,
                'confidence': 'derived',
                'derived_from': derived_from,
                'formula': formula,
                'note': f"SANITY FAIL: computed {value:.4g} outside expected range [{lo}, {hi}]. Check input units.",
            }

    return {
        'value': round(value, 6),
        'confidence': 'derived',
        'derived_from': derived_from,
        'formula': formula,
        'note': note,
    }


# ── Individual derivation functions ───────────────────────────────────────

def _derive_resistivity(sample: dict) -> dict:
    """
    Normal state resistivity from sheet resistance and film thickness.
    ρ (µΩ·cm) = Rs (Ω/□) × t (nm) × 0.1

    Factor: 1 Ω/□ × 1 nm = 1e-9 Ω·m = 0.1 µΩ·cm
    Requires: sheet_resistance_Ohm_sq AND film_thickness_nm
    Skip if: paper already reports resistivity
    """
    # Don't derive if already reported
    # (check common field names the ingester might use)
    if is_already_reported(sample, 'normal_resistivity_uOhm_cm'):
        return {}

    Rs = get_value(sample, 'sheet_resistance_Ohm_sq')
    t  = get_value(sample, 'film_thickness_nm')

    if Rs is None or t is None:
        return {}

    value = Rs * t * 0.1

    entry = make_derived(
        value=value,
        field='derived_resistivity_uOhm_cm',
        derived_from=['sheet_resistance_Ohm_sq', 'film_thickness_nm'],
        formula='ρ = Rs × t × 0.1  [Ω/□ × nm → µΩ·cm]',
    )
    return {'derived_resistivity_uOhm_cm': entry} if entry else {}


def _derive_bcs_gap(sample: dict) -> dict:
    """
    BCS superconducting gap energy from Tc.
    Δ (meV) = 1.764 × kB × Tc

    Valid for conventional BCS superconductors (Nb, Ta, Al, NbN, TiN).
    Not valid for high-Tc or unconventional superconductors.
    Requires: Tc_K
    Skip if: paper already reports gap energy
    """
    Tc = get_value(sample, 'Tc_K')
    if Tc is None:
        return {}

    value = 1.764 * kB_meV * Tc

    entry = make_derived(
        value=value,
        field='derived_BCS_gap_meV',
        derived_from=['Tc_K'],
        formula='Δ = 1.764 × kB × Tc  [BCS weak coupling]',
        note='Valid for conventional BCS superconductors only',
    )
    return {'derived_BCS_gap_meV': entry} if entry else {}


def _derive_coherence_length(sample: dict) -> dict:
    """
    Superconducting coherence length from upper critical field.
    ξ (nm) = sqrt(Φ0 / (2π × Hc2))
    where Φ0 = 2.068e-15 Wb (flux quantum)

    Requires: upper_critical_field_T
    Skip if: paper already reports coherence length
    """
    # Check catchall for already-reported coherence length
    # (it's currently a catchall field, not a structured field)
    Hc2 = get_value(sample, 'upper_critical_field_T')
    if Hc2 is None:
        return {}

    if Hc2 <= 0:
        return {}

    Phi0 = 2.068e-15  # Weber (flux quantum)
    xi_m = math.sqrt(Phi0 / (2 * math.pi * Hc2))
    xi_nm = xi_m * 1e9  # convert to nm

    entry = make_derived(
        value=xi_nm,
        field='derived_coherence_length_nm',
        derived_from=['upper_critical_field_T'],
        formula='ξ = sqrt(Φ0 / (2π × Hc2))  [Φ0 = 2.068×10⁻¹⁵ Wb]',
    )
    return {'derived_coherence_length_nm': entry} if entry else {}


def _derive_kinetic_inductance(sample: dict, Rs_override: Optional[float] = None) -> dict:
    """
    Kinetic inductance per square from sheet resistance and Tc.
    Lk (pH/□) = (hbar × Rs) / (π × Δ)
               = (hbar × Rs) / (π × 1.764 × kB × Tc)

    Relevant for resonator and qubit design — affects qubit frequency.
    Requires: sheet_resistance_Ohm_sq (or derived) AND Tc_K

    Rs_override: pre-computed sheet resistance from upstream derivation
                 (used when Rs not directly reported but derivable from
                  resistivity+thickness or R vs T geometry). The reported
                 value always takes priority.
    """
    Rs = get_value(sample, 'sheet_resistance_Ohm_sq')
    if Rs is None:
        Rs = Rs_override  # fall back to upstream-derived value
    Tc = get_value(sample, 'Tc_K')

    if Rs is None or Tc is None:
        return {}

    Delta_J = 1.764 * kB_eV * Tc * 1.602e-19  # gap in Joules
    hbar_J  = hbar_eV * 1.602e-19              # hbar in J·s

    Lk_H  = hbar_J * Rs / (math.pi * Delta_J)
    Lk_pH = Lk_H * 1e12  # convert to pH

    entry = make_derived(
        value=Lk_pH,
        field='derived_kinetic_inductance_pH_sq',
        derived_from=['sheet_resistance_Ohm_sq', 'Tc_K'],
        formula='Lk = ℏ × Rs / (π × Δ)  [Δ = 1.764 kB Tc]',
        note='Useful for resonator and qubit frequency estimation',
    )
    return {'derived_kinetic_inductance_pH_sq': entry} if entry else {}


def _derive_RRR_from_RvT(sample: dict) -> dict:
    """
    RRR from R vs T curve if not directly reported.
    RRR = R(300K) / R(Tc+)
    Requires: room_temperature_resistance_Ohm AND normal_state_resistance_Ohm
    Skip if: RRR already reported
    """
    if is_already_reported(sample, 'RRR'):
        return {}

    R300 = get_value(sample, 'room_temperature_resistance_Ohm')
    Rn   = get_value(sample, 'normal_state_resistance_Ohm')

    if R300 is None or Rn is None or Rn == 0:
        return {}

    value = R300 / Rn

    # Sanity check — RRR should be > 1 and typically < 1000 for SC films
    if not (1.0 <= value <= 1000.0):
        return {
            'derived_RRR_from_RvT': {
                'value': None,
                'confidence': 'derived',
                'derived_from': ['room_temperature_resistance_Ohm', 'normal_state_resistance_Ohm'],
                'formula': 'RRR = R(300K) / R(Tc+)',
                'note': f'SANITY FAIL: computed RRR={value:.2f} outside expected range [1, 1000]',
            }
        }

    entry = make_derived(
        value=value,
        field='derived_RRR_from_RvT',
        derived_from=['room_temperature_resistance_Ohm', 'normal_state_resistance_Ohm'],
        formula='RRR = R(300K) / R(Tc+)',
        note='Derived from R vs T curve — use reported RRR if available',
    )
    return {'derived_RRR_from_RvT': entry} if entry else {}


def _derive_sheet_resistance_from_RvT(sample: dict) -> dict:
    """
    Sheet resistance from normal state resistance and device geometry.
    Rs = Rn × (width / length)  [Ω/□]
    Requires: normal_state_resistance_Ohm AND measured_structure_width_um
              AND measured_structure_length_um
    Skip if: sheet_resistance_Ohm_sq already reported
    """
    if is_already_reported(sample, 'sheet_resistance_Ohm_sq'):
        return {}

    Rn = get_value(sample, 'normal_state_resistance_Ohm')
    w  = get_value(sample, 'measured_structure_width_um')
    L  = get_value(sample, 'measured_structure_length_um')

    if Rn is None or w is None or L is None or L == 0:
        return {}

    Rs = Rn * (w / L)

    entry = make_derived(
        value=Rs,
        field='derived_sheet_resistance_Ohm_sq',
        derived_from=['normal_state_resistance_Ohm',
                      'measured_structure_width_um',
                      'measured_structure_length_um'],
        formula='Rs = Rn × (width / length)  [Ω/□]',
        note='Derived from R vs T curve and device geometry',
    )
    return {'derived_sheet_resistance_Ohm_sq': entry} if entry else {}


def _derive_sheet_resistance_from_resistivity(sample: dict) -> dict:
    """
    Sheet resistance from normal-state resistivity and film thickness.
    Rs (Ω/□) = ρ (µΩ·cm) / t (nm) × 10

    Unit derivation:
        1 µΩ·cm = 1e-8 Ω·m
        1 nm    = 1e-9 m
        Rs = ρ/t = (1e-8 Ω·m) / (1e-9 m) × (ρ_num / t_num)
           = 10 × (ρ_num / t_num)  [Ω/□]

    Sanity: Ta at ρ≈180 µΩ·cm, t=200nm → Rs = 9 Ω/□ (within 5–20 Ω/□ for β-Ta)

    Requires: normal_state_resistivity_uOhm_cm AND film_thickness_nm
    Skip if: sheet_resistance_Ohm_sq already reported (measured > derived)
             OR derived_sheet_resistance_Ohm_sq already computed from R vs T geometry
    """
    if is_already_reported(sample, 'sheet_resistance_Ohm_sq'):
        return {}

    rho = get_value(sample, 'normal_state_resistivity_uOhm_cm')
    t   = get_value(sample, 'film_thickness_nm')

    if rho is None or t is None or t <= 0:
        return {}

    Rs = rho / t * 10.0

    entry = make_derived(
        value=Rs,
        field='derived_sheet_resistance_Ohm_sq',
        derived_from=['normal_state_resistivity_uOhm_cm', 'film_thickness_nm'],
        formula='Rs = ρ / t × 10  [µΩ·cm / nm → Ω/□]',
        note='ρ/t: 1 µΩ·cm / 1 nm = 1e-8/1e-9 Ω/□ = 10 Ω/□',
    )
    return {'derived_sheet_resistance_Ohm_sq': entry} if entry else {}


# ── Main entry point ───────────────────────────────────────────────────────

def derive_all(sample: dict) -> dict:
    """
    Compute all applicable derived quantities for a sample.

    Args:
        sample: the sample dict from extraction_json

    Returns:
        dict of derived quantity name → {value, confidence, derived_from, formula, note}
        Empty dict if nothing can be derived.

    Ordering matters for cascades:
        Sheet resistance must be derived before kinetic inductance,
        since Lk = f(Rs, Tc) and Rs may itself be derived.

    Priority for derived_sheet_resistance_Ohm_sq:
        1. R vs T geometry  (direct measurement + geometry)
        2. ρ + thickness    (reported resistivity + film thickness)
        (Reported sheet_resistance_Ohm_sq always wins over both — checked inside each function.)

    To add a new derived quantity:
        1. Write a _derive_xxx() function following the pattern above
        2. Add one line here: derived.update(_derive_xxx(sample))
        3. If the new quantity feeds a downstream derivation, pass it explicitly
           (see Rs_override pattern for kinetic inductance below)
    """
    derived = {}

    # ── Resistivity (from geometry) ──────────────────────────────────────
    derived.update(_derive_resistivity(sample))

    # ── Sheet resistance ─────────────────────────────────────────────────
    # Priority 1: R vs T geometry (Rn + width + length)
    derived.update(_derive_sheet_resistance_from_RvT(sample))

    # Priority 2: ρ + thickness — only if not already computed above
    # (Both functions skip if sheet_resistance_Ohm_sq is reported;
    #  additionally skip the ρ path if R vs T path already succeeded.)
    if 'derived_sheet_resistance_Ohm_sq' not in derived:
        derived.update(_derive_sheet_resistance_from_resistivity(sample))

    # ── Kinetic inductance — pass derived Rs for cascade ─────────────────
    # If neither reported Rs nor upstream derivation is available, Rs_override is None
    # and the function returns {} gracefully.
    Rs_derived = get_derived_value(derived, 'derived_sheet_resistance_Ohm_sq')
    derived.update(_derive_kinetic_inductance(sample, Rs_override=Rs_derived))

    # ── Remaining derivations (order-independent) ─────────────────────────
    derived.update(_derive_bcs_gap(sample))
    derived.update(_derive_coherence_length(sample))
    derived.update(_derive_RRR_from_RvT(sample))

    return derived


def get_derived_value(derived: dict, field: str) -> Optional[float]:
    """
    Safely extract the numeric value from a derived quantities dict.
    Returns float or None (including if sanity check failed).
    """
    entry = derived.get(field)
    if not entry:
        return None
    val = entry.get('value')
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
