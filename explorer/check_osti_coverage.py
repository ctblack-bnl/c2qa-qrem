#!/usr/bin/env python3
"""
check_osti_coverage.py — Check what fraction of the ingested corpus is available on OSTI/DOE PAGES.

Search strategy (in priority order):
  1. DOI lookup on main OSTI API (osti.gov/api/v1) — fast, reliable
  2. Title + author fallback on main OSTI API — catches papers where DOI not registered
     User approval required for fallback matches.

The main OSTI API (osti.gov/api/v1) supports both DOI and title+author search,
and returns fulltext links (servlets/purl/) directly. The PAGES-specific endpoint
(osti.gov/pages/api/v1) is DOI-only and is a subset of the main API.

Legal basis: DOE retains a license in all works produced under DOE funding.
DOE PAGES users may read, download, and analyze material by virtue of these
reserved rights. Machine access is explicitly supported via the API.

Usage:
    python3 check_osti_coverage.py
    python3 check_osti_coverage.py --records path/to/records.jsonl
    python3 check_osti_coverage.py --out results.json
    python3 check_osti_coverage.py --no-interactive  (auto-accept first fallback result)
"""

import argparse
import json
import time
import sys
from pathlib import Path
from typing import Optional, Tuple

import requests

OSTI_API     = "https://www.osti.gov/api/v1/records"
OSTI_PURL_PREFIX = "https://www.osti.gov/servlets/purl/"
OSTI_BIB_BASE    = "https://www.osti.gov/biblio/"
DEFAULT_LEDGER  = "../data/ingested/processed_ledger.json"
DEFAULT_RECORDS = "../data/ingested/records.jsonl"
DEFAULT_OUT     = "osti_coverage_results.json"
RATE_LIMIT_DELAY = 0.5   # seconds between API calls


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_papers_from_ledger(path: str) -> list:
    with open(path) as f:
        ledger = json.load(f)
    papers = []
    for e in ledger.get("processed", []):
        papers.append({
            "filename": e.get("filename", ""),
            "doi":      e.get("doi"),
            "title":    None,
            "authors":  None,
            "outcome":  e.get("outcome", ""),
        })
    return papers


def load_papers_from_records(path: str) -> list:
    seen = set()
    papers = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("outcome") == "skipped":
                continue
            doi      = record.get("doi")
            title    = record.get("title")
            authors  = record.get("authors", "")
            filename = record.get("filename", "")
            key = doi if doi else filename
            if key in seen:
                continue
            seen.add(key)
            papers.append({
                "filename": filename,
                "doi":      doi,
                "title":    title,
                "authors":  authors,
                "outcome":  record.get("outcome", ""),
            })
    return papers


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def normalize_doi(doi: Optional[str]) -> str:
    if not doi:
        return ""
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def is_arxiv(paper: dict) -> bool:
    doi   = (paper.get("doi") or "").lower()
    fname = (paper.get("filename") or "").lower()
    return doi.startswith("10.48550/arxiv") or "arxiv" in fname


def parse_first_author(authors_str: Optional[str]) -> Optional[str]:
    """Extract first author surname from 'Bland et al., 2025'."""
    if not authors_str:
        return None
    import re
    m = re.match(r'^([A-Za-z\-]+)', authors_str.strip())
    return m.group(1) if m else None


def classify_links(links: list) -> Tuple[str, Optional[str]]:
    """
    Given a links array from an OSTI record, return (status, fulltext_url).
    Status: 'fulltext' | 'metadata'
    """
    for link in links:
        if link.get("rel") == "fulltext":
            href = link.get("href", "")
            if href.startswith(OSTI_PURL_PREFIX):
                return "fulltext", href
            else:
                return "metadata", href
    return "metadata", None


# ---------------------------------------------------------------------------
# OSTI API queries
# ---------------------------------------------------------------------------

def query_by_doi(doi: str) -> Optional[dict]:
    """Primary lookup — DOI search on main OSTI API."""
    bare = normalize_doi(doi)
    if not bare:
        return None
    try:
        resp = requests.get(OSTI_API, params={"doi": bare}, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        return results[0] if results else None
    except requests.RequestException as e:
        print(f"  OSTI API error: {e}", file=sys.stderr)
        return None


def query_by_title_author(title: Optional[str],
                          author: Optional[str],
                          rows: int = 3) -> Optional[list]:
    """Fallback — title + author search on main OSTI API. Returns list of candidates."""
    if not title and not author:
        return None
    params = {"rows": rows}
    if title:
        # Use first 6 words to avoid overly specific queries
        words = title.split()[:6]
        params["title"] = " ".join(words)
    if author:
        params["author"] = author
    try:
        resp = requests.get(OSTI_API, params=params, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        return results if results else None
    except requests.RequestException as e:
        print(f"  OSTI API error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# User approval prompt
# ---------------------------------------------------------------------------

def ask_user_approve(paper_filename: str,
                     paper_title: Optional[str],
                     candidates: list,
                     method: str) -> Optional[dict]:
    """Show candidates and ask user to approve one. Returns chosen record or None."""
    print(f"\n  {'─'*55}")
    print(f"  Corpus paper : {Path(paper_filename).name}")
    print(f"  Title        : {paper_title or '(no title)'}")
    print(f"  Search method: {method}")
    print(f"\n  Candidates found on OSTI:")
    for i, c in enumerate(candidates, 1):
        status, url = classify_links(c.get("links", []))
        pub_date = c.get("publication_date", "")[:10]
        print(f"\n  [{i}] OSTI:{c.get('osti_id')}  ({pub_date})  [{status}]")
        print(f"      Title  : {c.get('title','')[:80]}")
        authors = c.get("authors", [])
        if isinstance(authors, list):
            auth_str = ", ".join(authors[:3])
        else:
            auth_str = str(authors)
        print(f"      Authors: {auth_str}")
        print(f"      Journal: {c.get('journal_name','')}")
        if url:
            print(f"      PDF    : {url}")
        else:
            print(f"      Bib    : {OSTI_BIB_BASE}{c.get('osti_id','')}")

    print(f"\n  Enter number to accept, 's' to skip, 'n' for none: ", end="", flush=True)
    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Interrupted — skipping.")
        return None

    if choice in ('s', ''):
        print("  → Skipped")
        return None
    elif choice == 'n':
        print("  → None of these")
        return None
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                print(f"  → Accepted: OSTI:{chosen.get('osti_id')}")
                return chosen
            else:
                print("  → Invalid choice — skipping")
                return None
        except ValueError:
            print("  → Invalid input — skipping")
            return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check OSTI/DOE PAGES coverage of ingested corpus")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ledger",  default=None)
    group.add_argument("--records", default=None)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--no-interactive", action="store_true",
                        help="Auto-accept first fallback result without prompting")
    args = parser.parse_args()

    # Load papers
    if args.records:
        papers = load_papers_from_records(args.records)
        print(f"Loaded from records.jsonl: {args.records}")
    elif args.ledger:
        papers = load_papers_from_ledger(args.ledger)
        print(f"Loaded from ledger: {args.ledger}")
    else:
        rp = Path(DEFAULT_RECORDS)
        lp = Path(DEFAULT_LEDGER)
        if rp.exists():
            print(f"Auto-detected: {rp}")
            papers = load_papers_from_records(str(rp))
        elif lp.exists():
            print(f"Auto-detected: {lp}")
            papers = load_papers_from_ledger(str(lp))
        else:
            print("ERROR: no records file found.", file=sys.stderr)
            sys.exit(1)

    total = len(papers)

    # Separate arXiv-sourced papers
    arxiv_papers = [p for p in papers if is_arxiv(p)]
    non_arxiv    = [p for p in papers if not is_arxiv(p)]
    has_doi      = [p for p in non_arxiv if p.get("doi")]
    no_doi       = [p for p in non_arxiv if not p.get("doi")]

    print(f"\nTotal papers: {total}")
    print(f"  Already arXiv-sourced (skipping): {len(arxiv_papers)}")
    print(f"  Non-arXiv papers: {len(non_arxiv)}")
    print(f"    With DOI:    {len(has_doi)}")
    print(f"    Without DOI: {len(no_doi)}")
    print(f"\nQuerying OSTI API for {len(non_arxiv)} non-arXiv papers...\n")

    results = []

    for i, paper in enumerate(non_arxiv, 1):
        doi      = paper.get("doi")
        title    = paper.get("title")
        authors  = paper.get("authors")
        filename = paper.get("filename", "")
        short    = Path(filename).name[:55] if filename else "unknown"

        print(f"[{i:3d}/{len(non_arxiv)}] {short}", flush=True)

        osti_record = None
        method      = None

        # --- Strategy 1: DOI lookup ---
        if doi:
            time.sleep(RATE_LIMIT_DELAY)
            osti_record = query_by_doi(doi)
            if osti_record:
                method = "doi"
                status, url = classify_links(osti_record.get("links", []))
                symbol = "✓" if status == "fulltext" else "~"
                print(f"  {symbol} Found via DOI [{status}]: {osti_record.get('title','')[:60]}", flush=True)
            else:
                print(f"  ~ DOI not found — trying title+author fallback...", flush=True)

        # --- Strategy 2: title + author fallback ---
        if not osti_record:
            first_author = parse_first_author(authors)
            if title or first_author:
                time.sleep(RATE_LIMIT_DELAY)
                candidates = query_by_title_author(title, first_author, rows=3)
                if candidates:
                    print(f"  ~ Fallback found {len(candidates)} candidate(s)", flush=True)
                    if args.no_interactive:
                        osti_record = candidates[0]
                        method = "title_author_auto"
                        status, url = classify_links(osti_record.get("links", []))
                        print(f"    Auto-accepted: OSTI:{osti_record.get('osti_id')} [{status}]", flush=True)
                    else:
                        osti_record = ask_user_approve(filename, title, candidates, "title+author")
                        method = "title_author" if osti_record else None
                else:
                    print(f"  ✗ Not found on OSTI", flush=True)
            else:
                print(f"  ✗ No DOI, title, or author to search", flush=True)

        if not osti_record:
            print(f"  ✗ Not found on OSTI", flush=True)

        # Classify final result
        if osti_record:
            status, fulltext_url = classify_links(osti_record.get("links", []))
        else:
            status, fulltext_url = "not_found", None

        results.append({
            "filename":     filename,
            "doi":          doi,
            "title":        title,
            "authors":      authors,
            "outcome":      paper.get("outcome", ""),
            "pages_status": status,
            "search_method": method,
            "fulltext_url": fulltext_url,
            "osti_id":      osti_record.get("osti_id") if osti_record else None,
            "osti_title":   osti_record.get("title")   if osti_record else None,
            "article_type": osti_record.get("article_type") if osti_record else None,
            "needs_verification": method in ("title_author_auto",),
        })

    # Add arXiv-sourced papers
    for paper in arxiv_papers:
        results.append({
            "filename":     paper["filename"],
            "doi":          paper.get("doi"),
            "title":        paper.get("title"),
            "authors":      paper.get("authors"),
            "outcome":      paper.get("outcome", ""),
            "pages_status": "arxiv_sourced",
            "search_method": None,
            "fulltext_url": None,
            "osti_id":      None,
            "osti_title":   None,
            "article_type": None,
            "needs_verification": False,
        })

    # Add no-DOI papers that weren't searched (already handled above via fallback)
    # (no_doi papers are included in non_arxiv loop — nothing extra needed)

    # Summary
    n_fulltext   = sum(1 for r in results if r["pages_status"] == "fulltext")
    n_metadata   = sum(1 for r in results if r["pages_status"] == "metadata")
    n_not_found  = sum(1 for r in results if r["pages_status"] == "not_found")
    n_no_doi     = sum(1 for r in results if r["pages_status"] == "no_doi")
    n_arxiv      = sum(1 for r in results if r["pages_status"] == "arxiv_sourced")
    n_non_arxiv  = total - n_arxiv

    # Method breakdown
    n_doi_found    = sum(1 for r in results if r.get("search_method") == "doi")
    n_fallback     = sum(1 for r in results if r.get("search_method") in ("title_author", "title_author_auto"))

    print("\n" + "="*60)
    print("OSTI COVERAGE SUMMARY")
    print("="*60)
    print(f"Total papers in corpus:            {total}")
    print(f"  Already arXiv-sourced:           {n_arxiv:3d}  ({100*n_arxiv/total:.1f}%)")
    print(f"\nOf {n_non_arxiv} non-arXiv papers:")
    if n_non_arxiv:
        print(f"  ✓ Full text on OSTI (PDF):       {n_fulltext:3d}  ({100*n_fulltext/n_non_arxiv:.1f}%)")
        print(f"      via DOI:                     {n_doi_found}")
        print(f"      via title+author fallback:   {n_fallback}")
        print(f"  ~ On OSTI, metadata only:        {n_metadata:3d}  ({100*n_metadata/n_non_arxiv:.1f}%)")
        print(f"  ✗ Not found on OSTI:             {n_not_found:3d}  ({100*n_not_found/n_non_arxiv:.1f}%)")
    print("="*60)

    not_found = [r for r in results if r["pages_status"] == "not_found"]
    if not_found:
        print(f"\nNot found on OSTI ({len(not_found)}):")
        for r in not_found:
            print(f"  {Path(r['filename']).name if r['filename'] else 'unknown'}  [{r.get('doi','no DOI')}]")

    needs_verify = [r for r in results if r.get("needs_verification")]
    if needs_verify:
        print(f"\nAuto-accepted fallbacks — please verify ({len(needs_verify)}):")
        for r in needs_verify:
            print(f"  {Path(r['filename']).name}")
            print(f"    OSTI title: {r.get('osti_title','')[:70]}")

    with open(args.out, "w") as f:
        json.dump({
            "summary": {
                "total":         total,
                "arxiv_sourced": n_arxiv,
                "fulltext":      n_fulltext,
                "metadata_only": n_metadata,
                "not_found":     n_not_found,
            },
            "results": results,
        }, f, indent=2)
    print(f"\nResults written to: {args.out}")


if __name__ == "__main__":
    main()
