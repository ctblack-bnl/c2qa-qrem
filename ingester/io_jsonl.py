# src/metadata_tagging/io_jsonl.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional, Set

from json_utils import safe_json_dumps


Record = Dict[str, Any]


def iter_jsonl(path: Path) -> Iterator[Record]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[io_jsonl] Skipping malformed line {i}: {e}")


def append_jsonl(path: Path, record: Record) -> None:
    """Append one record to JSONL (creates parent dirs as needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(safe_json_dumps(record) + "\n")


def write_jsonl(path: Path, records: Iterable[Record]) -> None:
    """Write records to JSONL (overwrite)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(safe_json_dumps(r) + "\n")


def load_processed_keys(
    jsonl_path: Path,
    *,
    require_ok: bool = True,
    key_mode: str = "filename",  # "filename", "relpath", or "fullpath"
) -> Set[str]:
    """
    Build a set of processed keys from an existing JSONL.

    require_ok=True means: error is None AND model_output_json exists.
    key_mode:
        - "filename": just basename
        - "relpath": path relative to images root (recommended for subfolders)
        - "fullpath": stored path as-is
    """
    processed: Set[str] = set()

    if not jsonl_path.exists():
        return processed

    for rec in iter_jsonl(jsonl_path):
        asset = rec.get("asset") or {}
        p = asset.get("path")

        # Determine key
        if key_mode == "filename":
            key = Path(p).name if p else asset.get("basename")

        elif key_mode == "relpath":
            if p:
                pp = Path(p).as_posix()
                for prefix in ("data/images/", "images/", "Images/"):
                    if pp.startswith(prefix):
                        pp = pp[len(prefix):]
                        break
                key = pp
            else:
                key = asset.get("basename")

        else:  # fullpath
            key = p or asset.get("basename")

        if not key:
            continue

        if require_ok:
            ok = rec.get("error") is None and rec.get("model_output_json") is not None
            if not ok:
                continue

        processed.add(str(key))

    return processed