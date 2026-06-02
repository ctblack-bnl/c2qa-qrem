#!/usr/bin/env python3
"""
check_arxiv_coverage.py — Check what fraction of the ingested corpus is available on arXiv.

Search strategy (in priority order):
  1. arXiv ID in filename — instant, no API call (e.g. 2503.14798.pdf)
  2. DOI search — reliable when author registered DOI on arXiv submission
  3. Author + year search — catches papers where DOI not registered (most common gap)
     e.g. "Bland et al., 2025" -> au:Bland AND submittedDate:[20250101 TO 20251231]
  4. Title keyword search — last resort, flagged for human verification

For strategies 3 and 4, the script pauses and asks for human approval before
recording a match, since these are less reliable.

Usage:
    python3 check_arxiv_coverage.py --osti-results osti_coverage_results.json
    python3 check_arxiv_coverage.py --records ../data/ingested/records.jsonl
    python3 check_arxiv_coverage.py --osti-results osti_coverage_results.json --out results.json
"""

import argparse
import json
import re
import time
import sys
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF_BASE = "https://arxiv.org/pdf/"
ARXIV_ABS_BASE = "https://arxiv.org/abs/"
DEFAULT_RECORDS = "../data/ingested/records.jsonl"
DEFAULT_OUT = "arxiv_coverage_results.json"
DEFAULT_COMBINED_OUT = "combined_coverage_results.json"

# 5s base delay between API calls; exponential backoff on 429
RATE_LIMIT_DELAY = 5.0
MAX_RETRIES = 4

NS = {"atom": "http://www.w3.org/2005/Atom",
      "arxiv": "http://arxiv.org/schemas/atom"}

ARXIV_ID_RE = re.compile(r'(\d{4}\.\d{4,5})(v\d+)?')


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_papers_from_records(path: str) -> list:
    """Load papers from records.jsonl, deduplicated by DOI or filename."""
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
            doi = record.get("doi")
            title = record.get("title")
            authors = record.get("authors", "")  # e.g. "Bland et al., 2025"
            filename = record.get("filename", "")
            key = doi if doi else filename
            if key in seen:
                continue
            seen.add(key)
            papers.append({
                "filename": filename,
                "doi": doi,
                "title": title,
                "authors": authors,
            })
    return papers


def load_osti_results(path: str) -> tuple:
    """Returns (by_doi dict, set of DOIs with PAGES fulltext, set of arxiv-sourced DOIs)."""
    with open(path) as f:
        data = json.load(f)
    by_doi = {}
    fulltext_dois = set()
    arxiv_sourced_dois = set()
    for r in data.get("results", []):
        doi = normalize_doi(r.get("doi", ""))
        status = r.get("pages_status", "")
        if doi:
            by_doi[doi] = r
            if status == "fulltext":
                fulltext_dois.add(doi)
            if status == "arxiv_sourced":
                arxiv_sourced_dois.add(doi)
    return by_doi, fulltext_dois, arxiv_sourced_dois


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
    return doi.lower()


def extract_arxiv_id_from_filename(filename: str) -> Optional[str]:
    if not filename:
        return None
    m = ARXIV_ID_RE.search(Path(filename).stem)
    return m.group(1) if m else None


def parse_author_year(authors_str: str) -> tuple:
    """
    Parse "Bland et al., 2025" -> ("Bland", "2025").
    Returns (None, None) if unparseable.
    """
    if not authors_str:
        return None, None
    # Match "Lastname et al., YYYY" or "Lastname, YYYY"
    m = re.match(r'^([A-Za-z\-]+)\s+(?:et al\.,?\s*)?(\d{4})', authors_str.strip())
    if m:
        return m.group(1), m.group(2)
    # Try just extracting a 4-digit year anywhere
    m_year = re.search(r'(\d{4})', authors_str)
    m_name = re.match(r'^([A-Za-z\-]+)', authors_str.strip())
    if m_name and m_year:
        return m_name.group(1), m_year.group(1)
    return None, None


def title_keywords(title: str, n: int = 4) -> str:
    """Extract n most distinctive words from title for keyword search."""
    if not title:
        return ""
    stopwords = {'a', 'an', 'the', 'of', 'in', 'for', 'and', 'or', 'with',
                 'on', 'at', 'to', 'by', 'from', 'as', 'is', 'are', 'was'}
    words = [w for w in re.findall(r'[A-Za-z]{3,}', title)
             if w.lower() not in stopwords]
    return ' '.join(words[:n])


# ---------------------------------------------------------------------------
# arXiv API
# ---------------------------------------------------------------------------

def _query_arxiv(search_query: str) -> Optional[dict]:
    """
    Execute arXiv API query with exponential backoff on 429.
    Returns parsed result dict or None.
    """
    params = urllib.parse.urlencode({
        "search_query": search_query,
        "max_results": 3,  # fetch a few so user can pick
        "sortBy": "relevance",
    })
    url = f"{ARXIV_API}?{params}"

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                body = resp.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = RATE_LIMIT_DELAY * (2 ** attempt)
                print(f"\n  429 rate limited — waiting {wait:.0f}s...", file=sys.stderr)
                time.sleep(wait)
                if attempt == MAX_RETRIES - 1:
                    print("  giving up.", file=sys.stderr)
                    return None
            else:
                print(f"\n  HTTP error: {e}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"\n  arXiv API error: {e}", file=sys.stderr)
            return None

    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        print(f"\n  XML parse error: {e}", file=sys.stderr)
        return None

    entries = root.findall("atom:entry", NS)
    if not entries:
        return None

    # Return list of candidates for user review
    candidates = []
    for entry in entries:
        id_elem = entry.find("atom:id", NS)
        if id_elem is None or not id_elem.text:
            continue
        m = ARXIV_ID_RE.search(id_elem.text.strip())
        if not m:
            continue
        arxiv_id = m.group(1)
        title_elem = entry.find("atom:title", NS)
        arxiv_title = title_elem.text.strip().replace("\n", " ") if title_elem is not None else ""
        authors_elems = entry.findall("atom:author", NS)
        arxiv_authors = ", ".join(
            a.find("atom:name", NS).text
            for a in authors_elems[:3]
            if a.find("atom:name", NS) is not None
        )
        published_elem = entry.find("atom:published", NS)
        published = published_elem.text[:10] if published_elem is not None else ""
        candidates.append({
            "arxiv_id": arxiv_id,
            "title": arxiv_title,
            "authors": arxiv_authors,
            "published": published,
            "pdf_url": f"{ARXIV_PDF_BASE}{arxiv_id}",
            "abs_url": f"{ARXIV_ABS_BASE}{arxiv_id}",
        })

    return candidates if candidates else None


def query_by_doi(doi: str) -> Optional[list]:
    bare = normalize_doi(doi)
    if not bare:
        return None
    return _query_arxiv(f"doi:{bare}")


def query_by_author_year(author: str, year: str, title: str = "") -> Optional[list]:
    """Author + year + optional title keywords."""
    query = f"au:{author} AND submittedDate:[{year}0101 TO {year}1231]"
    if title:
        kw = title_keywords(title, 3)
        if kw:
            query += f" AND ti:{kw}"
    return _query_arxiv(query)


def query_by_title_keywords(title: str) -> Optional[list]:
    kw = title_keywords(title, 5)
    if not kw:
        return None
    return _query_arxiv(f"ti:{kw}")


# ---------------------------------------------------------------------------
# User approval prompt
# ---------------------------------------------------------------------------

def ask_user_approve(paper_filename: str, paper_title: str,
                     candidates: list, method: str) -> Optional[dict]:
    """
    Show candidates to user and ask for approval.
    Returns approved candidate dict, or None if rejected/skipped.
    """
    print(f"\n  {'─'*55}")
    print(f"  Corpus paper : {Path(paper_filename).name}")
    print(f"  Title        : {paper_title or '(no title)'}")
    print(f"  Search method: {method}")
    print(f"\n  Candidates found:")
    for i, c in enumerate(candidates, 1):
        print(f"\n  [{i}] arXiv:{c['arxiv_id']}  ({c['published']})")
        print(f"      Title  : {c['title'][:80]}")
        print(f"      Authors: {c['authors']}")
        print(f"      URL    : {c['abs_url']}")

    print(f"\n  Enter number to accept, 's' to skip, 'n' for none: ", end="", flush=True)

    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Interrupted — skipping.")
        return None

    if choice == 's' or choice == '':
        print("  → Skipped (will review later)")
        return None
    elif choice == 'n':
        print("  → None of these — marking not found")
        return None
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                print(f"  → Accepted: arXiv:{chosen['arxiv_id']}")
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
    parser = argparse.ArgumentParser(description="Check arXiv coverage of ingested corpus")
    parser.add_argument("--records", default=None, help="Path to records.jsonl")
    parser.add_argument("--osti-results", default=None,
                        help="Path to osti_coverage_results.json")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--combined-out", default=DEFAULT_COMBINED_OUT)
    parser.add_argument("--no-interactive", action="store_true",
                        help="Skip user approval prompts (auto-accept first candidate)")
    args = parser.parse_args()

    # Load OSTI results
    osti_fulltext_dois = set()
    osti_arxiv_dois = set()
    osti_results_raw = None
    if args.osti_results:
        print(f"Loading OSTI results from: {args.osti_results}")
        _, osti_fulltext_dois, osti_arxiv_dois = load_osti_results(args.osti_results)
        with open(args.osti_results) as f:
            osti_results_raw = json.load(f)
        print(f"  {len(osti_fulltext_dois)} papers on PAGES — will skip")
        print(f"  {len(osti_arxiv_dois)} already arXiv-sourced — will skip")

    # Load papers
    records_path = args.records or DEFAULT_RECORDS
    if not Path(records_path).exists():
        print(f"ERROR: records file not found: {records_path}", file=sys.stderr)
        sys.exit(1)
    print(f"\nLoading papers from: {records_path}")
    all_papers = load_papers_from_records(records_path)

    # Filter: skip PAGES fulltext and already-arXiv-sourced
    skip_dois = osti_fulltext_dois | osti_arxiv_dois
    to_check = []
    skipped = []
    for p in all_papers:
        doi_norm = normalize_doi(p.get("doi", ""))
        if doi_norm and doi_norm in skip_dois:
            skipped.append(p)
        else:
            to_check.append(p)

    print(f"\nTotal papers in corpus:     {len(all_papers)}")
    print(f"  Skipping (PAGES/arXiv):   {len(skipped)}")
    print(f"  To check on arXiv:        {len(to_check)}")
    est = len(to_check) * RATE_LIMIT_DELAY * 2 / 60
    print(f"\nQuerying arXiv (est. ~{est:.0f} min — longer if fallbacks needed)...\n")

    results = []

    for i, paper in enumerate(to_check, 1):
        doi = paper.get("doi")
        title = paper.get("title", "")
        authors_str = paper.get("authors", "")
        filename = paper.get("filename", "")
        short_name = Path(filename).name[:50] if filename else "unknown"

        print(f"[{i:3d}/{len(to_check)}] {short_name}", flush=True)

        arxiv_result = None
        method = None

        # --- Strategy 1: arXiv ID in filename ---
        arxiv_id_from_file = extract_arxiv_id_from_filename(filename)
        if arxiv_id_from_file:
            arxiv_result = {
                "arxiv_id": arxiv_id_from_file,
                "title": title,
                "authors": authors_str,
                "published": "",
                "pdf_url": f"{ARXIV_PDF_BASE}{arxiv_id_from_file}",
                "abs_url": f"{ARXIV_ABS_BASE}{arxiv_id_from_file}",
            }
            method = "filename"
            print(f"  ✓ arXiv ID in filename: {arxiv_id_from_file}", flush=True)

        # --- Strategy 2: DOI search ---
        elif doi:
            time.sleep(RATE_LIMIT_DELAY)
            candidates = query_by_doi(doi)
            if candidates:
                # DOI match is reliable — auto-accept first result, no prompt needed
                arxiv_result = candidates[0]
                method = "doi"
                print(f"  ✓ Found via DOI: arXiv:{arxiv_result['arxiv_id']}", flush=True)
                print(f"    Title: {arxiv_result['title'][:70]}", flush=True)
            else:
                print(f"  ~ DOI search: no match", flush=True)

                # --- Strategy 3: Author + year ---
                author, year = parse_author_year(authors_str)
                if author and year:
                    time.sleep(RATE_LIMIT_DELAY)
                    candidates = query_by_author_year(author, year, title)
                    if candidates:
                        print(f"  ~ Author+year search found {len(candidates)} candidate(s)", flush=True)
                        if args.no_interactive:
                            arxiv_result = candidates[0]
                            method = "author_year_auto"
                            print(f"    Auto-accepted: arXiv:{arxiv_result['arxiv_id']}", flush=True)
                        else:
                            arxiv_result = ask_user_approve(filename, title, candidates, "author+year")
                            method = "author_year" if arxiv_result else None
                    else:
                        print(f"  ~ Author+year: no match", flush=True)

                        # --- Strategy 4: Title keywords ---
                        if title:
                            time.sleep(RATE_LIMIT_DELAY)
                            candidates = query_by_title_keywords(title)
                            if candidates:
                                print(f"  ~ Title keyword search found {len(candidates)} candidate(s)", flush=True)
                                if args.no_interactive:
                                    arxiv_result = candidates[0]
                                    method = "title_auto"
                                    print(f"    Auto-accepted: arXiv:{arxiv_result['arxiv_id']}", flush=True)
                                else:
                                    arxiv_result = ask_user_approve(filename, title, candidates, "title keywords")
                                    method = "title" if arxiv_result else None
                            else:
                                print(f"  ✗ Not found on arXiv", flush=True)
                        else:
                            print(f"  ✗ No title for fallback search", flush=True)

        # --- No DOI: go straight to author+year ---
        else:
            author, year = parse_author_year(authors_str)
            if author and year:
                time.sleep(RATE_LIMIT_DELAY)
                candidates = query_by_author_year(author, year, title)
                if candidates:
                    print(f"  ~ Author+year search found {len(candidates)} candidate(s)", flush=True)
                    if args.no_interactive:
                        arxiv_result = candidates[0]
                        method = "author_year_auto"
                    else:
                        arxiv_result = ask_user_approve(filename, title, candidates, "author+year (no DOI)")
                        method = "author_year" if arxiv_result else None
                else:
                    print(f"  ✗ Not found (no DOI, author+year search failed)", flush=True)
            else:
                print(f"  ✗ Not found (no DOI, could not parse author/year)", flush=True)

        if not arxiv_result and method is None:
            print(f"  ✗ Not found on arXiv", flush=True)

        results.append({
            "filename": filename,
            "doi": doi,
            "title": title,
            "authors": authors_str,
            "arxiv_status": "found" if arxiv_result else "not_found",
            "search_method": method,
            "arxiv_id": arxiv_result["arxiv_id"] if arxiv_result else None,
            "arxiv_pdf_url": arxiv_result["pdf_url"] if arxiv_result else None,
            "arxiv_abs_url": arxiv_result["abs_url"] if arxiv_result else None,
            "arxiv_title": arxiv_result["title"] if arxiv_result else None,
            "needs_verification": method in ("author_year_auto", "title_auto"),
        })

    # Summary
    n_found = sum(1 for r in results if r["arxiv_status"] == "found")
    by_method = {}
    for r in results:
        if r["arxiv_status"] == "found":
            m = r["search_method"] or "unknown"
            by_method[m] = by_method.get(m, 0) + 1
    n_not_found = sum(1 for r in results if r["arxiv_status"] == "not_found")

    print("\n" + "="*60)
    print("arXiv COVERAGE SUMMARY")
    print("="*60)
    print(f"Papers checked: {len(to_check)}")
    print(f"  ✓ Found: {n_found}")
    for m, count in sorted(by_method.items()):
        print(f"      via {m}: {count}")
    print(f"  ✗ Not found: {n_not_found}")

    if osti_results_raw:
        osti_summary = osti_results_raw.get("summary", {})
        n_pages_fulltext = osti_summary.get("fulltext", 0)
        n_pages_metadata = osti_summary.get("metadata_only", 0)
        n_arxiv_sourced = osti_summary.get("arxiv_sourced", 0)
        total = len(all_papers)

        n_combined = n_pages_fulltext + n_arxiv_sourced + n_found
        n_neither = total - n_combined

        print(f"\n{'='*60}")
        print("COMBINED COVERAGE SUMMARY (PAGES + arXiv)")
        print("="*60)
        print(f"Total papers in corpus:          {total}")
        print(f"  ✓ Already arXiv-sourced:       {n_arxiv_sourced:3d}  ({100*n_arxiv_sourced/total:.1f}%)")
        print(f"  ✓ PAGES full text:             {n_pages_fulltext:3d}  ({100*n_pages_fulltext/total:.1f}%)")
        print(f"  ✓ arXiv (found this run):      {n_found:3d}  ({100*n_found/total:.1f}%)")
        print(f"  ─────────────────────────────────────────")
        print(f"  ✓ TOTAL open-source covered:   {n_combined:3d}  ({100*n_combined/total:.1f}%)")
        print(f"  ~ PAGES metadata only:         {n_pages_metadata:3d}  ({100*n_pages_metadata/total:.1f}%)")
        print(f"  ✗ Not found anywhere:          {n_neither:3d}  ({100*n_neither/total:.1f}%)")
        print("="*60)

    # Write results
    with open(args.out, "w") as f:
        json.dump({"results": results}, f, indent=2)
    print(f"\narXiv results written to: {args.out}")

    if osti_results_raw:
        combined = {
            "summary": {
                "total": len(all_papers),
                "arxiv_sourced": n_arxiv_sourced,
                "pages_fulltext": n_pages_fulltext,
                "pages_metadata_only": n_pages_metadata,
                "arxiv_found_this_run": n_found,
                "combined_open_source": n_combined,
                "not_found_anywhere": n_neither,
            },
            "osti_results": osti_results_raw.get("results", []),
            "arxiv_results": results,
        }
        with open(args.combined_out, "w") as f:
            json.dump(combined, f, indent=2)
        print(f"Combined results written to: {args.combined_out}")


if __name__ == "__main__":
    main()
