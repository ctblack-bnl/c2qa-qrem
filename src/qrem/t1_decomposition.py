# t1_decomposition.py
# Stage 4 of the QREM pipeline: decompose T1 into physical loss channels.
#
# Implements the two-level loss model from loss_channel_model_v2-4.md:
#
#   Level 1 — device components:
#     Γ_total = p_resonator × Γ_resonator
#             + p_pad       × Γ_pad
#             + p_junction  × Γ_junction
#             + Γ_radiation (system level)
#
#   Level 2 — loss channels within each component:
#     Γ_component = Γ_TLS + Γ_QP + Γ_vortex
#     Γ_TLS       = Σ_i ( p_i × tan_delta_i )   [MS, SA, MA, bulk interfaces]
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
#   Wang et al., APL 107, 162601 (2015)       — participation ratios
#   Read et al., PRA 19, 034064 (2023)        — interface loss tangents, Qi interpretation
#   loss_channel_model_v2-4.md                — model architecture
#   qrem_scientific_vision.md                 — Tier 2 derivation rationale

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


# ---------------------------------------------------------------------------
# Channel computations
# ---------------------------------------------------------------------------

def _compute_tls_component(component_name: str,
                            material_record: dict,
                            defaults: dict,
                            qi_value: Optional[float],
                            qi_provenance: str,
                            qi_frequency_ghz: float) -> dict:
    """
    Compute Γ_TLS for one device component.

    Two paths:
      Path A — Qi available: T1_TLS ≈ Qi / (2π × f)
        Valid when Qi reflects energy decay. S21-extracted Qi may include
        T_phi contribution (Read et al. 2023, Appendix A) — flagged in provenance.
      Path B — Qi not available: sum over interfaces using participation ratios
        and loss tangents from material record or defaults.

    Returns dict with T1_TLS_us, provenance, path_used, notes.
    """
    notes = []

    # --- Path A: Qi available (aggregate, not component-resolved) ---
    # Only use for resonator component — Qi is a resonator measurement.
    if component_name == 'resonator' and qi_value is not None and qi_frequency_ghz is not None:
        omega = 2.0 * math.pi * qi_frequency_ghz  # rad/µs (GHz × 2π = rad/µs)
        t1_tls_us = qi_value / omega

        # Flag measurement method uncertainty per Mingzhao / Read et al.
        method = material_record.get('materials', {}).get('Qi', {}).get('measurement_method', 'S21')
        if method == 'ring_down':
            prov = DERIVED
            notes.append("Qi from ring-down measurement — T1_TLS reflects energy decay rate.")
        else:
            prov = DERIVED
            notes.append(
                "Qi from S21 linewidth (assumed) — T1_TLS may include T_phi contribution "
                "(Read et al. 2023, Appendix A). Treat as lower bound on true T1_TLS."
            )

        return {
            'T1_TLS_us': t1_tls_us,
            'provenance': prov,
            'path': 'Qi_aggregate',
            'qi_value': qi_value,
            'qi_provenance': qi_provenance,
            'notes': notes,
        }

    # --- Path B: interface sum ---
    # Γ_TLS = Σ_i ( p_i × tan_delta_i ) × ω
    # where ω is needed to convert loss tangent to rate.
    # When ω is unknown, we work in units of Γ/ω and convert at the end
    # using a default frequency.

    comp_defaults = defaults.get('interface_participation', {}).get(component_name, {})
    loss_defaults = defaults.get('interface_loss_tangents', {})

    interfaces = ['MS', 'SA', 'MA', 'bulk']
    gamma_tls_over_omega = 0.0
    interface_notes = []
    worst_provenance = MEASURED  # will be degraded as we use defaults

    provenance_rank = {MEASURED: 0, DERIVED: 1, CLASS_DEFAULT: 2, ASSUMED: 3}

    for iface in interfaces:
        p_key = f'p_{iface}'
        td_key = f'tan_delta_{iface}'

        # Participation ratio — try material record first, then defaults
        p_val, p_prov = _get(
            material_record, 'geometry', component_name, p_key,
            default=None, default_provenance=CLASS_DEFAULT
        )
        if p_val is None:
            p_val, p_prov = _get(comp_defaults, p_key,
                                  default=1e-4, default_provenance=CLASS_DEFAULT)

        # Loss tangent — try material record first, then defaults
        td_val, td_prov = _get(
            material_record, 'interfaces', td_key,
            default=None, default_provenance=CLASS_DEFAULT
        )
        if td_val is None:
            td_val, td_prov = _get(loss_defaults, td_key,
                                    default=1e-3, default_provenance=CLASS_DEFAULT)

        contribution = p_val * td_val
        gamma_tls_over_omega += contribution

        # Track worst provenance across all inputs
        for prov in [p_prov, td_prov]:
            if provenance_rank.get(prov, 3) > provenance_rank.get(worst_provenance, 0):
                worst_provenance = prov

        interface_notes.append(
            f"  {iface}: p={p_val:.2e} [{p_prov}] × tan_δ={td_val:.2e} [{td_prov}] "
            f"= {contribution:.2e}"
        )

    # Convert to T1: T1 = 1 / (Γ_TLS) = 1 / (gamma_over_omega × ω)
    # Use measured frequency if available, else default
    if qi_frequency_ghz is not None:
        omega_ghz = 2.0 * math.pi * qi_frequency_ghz
        freq_note = f"Using measured frequency {qi_frequency_ghz:.2f} GHz."
        freq_prov = qi_provenance
    else:
        omega_ghz = 2.0 * math.pi * 5.0  # default 5 GHz qubit frequency
        freq_note = "Using default qubit frequency 5 GHz."
        freq_prov = CLASS_DEFAULT
        if provenance_rank.get(CLASS_DEFAULT, 2) > provenance_rank.get(worst_provenance, 0):
            worst_provenance = CLASS_DEFAULT

    gamma_tls = gamma_tls_over_omega * omega_ghz  # 1/µs
    t1_tls_us = _t1_from_gamma(gamma_tls)
    notes.extend(interface_notes)
    notes.append(freq_note)

    return {
        'T1_TLS_us': t1_tls_us,
        'provenance': worst_provenance,
        'path': 'interface_sum',
        'gamma_tls_over_omega': gamma_tls_over_omega,
        'notes': notes,
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

    Returns dict with T1_QP_us, provenance, notes.
    """
    notes = []
    qp_defaults = defaults.get('quasiparticle', {})

    # Tc
    tc_val, tc_prov = _get(material_record, 'materials', 'Tc_K',
                            default=None, default_provenance=CLASS_DEFAULT)
    if tc_val is None:
        tc_val, tc_prov = _get(qp_defaults, 'Tc_K',
                                default=1.2, default_provenance=CLASS_DEFAULT)
        notes.append(f"Tc not measured — using class default {tc_val} K.")
    else:
        notes.append(f"Tc = {tc_val} K [{tc_prov}].")

    # Operating temperature
    t_op_mk, t_op_prov = _get(qp_defaults, 'T_operating_mK',
                                default=20.0, default_provenance=CLASS_DEFAULT)
    t_op_k = t_op_mk / 1000.0

    # Reference calibration point (Al at 20mK)
    tc_ref = 1.2    # K — aluminum
    t1_ref = 1000.0  # µs — 1ms reference T1_QP for Al at 20mK

    # Scale: T1_QP(Tc) = T1_ref × exp(1.76 × (Tc - Tc_ref) / T_op)
    # This is the ratio of thermal activation factors relative to the reference.
    # For high-Tc materials (Ta, Nb, NbN) the exponent is enormous (e.g. Ta at 20mK
    # gives exponent ~280) — QP loss is essentially zero. Cap T1_QP at 1e9 µs
    # (~30 years) which is physically "negligible" without numerical overflow.
    T1_QP_MAX_US = 1.0e9
    exponent = 1.76 * (tc_val - tc_ref) / t_op_k
    if exponent > math.log(T1_QP_MAX_US / t1_ref):
        t1_qp_us = T1_QP_MAX_US
        notes.append(
            f"QP thermal activation exponent ({exponent:.1f}) extremely large — "
            f"T1_QP capped at {T1_QP_MAX_US:.0e} µs (effectively negligible loss channel)."
        )
    else:
        t1_qp_us = t1_ref * math.exp(exponent)

    # Provenance degrades if Tc was not measured
    provenance_rank = {MEASURED: 0, DERIVED: 1, CLASS_DEFAULT: 2, ASSUMED: 3}
    worst = tc_prov if provenance_rank.get(tc_prov, 3) >= provenance_rank.get(t_op_prov, 3) else t_op_prov
    if worst in [CLASS_DEFAULT, ASSUMED]:
        provenance = DERIVED  # formula is applied but inputs are defaults
    else:
        provenance = DERIVED  # formula always makes this DERIVED at best

    notes.append(
        f"T1_QP derived from thermal activation: "
        f"T1_QP = {t1_ref:.0f} µs × exp(1.76 × ({tc_val:.2f} - {tc_ref}) / {t_op_k:.4f}) "
        f"= {t1_qp_us:.0f} µs."
    )
    notes.append("Reference calibration: Al (Tc=1.2K) → T1_QP~1ms at 20mK.")

    return {
        'T1_QP_us': t1_qp_us,
        'provenance': provenance,
        'Tc_K': tc_val,
        'Tc_provenance': tc_prov,
        'T_operating_mK': t_op_mk,
        'notes': notes,
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
        # Determine clean vs dirty limit
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
        # Provenance: regime is DERIVED (from measured mfp), but T1 value is CLASS_DEFAULT
        provenance = DERIVED
        notes.append(f"T1_vortex class default for {regime} limit: {t1_vortex_us:.0f} µs [{t1_prov}].")
        notes.append(
            "Note: corpus finding (May 2026, Ta-Hf) supports ~10× higher vortex "
            "activation temperature in dirty-limit films."
        )
    else:
        # Mean free path not available — use unknown default
        regime = 'unknown'
        t1_vortex_us, t1_prov = _get(vortex_defaults, 'T1_vortex_us_default_unknown',
                                       default=1000.0, default_provenance=CLASS_DEFAULT)
        provenance = CLASS_DEFAULT
        notes.append("Mean free path not reported — cannot determine clean/dirty limit.")
        notes.append(f"Using unknown-regime default T1_vortex = {t1_vortex_us:.0f} µs.")

    return {
        'T1_vortex_us': t1_vortex_us,
        'provenance': provenance,
        'regime': regime,
        'mean_free_path_nm': mfp_val,
        'mfp_provenance': mfp_prov,
        'coherence_length_nm': xi_val,
        'notes': notes,
    }


def _compute_radiation_channel(defaults: dict) -> dict:
    """
    Compute T1_radiation — system-level class default.

    Per Mingzhao (May 2026): radiation loss of the junction depends on its
    coupling strength to the cavity (Purcell / photon DOS effect). It is not
    decomposable into per-component material terms and is not expected to be
    derivable from corpus material measurements.
    """
    rad_defaults = defaults.get('radiation', {})
    t1_rad_us, prov = _get(rad_defaults, 'T1_radiation_us',
                            default=5000.0, default_provenance=CLASS_DEFAULT)
    return {
        'T1_radiation_us': t1_rad_us,
        'provenance': CLASS_DEFAULT,
        'notes': [
            "Radiation loss is a system/packaging parameter, not a material property.",
            "Per Mingzhao (May 2026): junction radiation rate depends on cavity coupling "
            "(Purcell effect) — not decomposable into per-component material terms.",
            f"Using class default T1_radiation = {t1_rad_us:.0f} µs.",
        ],
    }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def compute_t1_decomposition(material_record: dict, defaults: dict) -> dict:
    """
    Compute the full two-level T1 loss channel decomposition.

    If T1 is directly measured in the material record, it is used as the
    authoritative value [MEASURED] and the decomposition result is labeled
    PREDICTED — enabling model validation against the measured value.

    Returns a plain dict (consistent with coherence_budget in estimator.py)
    containing:
      - T1_total_us, T1_provenance
      - T1_measured_us (if available — gold value)
      - T1_predicted_us (decomposition result — always computed)
      - model_validates (bool — True if predicted within 2x of measured)
      - per-component results (resonator, pad, junction, radiation)
      - per-channel results within each component (TLS, QP, vortex)
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
            "This is the authoritative value. Decomposition will also run for model validation."
        )
    if has_measured_t2:
        notes.append(f"Measured T2 = {t2_measured_us:.1f} µs [{t2_meas_prov}] found in record.")

    # -----------------------------------------------------------------------
    # Shared inputs used across multiple channels
    # -----------------------------------------------------------------------
    qi_val, qi_prov = _get(material_record, 'materials', 'Qi',
                            default=None, default_provenance=ASSUMED)
    qi_freq_ghz, qi_freq_prov = _get(material_record, 'materials', 'Qi_frequency_GHz',
                                      default=None, default_provenance=ASSUMED)

    # -----------------------------------------------------------------------
    # Component participation ratios (Level 1)
    # -----------------------------------------------------------------------
    comp_defaults = defaults.get('component_participation', {})

    p_resonator, p_res_prov = _get(material_record, 'geometry', 'p_resonator',
                                    default=None, default_provenance=CLASS_DEFAULT)
    if p_resonator is None:
        p_resonator, p_res_prov = _get(comp_defaults, 'p_resonator',
                                        default=0.90, default_provenance=CLASS_DEFAULT)

    p_pad, p_pad_prov = _get(material_record, 'geometry', 'p_pad',
                              default=None, default_provenance=CLASS_DEFAULT)
    if p_pad is None:
        p_pad, p_pad_prov = _get(comp_defaults, 'p_pad',
                                  default=0.08, default_provenance=CLASS_DEFAULT)

    p_junction, p_junc_prov = _get(material_record, 'geometry', 'p_junction',
                                    default=None, default_provenance=CLASS_DEFAULT)
    if p_junction is None:
        p_junction, p_junc_prov = _get(comp_defaults, 'p_junction',
                                        default=0.02, default_provenance=CLASS_DEFAULT)

    # -----------------------------------------------------------------------
    # Compute loss channels for each component
    # -----------------------------------------------------------------------

    # --- Resonator ---
    res_tls  = _compute_tls_component('resonator', material_record, defaults,
                                       qi_val, qi_prov, qi_freq_ghz)
    res_qp   = _compute_qp_channel(material_record, defaults)
    res_vort = _compute_vortex_channel(material_record, defaults)

    t1_res_tls  = res_tls['T1_TLS_us']
    t1_res_qp   = res_qp['T1_QP_us']
    t1_res_vort = res_vort['T1_vortex_us']

    if res_tls['path'] == 'Qi_aggregate':
        # Qi already encodes ALL resonator loss — TLS, QP, vortex, radiation
        # combined. Do not add QP and vortex on top — that would double-count.
        # T1_resonator = Qi / (2πf) directly.
        t1_resonator = t1_res_tls
        res_qp['notes'].insert(0,
            "QP not added separately — Qi aggregate already includes all resonator loss channels.")
        res_vort['notes'].insert(0,
            "Vortex not added separately — Qi aggregate already includes all resonator loss channels.")
    else:
        # Interface sum path — each channel is independent, combine normally
        t1_resonator = _combine_t1_channels(t1_res_tls, t1_res_qp, t1_res_vort)

    # --- Pad ---
    # Pad has no Qi (that's a resonator measurement) — always uses interface sum
    pad_tls  = _compute_tls_component('pad', material_record, defaults,
                                       None, ASSUMED, qi_freq_ghz)
    pad_qp   = _compute_qp_channel(material_record, defaults)   # same Tc input
    pad_vort = _compute_vortex_channel(material_record, defaults)  # same film

    t1_pad_tls  = pad_tls['T1_TLS_us']
    t1_pad_qp   = pad_qp['T1_QP_us']
    t1_pad_vort = pad_vort['T1_vortex_us']
    t1_pad = _combine_t1_channels(t1_pad_tls, t1_pad_qp, t1_pad_vort)

    # --- Junction ---
    junc_tls  = _compute_tls_component('junction', material_record, defaults,
                                        None, ASSUMED, qi_freq_ghz)
    junc_qp   = _compute_qp_channel(material_record, defaults)
    junc_vort = _compute_vortex_channel(material_record, defaults)

    t1_junc_tls  = junc_tls['T1_TLS_us']
    t1_junc_qp   = junc_qp['T1_QP_us']
    t1_junc_vort = junc_vort['T1_vortex_us']
    t1_junction = _combine_t1_channels(t1_junc_tls, t1_junc_qp, t1_junc_vort)

    # --- Radiation (system level) ---
    rad = _compute_radiation_channel(defaults)
    t1_radiation = rad['T1_radiation_us']

    # -----------------------------------------------------------------------
    # Combine components → T1_predicted
    # Level 1: 1/T1_total = p_res/T1_res + p_pad/T1_pad + p_junc/T1_junc + 1/T1_rad
    # -----------------------------------------------------------------------
    gamma_total = 0.0
    if t1_resonator and t1_resonator > 0:
        gamma_total += p_resonator / t1_resonator
    if t1_pad and t1_pad > 0:
        gamma_total += p_pad / t1_pad
    if t1_junction and t1_junction > 0:
        gamma_total += p_junction / t1_junction
    if t1_radiation and t1_radiation > 0:
        gamma_total += 1.0 / t1_radiation

    t1_predicted_us = _t1_from_gamma(gamma_total) if gamma_total > 0 else None

    # -----------------------------------------------------------------------
    # Model validation — compare predicted vs measured if both available
    # -----------------------------------------------------------------------
    model_validates = None
    validation_note = None
    if has_measured_t1 and t1_predicted_us is not None:
        ratio = t1_predicted_us / t1_measured_us
        model_validates = 0.5 <= ratio <= 2.0  # within factor of 2
        validation_note = (
            f"Model validation: predicted {t1_predicted_us:.1f} µs vs "
            f"measured {t1_measured_us:.1f} µs (ratio {ratio:.2f}). "
            f"{'PASS (within 2×).' if model_validates else 'FAIL (outside 2×) — review model inputs.'}"
        )
        notes.append(validation_note)

    # -----------------------------------------------------------------------
    # Authoritative T1 — measured if available, predicted otherwise
    # -----------------------------------------------------------------------
    if has_measured_t1:
        t1_total_us     = t1_measured_us
        t1_provenance   = MEASURED
    else:
        t1_total_us     = t1_predicted_us
        t1_provenance   = DERIVED

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
        'T1_us':            t1_total_us,
        'T1_provenance':    t1_provenance,
        'T2_us':            t2_total_us,
        'T2_provenance':    t2_provenance,

        # --- Gold measured values (if present) ---
        'T1_measured_us':   t1_measured_us,
        'T1_meas_provenance': t1_meas_prov if has_measured_t1 else None,
        'T2_measured_us':   t2_measured_us,
        'T2_meas_provenance': t2_meas_prov if has_measured_t2 else None,

        # --- Decomposition prediction (always computed) ---
        'T1_predicted_us':  t1_predicted_us,
        'model_validates':  model_validates,
        'validation_note':  validation_note,

        # --- Component-level results ---
        'components': {
            'resonator': {
                'p_resonator':      p_resonator,
                'p_provenance':     p_res_prov,
                'T1_resonator_us':  t1_resonator,
                'channels': {
                    'TLS':   res_tls,
                    'QP':    res_qp,
                    'vortex': res_vort,
                },
            },
            'pad': {
                'p_pad':        p_pad,
                'p_provenance': p_pad_prov,
                'T1_pad_us':    t1_pad,
                'channels': {
                    'TLS':   pad_tls,
                    'QP':    pad_qp,
                    'vortex': pad_vort,
                },
            },
            'junction': {
                'p_junction':   p_junction,
                'p_provenance': p_junc_prov,
                'T1_junction_us': t1_junction,
                'channels': {
                    'TLS':   junc_tls,
                    'QP':    junc_qp,
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
    lines.append("--- T1 Loss Channel Decomposition ---")

    t1 = result.get('T1_us')
    t1_prov = result.get('T1_provenance', '')
    t2 = result.get('T2_us')
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

    lines.append("")
    lines.append("  Component breakdown:")
    comps = result.get('components', {})

    for comp_name in ['resonator', 'pad', 'junction']:
        comp = comps.get(comp_name, {})
        p_key = f'p_{comp_name}'
        p_val = comp.get(p_key)
        t1_comp = comp.get(f'T1_{comp_name}_us')
        p_prov = comp.get('p_provenance', '')
        t1_str = f"{t1_comp:.1f} µs" if t1_comp else "n/a"
        p_str  = f"{p_val:.3f}" if p_val is not None else "n/a"
        lines.append(f"    {comp_name:<12}: p={p_str} [{p_prov}]  →  T1={t1_str}")

        channels = comp.get('channels', {})
        for ch_name, ch_data in channels.items():
            t1_ch_key = f'T1_{ch_name}_us' if ch_name != 'TLS' else 'T1_TLS_us'
            # handle naming variations
            t1_ch = ch_data.get('T1_TLS_us') or ch_data.get('T1_QP_us') or ch_data.get('T1_vortex_us')
            ch_prov = ch_data.get('provenance', '')
            t1_ch_str = f"{t1_ch:.1f} µs" if t1_ch else "n/a"
            lines.append(f"      {ch_name:<10}: T1={t1_ch_str} [{ch_prov}]")

    rad = comps.get('radiation', {})
    t1_rad = rad.get('T1_radiation_us')
    rad_prov = rad.get('provenance', '')
    lines.append(f"    {'radiation':<12}: T1={t1_rad:.1f} µs [{rad_prov}] (system level)" if t1_rad else "")

    if result.get('assumptions'):
        lines.append("")
        lines.append("  Assumptions:")
        for a in result['assumptions']:
            lines.append(f"    * {a}")

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
