# src/metadata_tagging/json_utils.py
import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any

def safe_json_dumps(obj: Any) -> str:
    def _default(o: Any):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, (bytes, bytearray)):
            return {"__bytes__": True, "b64": base64.b64encode(o).decode("utf-8")}
        if isinstance(o, Path):
            return o.as_posix()
        print(f"[json_utils] WARNING: Unhandled type {type(o).__name__}, falling back to str()")
        return str(o)

    return json.dumps(obj, ensure_ascii=False, default=_default)