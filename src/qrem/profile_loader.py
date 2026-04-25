# profile_loader.py
# Modular hardware profile loader for the QREM pipeline.
#
# Replaces the single _load_profile() call in estimator.py with a loader
# that merges four separate YAML files into one profile dict — the same
# structure the rest of estimator.py already expects.
#
# Two calling modes:
#
#   Modular (new):
#       profile = load_profile(
#           profiles_dir="src/qrem/hardware_profiles",
#           qubits="transmon_baseline_2026",
#           interconnect="microwave_photonic_85pct",
#           module="module_1000q_nearest_neighbor",
#           error_correction="surface_code_1e6",
#       )
#
#   Legacy (backward compatible — single monolithic yaml):
#       profile = load_profile(legacy_path="src/qrem/hardware_profiles/superconducting.yaml")
#
# The merged dict is identical in structure to the old monolithic YAML so
# estimator.py needs no other changes.

import yaml
import copy
from pathlib import Path
from typing import Optional


PROFILE_SUBDIRS = {
    "qubits":           "qubits",
    "interconnect":     "interconnects",
    "module":           "modules",
    "error_correction": "error_correction",
}

# Sections each subdir contributes to the merged profile dict.
# Keys here match what estimator.py reads from profile[section].
SECTION_KEYS = {
    "qubits":           ["coherence", "gates", "provenance"],
    "interconnect":     ["intermodule"],
    "module":           ["module"],
    "error_correction": ["error_correction"],
}


def _load_yaml(path: Path) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_profile(
    profiles_dir: Optional[str] = None,
    qubits: Optional[str] = None,
    interconnect: Optional[str] = None,
    module: Optional[str] = None,
    error_correction: Optional[str] = None,
    legacy_path: Optional[str] = None,
    overrides: Optional[dict] = None,
) -> dict:
    """
    Load and merge hardware profile components into a single profile dict.

    Modular mode — pass profiles_dir + four component names:
        profile = load_profile(
            profiles_dir="src/qrem/hardware_profiles",
            qubits="transmon_baseline_2026",
            interconnect="microwave_photonic_85pct",
            module="module_1000q_nearest_neighbor",
            error_correction="surface_code_1e6",
        )

    Legacy mode — pass a single YAML path (old behavior, still works):
        profile = load_profile(legacy_path="src/qrem/hardware_profiles/superconducting.yaml")

    Optional overrides dict is merged after loading (same as before):
        overrides={"gates": {"two_qubit_fidelity_pct": 99.5}}

    Returns a dict with the same structure estimator.py has always expected.
    """
    if legacy_path:
        profile = _load_yaml(Path(legacy_path))
        if overrides:
            profile = _apply_overrides(profile, overrides)
        return profile

    # --- Modular mode ---
    if not profiles_dir:
        raise ValueError("Must provide either profiles_dir or legacy_path")

    base = Path(profiles_dir)
    components = {
        "qubits":           qubits,
        "interconnect":     interconnect,
        "module":           module,
        "error_correction": error_correction,
    }

    merged = {}
    provenance_log = {}  # track which file each section came from

    for component, name in components.items():
        if not name:
            raise ValueError(f"Missing profile component: {component}")

        subdir = PROFILE_SUBDIRS[component]
        path = base / subdir / f"{name}.yaml"

        if not path.exists():
            raise FileNotFoundError(
                f"Profile not found: {path}\n"
                f"Available in {base / subdir}:\n" +
                "\n".join(f"  {p.stem}" for p in (base / subdir).glob("*.yaml"))
            )

        data = _load_yaml(path)

        # Merge the relevant sections into the combined profile dict
        for key in SECTION_KEYS[component]:
            if key in data:
                merged[key] = copy.deepcopy(data[key])
                provenance_log[key] = str(path)

        # Carry top-level metadata from the qubit profile
        if component == "qubits":
            merged["platform"]    = data.get("platform", "superconducting")
            merged["description"] = data.get("description", name)
            merged["name"]        = data.get("name", name)

    # Attach provenance so callers can inspect what was loaded
    merged["_provenance"] = provenance_log

    if overrides:
        merged = _apply_overrides(merged, overrides)

    return merged


def _apply_overrides(profile: dict, overrides: dict) -> dict:
    """
    Apply a nested override dict to a profile dict.
    Merges one level deep — sufficient for all current profile parameters.
    """
    profile = copy.deepcopy(profile)
    for section, values in overrides.items():
        if isinstance(values, dict) and section in profile:
            profile[section].update(values)
        else:
            profile[section] = values
    return profile


def list_profiles(profiles_dir: str) -> dict:
    """
    Return available profile names for each component directory.
    Used to populate UI dropdowns.

    Returns:
        {
            "qubits":           ["transmon_baseline_2026", ...],
            "interconnects":    ["microwave_photonic_85pct", ...],
            "modules":          ["module_1000q_nearest_neighbor", ...],
            "error_correction": ["surface_code_1e6", ...],
        }
    """
    base = Path(profiles_dir)
    result = {}
    for component, subdir in PROFILE_SUBDIRS.items():
        d = base / subdir
        if d.exists():
            result[component] = sorted(p.stem for p in d.glob("*.yaml"))
        else:
            result[component] = []
    return result


if __name__ == "__main__":
    # Quick smoke test
    import sys
    profiles_dir = sys.argv[1] if len(sys.argv) > 1 else "hardware_profiles"

    print("Available profiles:")
    available = list_profiles(profiles_dir)
    for component, names in available.items():
        print(f"  {component}: {names}")

    print("\nLoading default modular profile...")
    try:
        profile = load_profile(
            profiles_dir=profiles_dir,
            qubits="transmon_baseline_2026",
            interconnect="microwave_photonic_85pct",
            module="module_1000q_nearest_neighbor",
            error_correction="surface_code_1e6",
        )
        print(f"  Platform:    {profile.get('platform')}")
        print(f"  Description: {profile.get('description')}")
        print(f"  T1:          {profile['coherence']['T1_us']} µs")
        print(f"  2Q fidelity: {profile['gates']['two_qubit_fidelity_pct']}%")
        print(f"  Link fidelity: {profile['intermodule']['link_fidelity_pct']}%")
        print(f"  Qubits/module: {profile['module']['physical_qubits_per_module']}")
        print(f"  QEC target:  {profile['error_correction']['target_logical_error_rate']}")
        print(f"\n  Provenance:")
        for section, path in profile['_provenance'].items():
            print(f"    {section}: {path}")
        print("\nOK — modular loader working.")
    except Exception as e:
        print(f"ERROR: {e}")
