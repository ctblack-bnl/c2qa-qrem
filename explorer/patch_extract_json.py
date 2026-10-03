#!/usr/bin/env python3
"""Patch pipeline_ingest.py: make extract_json() tolerate trailing commas.

Usage (from explorer/):  python3 patch_extract_json.py
Makes a backup pipeline_ingest.py.bak first. Safe to run twice."""
import re, sys, shutil
from pathlib import Path

TARGET = Path("pipeline_ingest.py")
NEW = r'''def _strip_trailing_commas(text: str) -> str:
    """Remove commas that directly precede a closing } or ] (ignoring
    whitespace), but only outside quoted strings so paper text is never
    altered. Models occasionally emit these; strict JSON rejects them."""
    out = []
    in_str = False
    esc = False
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
                out.append(c)
            elif c == ",":
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if j < n and text[j] in "}]":
                    pass  # drop the trailing comma
                else:
                    out.append(c)
            else:
                out.append(c)
        i += 1
    return "".join(out)


def extract_json(raw: str) -> Optional[dict]:
    """
    Extract and parse a JSON object from Claude's response.
    Handles markdown code fences, and (as a last resort) trailing commas
    before a closing brace/bracket -- a known occasional model slip that
    otherwise fails an entire paper's extraction.
    """
    if not raw:
        return None

    # Strip markdown code fences if present
    text = raw.strip()

    # Remove opening fence (```json or ```)
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1:].strip()

    # Remove closing fence (```)
    if text.endswith("```"):
        text = text[:-3].strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find the first { and last } and parse between them
    start = text.find("{")
    end   = text.rfind("}") + 1
    candidate = text[start:end] if (start >= 0 and end > start) else None
    if candidate is not None:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Last resort: repair trailing commas (outside strings) and retry
        try:
            result = json.loads(_strip_trailing_commas(candidate))
            print("  (note: repaired trailing comma(s) in model JSON)", flush=True)
            return result
        except json.JSONDecodeError:
            pass

    return None'''

src = TARGET.read_text(encoding="utf-8")
if "_strip_trailing_commas" in src:
    print("Already patched; nothing to do."); sys.exit(0)

m = re.search(r"^def extract_json\(raw: str\) -> Optional\[dict\]:.*?(?=^# -{20,}\n# Main pipeline)",
              src, flags=re.S | re.M)
if not m:
    print("ERROR: could not find extract_json() block; no changes made."); sys.exit(1)

shutil.copy(TARGET, "pipeline_ingest.py.bak")
new_src = src[:m.start()] + NEW.strip("\n") + "\n\n\n" + src[m.end():]
TARGET.write_text(new_src, encoding="utf-8")
print("Patched. Backup saved as pipeline_ingest.py.bak")
