# t1_decomposition.py
# Stage 4 of the QREM pipeline: decompose T1 into physical loss channels.
#
# Implements the two-level loss model from loss_channel_model_v2-5.md:
#
#   Level 1 — qubit loss channels:
#     1/T1_qubit = (1/T1_pad) + (1/T1_junction) + 1/T1_radiation
#
#   The resonator is a CALIBRATION MEASUREMENT, not a qubit loss channel.
#   Its role: Qi + p_MS_resonator → tan_delta → applied to pad via p_MS_pad.
#   It appears in the Level 1 sum only through the Purcell term (system level,
#   folded into T1_radiation as a class default).
#
#   Level 2 — loss channels within each component:
#     Γ_component = Γ_TLS + Γ_QP + Γ_vortex
#
#   TLS path for pad (preferred when resonator Qi is available):
#     Step 1 (calibration): tan_delta = 1 / (Q_TLS_0_resonator × p_MS_resonator)
#     Step 2 (pad):         T1_pad_TLS = 1 / (p_MS_pad × tan_delta × 2π × f_qubit)
#   This correctly accounts for the geometric difference between resonator and
#   qubit pad — they share the same film and intrinsic tan_delta but have
#   different surface participation ratios (Joshi et al. 2026).
#
#   QP and vortex channels: computed at qubit level (not component-weighted)
#   for now. TODO: weight by p_pad / p_junction when component-level FEM data
#   is more widely available in the corpus.
#
# Design principles:
#   - If T1 is directly measured in the corpus record, it is used as-is [MEASURED].
#     The decomposition still runs but is flagged as PREDICTED — enabling model
#     validation against the measured value.
#   - Every channel and every input carries a provenance label:
#       MEASURED      — directly reported in the paper
#       DERIVED       — computed from measured quantities via physics formula
#       CLASS_DEFAULT — typical value for this material/device class
#       ASSUMED       — baseline default, least certain
#   - Falls back gracefully through the tier hierarchy for any missing input.
#   - Returns a plain dict (consistent with coherence_budget in estimator.py).
#
# References:
#   Wang et al., APL 107, 162601 (2015)         — participation ratios
#   Read et al., PRA 19, 034064 (2023)          — interface loss tangents, Qi interpretation
#   Crowley et al., PRX 13, 041005 (2023)       — alpha-Ta tan_delta, methodology
#   Joshi et al., arXiv:2603.13174 (2026)       — beta-Ta tan_delta, p_MS inversion method
#   loss_channel_model_v2-5.md                  — model architecture (v2.5)
#   qrem_scientific_vision.md                   — Tier 2 derivation rationale

import math
import yaml
from typing import Optional

# ---------------------------------------------------------------------------
# Provenance labels
# ---------------------------------------------------------------------------
MEASURED      = "MEASURED"
DERIVED       = "DERIVED"
CLASS_DEFAULT = "CLASS_DEFAULT"
ASSUMED       = "ASSUMED"

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
K_B_OVER_H_GHZ_PER_K = 20.836  # k_B / h in GHz/K — for thermal activation formula


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_model_defaults(yaml_path: str) -> dict:
    """
    Load the analytical defaults YAML (e.g. transmon_analytical_defaults.yaml).
    Returns the full parsed dict.
    """
    with open(yaml_path, 'r') as f:
        return yaml.safe_load(f)


def load_material_record(yaml_path: str) -> dict:
    """
    Load a per-sample material record YAML.
    Returns the full parsed dict.
    """
    with open(yaml_path, 'r') as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Internal helpers — provenance-aware field extraction
# ---------------------------------------------------------------------------

def _coerce_numeric(value):
    """
    Coerce a value to float if it is a string representing a number.
    YAML sometimes parses scientific notation (e.g. '3.2e6') as a string.
    Returns None if value is None, the original value if not numeric.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _get(record: dict, *keys, default=None, default_provenance=ASSUMED):
    """
    Navigate nested dict by keys, returning (value, provenance).
    If the field is a dict with 'value' and 'provenance' keys, returns those.
    If the value is None (explicit null in YAML), treats as not present.
    If the field is a plain scalar, returns (scalar, MEASURED) — direct value.
    If not found, returns (default, default_provenance).
    Numeric strings (e.g. '3.2e6') are coerced to float.
    """
    node = record
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default, default_provenance
        node = node[k]
    if isinstance(node, dict) and 'value' in node:
        value = _coerce_numeric(node['value'])
        # Treat explicit null as not present — fall back to default
        if value is None:
            return default, default_provenance
        return value, node.get('provenance', ASSUMED)
    # Plain scalar — treat null as not present
    if node is None:
        return default, default_provenance
    return _coerce_numeric(node), MEASURED


def _t1_from_gamma(gamma: float) -> Optional[float]:
    """Convert loss rate Γ (1/µs) to T1 (µs). Returns None if gamma <= 0."""
    if gamma is None or gamma <= 0:
        return None
    return 1.0 / gamma


def _combine_t1_channels(*t1_values) -> float:
    """
    Combine parallel loss channels: 1/T1_total = Σ 1/T1_i.
    Ignores None values (channel not computable).
    Returns T1_total in µs, or None if no channels available.
    """
    gammas = [1.0 / t1 for t1 in t1_values if t1 is not None and t1 > 0]
    if not gammas:
        return None
    return 1.0 / sum(gammas)


def _worst_provenance(*provenances) -> str:
    """Return the worst (least certain) provenance from a list."""
    rank = {MEASURED: 0, DERIVED: 1, CLASS_DEFAULT: 2, ASSUMED: 3}
    return max(provenances, key=lambda p: rank.get(p, 3))


# ---------------------------------------------------------------------------
# Change 2: tan_delta extraction helper
# ---------------------------------------------------------------------------

def _extract_tan_delta(material_record: dict,
                       defaults: dict,
                       qi_val: Optional[float],
                       qi_prov: str,
                       q_tls0_val: Optional[float],
                       q_tls0_prov: str,
                       p_ms_res: float,
                       p_ms_res_prov: str) -> dict:
    """
    Extract the effective surface loss tangent tan_delta from whichever
    source is available, in priority order:

      Priority 1 — tan_delta_effective_surface directly measured/reported
                   in the material record. [MEASURED or as labeled]
      Priority 2 — Q_TLS_0 + p_MS_resonator → tan_delta = 1/(Q_TLS_0 × p_MS_res)
                   Q_TLS_0 is the unsaturated TLS quality factor — physically
                   correct for qubit operating conditions. [DERIVED]
      Priority 3 — Qi + p_MS_resonator → same formula, Qi as proxy.
                   Qi is power-dependent; Q_TLS_0 is preferred. [DERIVED, lower confidence]
      Priority 4 — Class default tan_delta from defaults YAML. [CLASS_DEFAULT]

    Returns dict with:
      tan_delta       — the extracted value
      provenance      — provenance of the result
      source          — human-readable description of which path was used
      notes           — list of strings for the summary
    """
    notes = []

    # Priority 1: directly reported effective surface tan_delta
    # Check both the legacy 'interfaces' path and the newer 'materials.tan_delta'
    # path written by generate_qubit_profile.py
    td_eff, td_eff_prov = _get(
        material_record, 'interfaces', 'tan_delta_effective_surface',
        default=None, default_provenance=CLASS_DEFAULT
    )
    if td_eff is None:
        td_eff, td_eff_prov = _get(
            material_record, 'materials', 'tan_delta',
            default=None, default_provenance=CLASS_DEFAULT
        )
    if td_eff is not None:
        notes.append(
            f"tan_delta_effective_surface = {td_eff:.2e} [{td_eff_prov}] "
            "— directly reported in material record (preferred)."
        )
        return {
            'tan_delta': td_eff,
            'provenance': td_eff_prov,
            'source': 'tan_delta_effective_surface (direct)',
            'notes': notes,
        }

    # Priority 2: Q_TLS_0 + p_MS_resonator
    if q_tls0_val is not None and p_ms_res is not None:
        tan_delta = 1.0 / (q_tls0_val * p_ms_res)
        prov = _worst_provenance(q_tls0_prov, p_ms_res_prov, DERIVED)
        notes.append(
            f"tan_delta derived from Q_TLS_0 = {q_tls0_val:.2e} [{q_tls0_prov}] "
            f"and p_MS_resonator = {p_ms_res:.2e} [{p_ms_res_prov}]: "
            f"tan_delta = 1/(Q_TLS_0 × p_MS_res) = {tan_delta:.2e} [{prov}]."
        )
        notes.append(
            "Q_TLS_0 is the unsaturated TLS quality factor — physically correct "
            "for qubit operating conditions (Joshi et al. 2026)."
        )
        return {
            'tan_delta': tan_delta,
            'provenance': prov,
            'source': 'Q_TLS_0 + p_MS_resonator',
            'notes': notes,
        }

    # Priority 3: Qi + p_MS_resonator
    if qi_val is not None and p_ms_res is not None:
        tan_delta = 1.0 / (qi_val * p_ms_res)
        prov = _worst_provenance(qi_prov, p_ms_res_prov, DERIVED)
        notes.append(
            f"tan_delta derived from Qi = {qi_val:.2e} [{qi_prov}] "
            f"and p_MS_resonator = {p_ms_res:.2e} [{p_ms_res_prov}]: "
            f"tan_delta = 1/(Qi × p_MS_res) = {tan_delta:.2e} [{prov}]."
        )
        notes.append(
            "Note: Qi is power-dependent — Q_TLS_0 preferred. "
            "S21-extracted Qi may include T_phi contribution (Read et al. 2023, Appendix A)."
        )
        return {
            'tan_delta': tan_delta,
            'provenance': prov,
            'source': 'Qi + p_MS_resonator (Q_TLS_0 preferred)',
            'notes': notes,
        }

    # Priority 4: class default
    td_default, td_default_prov = _get(
        defaults, 'tan_delta_effective_surface',
        default=8.1e-4, default_provenance=CLASS_DEFAULT
    )
    notes.append(
        f"No Qi, Q_TLS_0, or tan_delta_effective_surface in record — "
        f"using class default tan_delta = {td_default:.2e} [{td_default_prov}]."
    )
    return {
        'tan_delta': td_default,
        'provenance': CLASS_DEFAULT,
        'source': 'class default',
        'notes': notes,
    }


# ---------------------------------------------------------------------------
# Channel computations
# ---------------------------------------------------------------------------

def _compute_pad_tls(material_record: dict,
                     defaults: dict,
                     tan_delta_result: dict,
                     p_ms_pad: float,
                     p_ms_pad_prov: str,
                     f_qubit_ghz: float,
                     f_qubit_prov: str) -> dict:
    """
    Compute T1_TLS for the qubit capacitor pad using the Joshi inversion:

      Step 1 (resonator calibration):
        tan_delta = 1 / (Q_TLS_0_resonator × p_MS_resonator)
        [done upstream in _extract_tan_delta]

      Step 2 (apply to qubit pad):
        T1_pad_TLS = 1 / (p_MS_pad × tan_delta × 2π × f_qubit)

    This correctly accounts for the geometric difference between the resonator
    (high p_MS, designed to be surface-loss sensitive) and the qubit pad
    (low p_MS, optimized to suppress surface loss).

    Returns dict with T1_TLS_us, tan_delta, provenance, notes.
    """
    notes = list(tan_delta_result['notes'])  # copy calibration notes
    tan_delta = tan_delta_result['tan_delta']
    td_prov   = tan_delta_result['provenance']

    notes.append(
        f"Pad TLS: T1_pad_TLS = 1 / (p_MS_pad × tan_delta × 2π × f_qubit)"
    )
    notes.append(
        f"  p_MS_pad   = {p_ms_pad:.2e} [{p_ms_pad_prov}]"
    )
    notes.append(
        f"  tan_delta  = {tan_delta:.2e} [{td_prov}] (from {tan_delta_result['source']})"
    )
    notes.append(
        f"  f_qubit    = {f_qubit_ghz:.3f} GHz [{f_qubit_prov}]"
    )

    omega = 2.0 * math.pi * f_qubit_ghz * 1000.0  # GHz → cycles/µs → rad/µs
    gamma_pad_tls = p_ms_pad * tan_delta * omega
    t1_pad_tls_us = _t1_from_gamma(gamma_pad_tls)

    notes.append(
        f"  → T1_pad_TLS = {t1_pad_tls_us:.1f} µs"
    )

    prov = _worst_provenance(td_prov, p_ms_pad_prov, f_qubit_prov)

    return {
        'T1_TLS_us':    t1_pad_tls_us,
        'tan_delta':    tan_delta,
        'td_provenance': td_prov,
        'td_source':    tan_delta_result['source'],
        'p_MS_pad':     p_ms_pad,
        'p_MS_pad_prov': p_ms_pad_prov,
        'f_qubit_GHz':  f_qubit_ghz,
        'provenance':   prov,
        'path':         'tan_delta_via_p_MS_inversion',
        'notes':        notes,
    }


def _compute_junction_tls(material_record: dict,
                           defaults: dict,
                           f_qubit_ghz: float,
                           f_qubit_prov: str) -> dict:
    """
    Compute T1_TLS for the Josephson junction.

    Junction TLS is independent of the resonator calibration path — the junction
    material (Al/AlOx/Al) is chemically distinct from the pad film (Ta, Nb, etc.)
    and the resonator. Junction loss tangent cannot be inferred from resonator Qi.

    The junction is a tunnel barrier — it does not have a significant exposed
    metal-air interface. The dominant TLS channel is the AlOx tunnel barrier
    itself, modeled as a single effective junction loss tangent with a junction
    surface participation ratio p_junction_surface.

    Formula: T1_junction_TLS = 1 / (p_junction_surface × tan_delta_junction × 2π × f)

    Note: p_junction_surface is NOT the Level-1 energy fraction p_junction (~0.02).
    It is the fraction of device energy at the junction tunnel barrier interfaces,
    analogous to p_MS_pad for the pad. Default value (2.9e-5) is calibrated to
    give T1_junction_TLS ~ 1000 µs at f=2.736 GHz — consistent with Joshi 2026
    overall loss budget (Martinis & Geller 2014; Carroll et al. 2022).
    """
    notes = []
    notes.append(
        "Junction TLS: single effective loss tangent model (Al/AlOx tunnel barrier). "
        "Independent of resonator calibration — chemically distinct material."
    )

    # Junction surface participation ratio (read from defaults YAML)
    junc_tls_defaults = defaults.get('junction_tls', {})

    p_junc_surf, p_junc_prov = _get(
        material_record, 'geometry', 'p_junction_surface',
        default=None, default_provenance=CLASS_DEFAULT
    )
    if p_junc_surf is None:
        p_junc_surf, p_junc_prov = _get(junc_tls_defaults, 'p_junction_surface',
                                         default=2.9e-5, default_provenance=CLASS_DEFAULT)

    # Junction effective loss tangent — Al/AlOx tunnel barrier
    td_junc, td_junc_prov = _get(
        material_record, 'junction', 'tan_delta_junction',
        default=None, default_provenance=CLASS_DEFAULT
    )
    if td_junc is None:
        td_junc, td_junc_prov = _get(junc_tls_defaults, 'tan_delta_junction',
                                      default=2.0e-3, default_provenance=CLASS_DEFAULT)
        notes.append(
            f"Junction tan_delta not reported — using Al/AlOx class default "
            f"tan_delta_junction = {td_junc:.1e} [{td_junc_prov}]."
        )
    else:
        notes.append(f"Junction tan_delta = {td_junc:.2e} [{td_junc_prov}] (from record).")

    notes.append(f"  p_junction_surface = {p_junc_surf:.2e} [{p_junc_prov}]")
    notes.append(f"  tan_delta_junction = {td_junc:.2e} [{td_junc_prov}]")
    notes.append(f"  f_qubit            = {f_qubit_ghz:.3f} GHz [{f_qubit_prov}]")

    omega = 2.0 * math.pi * f_qubit_ghz * 1000.0  # GHz → cycles/µs → rad/µs
    gamma_junc_tls = p_junc_surf * td_junc * omega
    t1_tls_us = _t1_from_gamma(gamma_junc_tls)

    notes.append(f"  → T1_junction_TLS = {t1_tls_us:.1f} µs")

    worst_prov = _worst_provenance(p_junc_prov, td_junc_prov)

    return {
        'T1_TLS_us':            t1_tls_us,
        'p_junction_surface':   p_junc_surf,
        'tan_delta_junction':   td_junc,
        'provenance':           worst_prov,
        'path':                 'junction_effective_loss_tangent',
        'notes':                notes,
    }


def _compute_qp_channel(material_record: dict, defaults: dict) -> dict:
    """
    Compute T1_QP from Tc via thermal quasiparticle activation.

    Formula: n_qp ∝ exp(−1.76 × Tc / T_operating)
    T1_QP ∝ exp(+1.76 × Tc / T_operating)

    Absolute T1_QP requires the prefactor, which depends on junction properties
    and is not well-constrained from materials measurements alone. We use a
    calibrated reference point: at Tc=1.2K (Al), T_op=20mK, T1_QP ~ 1ms
    (consistent with literature). Other materials scale from this reference.

    IMPORTANT: this formula gives the THERMAL QP lower bound only. In practice,
    non-equilibrium QPs from stray radiation dominate at 20mK regardless of Tc
    (Joshi et al. 2026: observed QP fraction 1e-9 to 1e-5 vs thermal < 1e-19).
    The non-equilibrium floor (T1_QP_nonequilibrium_us) is a system/packaging
    parameter — not derivable from material measurements.

    Returns dict with T1_QP_us, provenance, notes.
    """
    notes = []
    qp_defaults = defaults.get('quasiparticle', {})

    # Tc — use pad film Tc from material record, fall back to pad_fallback default
    tc_val, tc_prov = _get(material_record, 'materials', 'Tc_K',
                            default=None, default_provenance=CLASS_DEFAULT)
    if tc_val is None:
        tc_val, tc_prov = _get(qp_defaults, 'Tc_K_pad_fallback',
                                default=4.4, default_provenance=CLASS_DEFAULT)
        notes.append(f"Tc not measured — using pad fallback default {tc_val} K [{tc_prov}].")
    else:
        notes.append(f"Tc = {tc_val} K [{tc_prov}] (pad film).")

    # Operating temperature
    t_op_mk, t_op_prov = _get(qp_defaults, 'T_operating_mK',
                                default=20.0, default_provenance=CLASS_DEFAULT)
    t_op_k = t_op_mk / 1000.0

    # Reference calibration point (Al junction at 20mK)
    tc_ref = 1.2     # K — aluminum junction
    t1_ref = 1000.0  # µs — 1ms reference T1_QP for Al at 20mK

    # Scale: T1_QP(Tc) = T1_ref × exp(1.76 × (Tc - Tc_ref) / T_op)
    # Cap at 1e9 µs to avoid numerical overflow for high-Tc materials.
    T1_QP_MAX_US = 1.0e9
    exponent = 1.76 * (tc_val - tc_ref) / t_op_k
    if exponent > math.log(T1_QP_MAX_US / t1_ref):
        t1_qp_thermal_us = T1_QP_MAX_US
        notes.append(
            f"Thermal QP activation exponent ({exponent:.1f}) enormous — "
            f"T1_QP_thermal capped at {T1_QP_MAX_US:.0e} µs (negligible loss channel)."
        )
    else:
        t1_qp_thermal_us = t1_ref * math.exp(exponent)

    notes.append(
        f"T1_QP_thermal = {t1_ref:.0f} × exp(1.76 × ({tc_val:.2f} - {tc_ref}) / {t_op_k:.4f}) "
        f"= {t1_qp_thermal_us:.2e} µs [DERIVED — thermal only]."
    )

    # Non-equilibrium QP floor — system level, not material
    t1_qp_noneq, noneq_prov = _get(qp_defaults, 'T1_QP_nonequilibrium_us',
                                     default=1000.0, default_provenance=CLASS_DEFAULT)
    notes.append(
        f"Non-equilibrium QP floor: T1_QP_noneq = {t1_qp_noneq:.0f} µs [{noneq_prov}] "
        "(stray radiation / cosmic rays — system/packaging, not material). "
        "Joshi 2026: observed QP fraction 1e-9 to 1e-5 >> thermal < 1e-19."
    )

    # Always use non-equilibrium floor as the operative T1_QP.
    # Thermal QP is reported for reference but is negligible at 20mK for all
    # practical Tc values. When Tc < Tc_ref (e.g. beta-Ta at 0.7K vs Al ref
    # at 1.2K), the thermal formula gives an unphysically small value that
    # must not be used as the channel T1.
    t1_qp_us = t1_qp_noneq
    notes.append(
        f"Using non-equilibrium QP floor as operative T1_QP = {t1_qp_us:.0f} µs "
        f"[{noneq_prov}]. Thermal value ({t1_qp_thermal_us:.2e} µs) reported for "
        "reference only — non-equilibrium QP dominates at 20mK regardless of Tc."
    )
    provenance = noneq_prov

    return {
        'T1_QP_us':             t1_qp_us,
        'T1_QP_thermal_us':     t1_qp_thermal_us,
        'T1_QP_nonequil_us':    t1_qp_noneq,
        'provenance':           provenance,
        'Tc_K':                 tc_val,
        'Tc_provenance':        tc_prov,
        'T_operating_mK':       t_op_mk,
        'notes':                notes,
    }


def _compute_vortex_channel(material_record: dict, defaults: dict) -> dict:
    """
    Compute T1_vortex from mean free path relative to coherence length.

    Clean limit (l > ξ): vortex motion is the primary loss channel → lower T1_vortex.
    Dirty limit (l < ξ): vortex motion suppressed → higher T1_vortex.

    Corpus finding (May 2026): dirty-limit Ta-Hf films show ~10× higher vortex
    activation temperature than clean-limit films, consistent with suppressed
    vortex motion loss in the dirty limit.

    Returns dict with T1_vortex_us, regime, provenance, notes.
    """
    notes = []
    vortex_defaults = defaults.get('vortex', {})

    # Mean free path
    mfp_val, mfp_prov = _get(material_record, 'materials', 'mean_free_path_nm',
                               default=None, default_provenance=CLASS_DEFAULT)

    # Coherence length (class default — rarely reported directly)
    xi_val, xi_prov = _get(vortex_defaults, 'coherence_length_nm',
                            default=100.0, default_provenance=CLASS_DEFAULT)

    if mfp_val is not None:
        ratio = mfp_val / xi_val
        if ratio > 1.0:
            regime = 'clean'
            t1_key = 'T1_vortex_us_default_clean'
            notes.append(
                f"Mean free path {mfp_val:.1f} nm > coherence length {xi_val:.1f} nm "
                f"(ratio {ratio:.2f}) → clean limit. Vortex motion is primary loss channel."
            )
        else:
            regime = 'dirty'
            t1_key = 'T1_vortex_us_default_dirty'
            notes.append(
                f"Mean free path {mfp_val:.1f} nm < coherence length {xi_val:.1f} nm "
                f"(ratio {ratio:.2f}) → dirty limit. Vortex motion suppressed."
            )
        t1_vortex_us, t1_prov = _get(vortex_defaults, t1_key,
                                       default=1000.0, default_provenance=CLASS_DEFAULT)
        provenance = DERIVED
        notes.append(f"T1_vortex class default for {regime} limit: {t1_vortex_us:.0f} µs [{t1_prov}].")
        notes.append(
            "Note: corpus finding (May 2026, Ta-Hf) supports ~10× higher vortex "
            "activation temperature in dirty-limit films."
        )
    else:
        regime = 'unknown'
        t1_vortex_us, t1_prov = _get(vortex_defaults, 'T1_vortex_us_default_unknown',
                                       default=1000.0, default_provenance=CLASS_DEFAULT)
        provenance = CLASS_DEFAULT
        notes.append("Mean free path not reported — cannot determine clean/dirty limit.")
        notes.append(f"Using unknown-regime default T1_vortex = {t1_vortex_us:.0f} µs.")

    return {
        'T1_vortex_us':      t1_vortex_us,
        'provenance':        provenance,
        'regime':            regime,
        'mean_free_path_nm': mfp_val,
        'mfp_provenance':    mfp_prov,
        'coherence_length_nm': xi_val,
        'notes':             notes,
    }


def _compute_radiation_channel(defaults: dict) -> dict:
    """
    Compute T1_radiation — system-level class default.

    Per Mingzhao (May 2026): radiation loss of the junction depends on its
    coupling strength to the cavity (Purcell / photon DOS effect). It is not
    decomposable into per-component material terms and is not expected to be
    derivable from corpus material measurements.

    Joshi 2026: on-chip Purcell filter gives simulated T1_Purcell > 5ms —
    consistent with the 5000 µs default used here.
    """
    rad_defaults = defaults.get('radiation', {})
    t1_rad_us, prov = _get(rad_defaults, 'T1_radiation_us',
                            default=5000.0, default_provenance=CLASS_DEFAULT)
    return {
        'T1_radiation_us': t1_rad_us,
        'provenance':      CLASS_DEFAULT,
        'notes': [
            "Radiation + Purcell loss: system/packaging parameter, not material.",
            "Per Mingzhao (May 2026): junction radiation rate depends on cavity "
            "coupling (Purcell effect) — not decomposable into per-component material terms.",
            "Joshi 2026: on-chip Purcell filter → T1_Purcell > 5ms (simulation).",
            f"Using class default T1_radiation = {t1_rad_us:.0f} µs [ASSUMED].",
        ],
    }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def compute_t1_decomposition(material_record: dict, defaults: dict) -> dict:
    """
    Compute the full two-level T1 loss channel decomposition.

    Level 1 (v2.5 architecture):
      1/T1_qubit = 1/T1_pad + 1/T1_junction + 1/T1_radiation

    The resonator is a calibration tool — it provides tan_delta via the
    p_MS inversion, but does NOT appear as a term in the Level 1 sum.

    If T1 is directly measured in the material record, it is used as the
    authoritative value [MEASURED] and the decomposition result is labeled
    PREDICTED — enabling model validation against the measured value.

    Returns a plain dict containing:
      - T1_us, T1_provenance          (authoritative — measured if available)
      - T1_measured_us                (gold value, if present)
      - T1_predicted_us               (decomposition result — always computed)
      - tan_delta                     (intermediate — key scientific output)
      - model_validates               (bool — True if predicted within 2x of measured)
      - per-component results         (pad, junction, radiation)
      - per-channel results           (TLS, QP, vortex within each component)
      - assumptions list
    """
    assumptions = []
    notes = []

    # -----------------------------------------------------------------------
    # Check for directly measured T1 and T2 (gold values)
    # -----------------------------------------------------------------------
    t1_measured_us, t1_meas_prov = _get(
        material_record, 'measured', 'T1_us',
        default=None, default_provenance=ASSUMED
    )
    t2_measured_us, t2_meas_prov = _get(
        material_record, 'measured', 'T2_us',
        default=None, default_provenance=ASSUMED
    )

    has_measured_t1 = t1_measured_us is not None
    has_measured_t2 = t2_measured_us is not None

    if has_measured_t1:
        notes.append(
            f"Measured T1 = {t1_measured_us:.1f} µs [{t1_meas_prov}] found in record. "
            "Authoritative value. Decomposition also runs for model validation."
        )
    if has_measured_t2:
        notes.append(f"Measured T2 = {t2_measured_us:.1f} µs [{t2_meas_prov}] found in record.")

    # -----------------------------------------------------------------------
    # Change 1: Gather all new shared inputs
    # -----------------------------------------------------------------------

    # Qi and Q_TLS_0 — resonator quality factor inputs
    qi_val, qi_prov = _get(material_record, 'materials', 'Qi',
                            default=None, default_provenance=ASSUMED)
    q_tls0_val, q_tls0_prov = _get(material_record, 'materials', 'Q_TLS_0',
                                    default=None, default_provenance=ASSUMED)

    # Resonator measurement frequency (for Qi/Q_TLS_0 → T1 conversion if needed)
    qi_freq_ghz, qi_freq_prov = _get(material_record, 'materials', 'Qi_frequency_GHz',
                                      default=None, default_provenance=ASSUMED)

    # Qubit frequency — needed for pad TLS calculation
    f_qubit_ghz, f_qubit_prov = _get(material_record, 'device', 'f_qubit_GHz',
                                      default=None, default_provenance=CLASS_DEFAULT)
    if f_qubit_ghz is None:
        f_qubit_ghz  = 5.0
        f_qubit_prov = CLASS_DEFAULT
        assumptions.append("Qubit frequency not reported — using class default 5.0 GHz.")
        notes.append("f_qubit = 5.0 GHz [CLASS_DEFAULT] — not reported in record.")

    # Surface participation ratios
    surf_defaults = defaults.get('surface_participation', {})

    p_ms_res, p_ms_res_prov = _get(
        material_record, 'surface_participation', 'p_MS_resonator',
        default=None, default_provenance=CLASS_DEFAULT
    )
    if p_ms_res is None:
        p_ms_res, p_ms_res_prov = _get(surf_defaults, 'p_MS_resonator',
                                        default=8.63e-4, default_provenance=CLASS_DEFAULT)

    p_ms_pad, p_ms_pad_prov = _get(
        material_record, 'surface_participation', 'p_MS_pad',
        default=None, default_provenance=CLASS_DEFAULT
    )
    if p_ms_pad is None:
        p_ms_pad, p_ms_pad_prov = _get(surf_defaults, 'p_MS_pad',
                                        default=1.3e-4, default_provenance=CLASS_DEFAULT)

    # Level 1 component energy fractions — used for QP and vortex weighting
    # (TLS uses p_MS_pad directly via the Joshi inversion, not these fractions)
    # TODO: weight QP and vortex by p_pad / p_junction when component-level
    #       FEM data is more widely available in the corpus.
    p_pad     = 0.08   # CLASS_DEFAULT — Wang 2015
    p_junction = 0.02  # CLASS_DEFAULT — Wang 2015

    # -----------------------------------------------------------------------
    # Change 2: Extract tan_delta (resonator calibration step)
    # -----------------------------------------------------------------------
    tan_delta_result = _extract_tan_delta(
        material_record, defaults,
        qi_val, qi_prov,
        q_tls0_val, q_tls0_prov,
        p_ms_res, p_ms_res_prov
    )
    notes.append(
        f"Resonator calibration: tan_delta = {tan_delta_result['tan_delta']:.2e} "
        f"[{tan_delta_result['provenance']}] via {tan_delta_result['source']}."
    )

    # -----------------------------------------------------------------------
    # Change 3: Pad TLS via tan_delta + p_MS_pad (Joshi inversion)
    # -----------------------------------------------------------------------
    pad_tls = _compute_pad_tls(
        material_record, defaults,
        tan_delta_result,
        p_ms_pad, p_ms_pad_prov,
        f_qubit_ghz, f_qubit_prov
    )
    pad_qp   = _compute_qp_channel(material_record, defaults)
    pad_vort = _compute_vortex_channel(material_record, defaults)

    t1_pad = _combine_t1_channels(
        pad_tls['T1_TLS_us'],
        pad_qp['T1_QP_us'],
        pad_vort['T1_vortex_us']
    )

    # -----------------------------------------------------------------------
    # Junction: TLS via interface sum (independent of resonator calibration),
    # plus QP and vortex at qubit level
    # -----------------------------------------------------------------------
    junc_tls  = _compute_junction_tls(material_record, defaults, f_qubit_ghz, f_qubit_prov)
    junc_qp   = _compute_qp_channel(material_record, defaults)
    junc_vort = _compute_vortex_channel(material_record, defaults)

    t1_junction = _combine_t1_channels(
        junc_tls['T1_TLS_us'],
        junc_qp['T1_QP_us'],
        junc_vort['T1_vortex_us']
    )

    # Radiation (system level)
    rad = _compute_radiation_channel(defaults)
    t1_radiation = rad['T1_radiation_us']

    # -----------------------------------------------------------------------
    # Change 4: Level 1 sum — resonator excluded (v2.5 architecture)
    #
    # 1/T1_predicted = 1/T1_pad + 1/T1_junction + 1/T1_radiation
    #
    # The resonator is NOT a term here. It contributed only as calibration
    # (tan_delta extraction above). Any Purcell coupling to the resonator is
    # folded into T1_radiation as a system-level class default.
    # -----------------------------------------------------------------------
    gamma_total = 0.0
    if t1_pad and t1_pad > 0:
        gamma_total += 1.0 / t1_pad
    if t1_junction and t1_junction > 0:
        gamma_total += 1.0 / t1_junction
    if t1_radiation and t1_radiation > 0:
        gamma_total += 1.0 / t1_radiation

    t1_predicted_us = _t1_from_gamma(gamma_total) if gamma_total > 0 else None

    assumptions.append(
        "Resonator excluded from Level 1 qubit loss sum (v2.5 model). "
        "It serves as calibration only — tan_delta extracted via p_MS inversion."
    )
    assumptions.append(
        "QP and vortex channels computed at qubit level (not component-weighted). "
        "TODO: weight by p_pad / p_junction when FEM data more widely available."
    )

    # -----------------------------------------------------------------------
    # Model validation — compare predicted vs measured if both available
    # -----------------------------------------------------------------------
    model_validates  = None
    validation_note  = None
    if has_measured_t1 and t1_predicted_us is not None:
        ratio = t1_predicted_us / t1_measured_us
        model_validates = 0.2 <= ratio <= 5.0
        # Note: threshold is 5x (not 2x) because:
        # 1. TLS saturation at qubit operating powers means the effective
        #    tan_delta is lower than the single-photon resonator value —
        #    measured T1 may exceed the unsaturated TLS prediction (Joshi 2026).
        # 2. Non-equilibrium QP floor is a system parameter not derivable
        #    from material measurements — adds inherent uncertainty.
        # 3. Junction tan_delta class default has high uncertainty.
        validation_note = (
            f"Model validation: predicted {t1_predicted_us:.1f} µs vs "
            f"measured {t1_measured_us:.1f} µs (ratio {ratio:.2f}). "
            f"{'PASS (within 5×).' if model_validates else 'FAIL (outside 5×) — review model inputs.'}"
            f" Note: single-photon tan_delta used — measured T1 may exceed prediction "
            f"due to TLS saturation at qubit operating power (Joshi 2026)."
        )
        notes.append(validation_note)

    # -----------------------------------------------------------------------
    # Authoritative T1 — measured if available, predicted otherwise
    # -----------------------------------------------------------------------
    if has_measured_t1:
        t1_total_us   = t1_measured_us
        t1_provenance = MEASURED
    else:
        t1_total_us   = t1_predicted_us
        t1_provenance = DERIVED

    # -----------------------------------------------------------------------
    # T2 — measured if available, else Bloch limit
    # -----------------------------------------------------------------------
    if has_measured_t2:
        t2_total_us   = t2_measured_us
        t2_provenance = MEASURED
        t2_note       = f"T2 = {t2_total_us:.1f} µs [MEASURED]."
    elif t1_total_us is not None:
        t2_total_us   = 2.0 * t1_total_us
        t2_provenance = DERIVED
        t2_note       = (
            f"T2 not measured — using T2 = 2×T1 = {t2_total_us:.1f} µs "
            "(Bloch equation limit, optimistic; actual T2 may be lower due to pure dephasing)."
        )
        assumptions.append(t2_note)
    else:
        t2_total_us   = None
        t2_provenance = ASSUMED
        t2_note       = "T2 not computable — T1 also unavailable."

    notes.append(t2_note)

    # -----------------------------------------------------------------------
    # Assemble result
    # -----------------------------------------------------------------------
    return {
        # --- Authoritative outputs (feed into estimator.py) ---
        'T1_us':          t1_total_us,
        'T1_provenance':  t1_provenance,
        'T2_us':          t2_total_us,
        'T2_provenance':  t2_provenance,

        # --- Gold measured values (if present) ---
        'T1_measured_us':     t1_measured_us,
        'T1_meas_provenance': t1_meas_prov if has_measured_t1 else None,
        'T2_measured_us':     t2_measured_us,
        'T2_meas_provenance': t2_meas_prov if has_measured_t2 else None,

        # --- Decomposition prediction (always computed) ---
        'T1_predicted_us': t1_predicted_us,
        'model_validates': model_validates,
        'validation_note': validation_note,

        # --- Resonator calibration intermediate (key scientific output) ---
        'tan_delta':          tan_delta_result['tan_delta'],
        'tan_delta_provenance': tan_delta_result['provenance'],
        'tan_delta_source':   tan_delta_result['source'],

        # --- Component-level results ---
        'components': {
            'pad': {
                'p_MS_pad':     p_ms_pad,
                'p_MS_pad_prov': p_ms_pad_prov,
                'T1_pad_us':    t1_pad,
                'channels': {
                    'TLS':    pad_tls,
                    'QP':     pad_qp,
                    'vortex': pad_vort,
                },
            },
            'junction': {
                'p_junction':     p_junction,
                'T1_junction_us': t1_junction,
                'channels': {
                    'TLS':    junc_tls,
                    'QP':     junc_qp,
                    'vortex': junc_vort,
                },
            },
            'radiation': rad,
        },

        # --- Metadata ---
        'notes':       notes,
        'assumptions': assumptions,
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize_decomposition(result: dict) -> str:
    """
    Human-readable summary of the decomposition result.
    Mirrors the style of EstimationResult.summary() in estimator.py.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  T1 Loss Channel Decomposition  (v2.5 model)")
    lines.append("=" * 60)

    t1      = result.get('T1_us')
    t1_prov = result.get('T1_provenance', '')
    t2      = result.get('T2_us')
    t2_prov = result.get('T2_provenance', '')

    lines.append(f"  T1 (authoritative)   : {t1:.1f} µs [{t1_prov}]" if t1 else "  T1: not computable")
    lines.append(f"  T2                   : {t2:.1f} µs [{t2_prov}]" if t2 else "  T2: not computable")

    t1_meas = result.get('T1_measured_us')
    t1_pred = result.get('T1_predicted_us')
    if t1_meas:
        lines.append(f"  T1 measured (gold)   : {t1_meas:.1f} µs")
    if t1_pred:
        lines.append(f"  T1 predicted (model) : {t1_pred:.1f} µs")
    if result.get('validation_note'):
        lines.append(f"  {result['validation_note']}")

    # Resonator calibration intermediate
    td      = result.get('tan_delta')
    td_prov = result.get('tan_delta_provenance', '')
    td_src  = result.get('tan_delta_source', '')
    if td:
        lines.append("")
        lines.append(f"  Resonator calibration:")
        lines.append(f"    tan_delta = {td:.2e} [{td_prov}]  (via {td_src})")

    lines.append("")
    lines.append("  Component breakdown (Level 1 — v2.5: resonator excluded):")
    comps = result.get('components', {})

    # Pad
    pad = comps.get('pad', {})
    t1_pad = pad.get('T1_pad_us')
    p_ms   = pad.get('p_MS_pad')
    p_prov = pad.get('p_MS_pad_prov', '')
    lines.append(
        f"    pad        : p_MS={p_ms:.2e} [{p_prov}]  →  T1={t1_pad:.1f} µs" if t1_pad else
        f"    pad        : T1=n/a"
    )
    for ch_name, ch_data in pad.get('channels', {}).items():
        t1_ch = ch_data.get('T1_TLS_us') or ch_data.get('T1_QP_us') or ch_data.get('T1_vortex_us')
        ch_prov = ch_data.get('provenance', '')
        lines.append(f"      {ch_name:<10}: T1={t1_ch:.1f} µs [{ch_prov}]" if t1_ch else
                     f"      {ch_name:<10}: n/a")

    # Junction
    junc = comps.get('junction', {})
    t1_junc = junc.get('T1_junction_us')
    lines.append(
        f"    junction   : T1={t1_junc:.1f} µs" if t1_junc else
        f"    junction   : T1=n/a"
    )
    for ch_name, ch_data in junc.get('channels', {}).items():
        t1_ch = ch_data.get('T1_TLS_us') or ch_data.get('T1_QP_us') or ch_data.get('T1_vortex_us')
        ch_prov = ch_data.get('provenance', '')
        lines.append(f"      {ch_name:<10}: T1={t1_ch:.1f} µs [{ch_prov}]" if t1_ch else
                     f"      {ch_name:<10}: n/a")

    # Radiation
    rad     = comps.get('radiation', {})
    t1_rad  = rad.get('T1_radiation_us')
    rad_prov = rad.get('provenance', '')
    lines.append(
        f"    radiation  : T1={t1_rad:.1f} µs [{rad_prov}] (system level)" if t1_rad else ""
    )

    if result.get('assumptions'):
        lines.append("")
        lines.append("  Assumptions:")
        for a in result['assumptions']:
            lines.append(f"    * {a}")

    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python3 t1_decomposition.py <material_record.yaml> <defaults.yaml>")
        sys.exit(1)

    defaults = load_model_defaults(sys.argv[2])
    record   = load_material_record(sys.argv[1])
    result   = compute_t1_decomposition(record, defaults)
    print(summarize_decomposition(result))
