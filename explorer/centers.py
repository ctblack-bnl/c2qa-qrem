"""
centers.py -- derive canonical DOE National QIS Research Center codes from
funding-acknowledgment text.

Design (see schema doc, acknowledged_centers):
  * Claude extracts the raw acknowledgment text (Pass 1 `funding_acknowledgments`);
    this module normalizes it DETERMINISTICALLY to canonical codes, the same
    pattern as derived_material / normalize_film_material() in build_sqlite.py.
  * Only the acknowledgment text is ever consulted -- never affiliations or
    author lists.
  * Matching is by specific center name or acronym, NEVER on the bare word
    "Center" -- non-NQISRC entities (Pro-QM EFRC, Center for Functional
    Nanomaterials, NSF QLCI, PNNL QuAADS, ...) must not match.

Return convention of derive_centers():
  None          -> no acknowledgment text available (null/empty); unknown
  []            -> text present, but names none of the five centers
  ["C2QA", ...] -> canonical codes, in CENTER_ORDER, de-duplicated
"""

import re
import unicodedata

# Canonical order is also the display order.
CENTER_ORDER = ["C2QA", "Q-NEXT", "QSA", "QSC", "SQMS"]

CENTER_NAMES = {
    "C2QA": "Co-design Center for Quantum Advantage",
    "Q-NEXT": "Next Generation Quantum Science and Engineering",
    "QSA": "Quantum Systems Accelerator",
    "QSC": "Quantum Science Center",
    "SQMS": "Superconducting Quantum Materials and Systems Center",
}

# Patterns run case-insensitively against dash-normalized, NFC text.
# Acronyms use word boundaries so e.g. "QSA" cannot match inside another word.
# Full names tolerate "for"/"of" and hyphen/space variants seen in real papers
# ("Co-design Center of Quantum Advantage", "Co-Design Center ...").
_ALIAS_PATTERNS = {
    "C2QA": [
        r"\bC2QA\b",
        r"\bco-?\s?design\s+cent(?:er|re)\s+(?:for|of)\s+quantum\s+advantage\b",
    ],
    "Q-NEXT": [
        r"\bQ-?\s?NEXT\b",
        r"\bnext[\s-]+generation\s+quantum\s+science\s+and\s+engineering\b",
    ],
    "QSA": [
        r"\bQSA\b",
        r"\bquantum\s+systems\s+accelerator\b",
    ],
    "QSC": [
        r"\bQSC\b",
        r"\bquantum\s+science\s+cent(?:er|re)\b",
    ],
    "SQMS": [
        r"\bSQMS\b",
        r"\bsuperconducting\s+quantum\s+materials\s+and\s+systems\b",
    ],
}

_COMPILED = {
    code: [re.compile(p, re.IGNORECASE) for p in pats]
    for code, pats in _ALIAS_PATTERNS.items()
}

# The generic program phrase. Seen WITHOUT a specific center name, it is a
# signal for human review (an alias we don't know yet), not a match.
_GENERIC_NQISRC = re.compile(
    r"national\s+quantum\s+information\s+science\s+research\s+cent(?:er|re)s?",
    re.IGNORECASE,
)

# Unicode dashes (non-breaking hyphen, en/em dash, minus) -> ASCII hyphen.
_DASHES = re.compile("[‐‑‒–—―−]")


def _normalize(text):
    # NFC first -- same lesson as the exclusions filename bug (composed vs
    # decomposed forms compare unequal while looking identical).
    text = unicodedata.normalize("NFC", text)
    return _DASHES.sub("-", text)


def derive_centers(text):
    """Return a list of canonical center codes found in `text`, or None if
    there is no usable text. See module docstring for the convention."""
    if isinstance(text, (list, dict)):
        # Defensive: Pass 1 is asked for a string, but a list/dict would
        # otherwise be silently misread as "no text".
        import json
        text = json.dumps(text, ensure_ascii=False)
    if text is None or not isinstance(text, str) or not text.strip():
        return None
    norm = _normalize(text)
    found = [
        code for code in CENTER_ORDER
        if any(p.search(norm) for p in _COMPILED[code])
    ]
    return found


def centers_for_record(record):
    """Record-level convention -- what build_sqlite.py should call.

      None  -> no Pass 1 output at all (failed ingestion, e.g. oversized PDF):
               genuinely unknown.
      []    -> Pass 1 ran: either the acknowledgment names none of the five
               centers, or the paper has no acknowledgment at all. Both mean
               "none" for filtering purposes.
      [...] -> canonical codes.
    """
    rj = record.get("relevance_json") if isinstance(record, dict) else None
    if not isinstance(rj, dict) or not rj:
        return None
    codes = derive_centers(rj.get("funding_acknowledgments"))
    return [] if codes is None else codes


def needs_review(text):
    """True when `text` matched no center but contains signals a human should
    look at: the generic NQISRC program phrase, or the word 'center'/'centre'
    near 'quantum'. Surfaces missing aliases -- a wrongly-unmatched paper
    otherwise produces no symptom at all (asymmetric curation errors)."""
    codes = derive_centers(text)
    if codes is None or codes:
        return False
    norm = _normalize(text)
    if _GENERIC_NQISRC.search(norm):
        return True
    return bool(re.search(r"quantum[^;]{0,60}cent(?:er|re)|cent(?:er|re)[^;]{0,60}quantum",
                          norm, re.IGNORECASE))


def display_string(codes):
    """Human-readable form for the Explorer / papers.acknowledged_centers_display."""
    if codes is None:
        return "unknown"
    return ", ".join(codes) if codes else "none"
