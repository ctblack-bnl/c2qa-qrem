#!/usr/bin/env python3
"""
Compare paper_list entries with available arXiv versions in utils/new_arxiv/.
For each paper, show the publisher version and any matching arXiv version below it.
"""
import os, sqlite3, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, 'data/ingested/records.db')
PAPERS_DIR = os.path.join(ROOT, 'data/papers')
ARXIV_DIR = os.path.join(ROOT, 'utils/new_arxiv')
OUTPUT_FILE = os.path.join(ROOT, 'utils/paper_list_matched.txt')

PUBLISHER_JOURNALS = [
    'Nature', 'NatComm', 'NatPhotonics', 'NatPhys', 'PhysRev', 'PRX', 'PRL',
    'PRB', 'PRA', 'PRD', 'PNAS', 'NanoLett', 'Small', 'Vacuum', 'Quantum',
    'AdvQuantumTech', 'CommPhys', 'JHEP', 'JPhys', 'AIChE', 'InorganicChem',
    'Nanophotonics', 'JStatMech', 'SmallMethods'
]

def source_type(fname):
    if 'arXiv' in fname or 'ariv' in fname:
        return 'arxiv'
    for j in PUBLISHER_JOURNALS:
        if j.lower() in fname.lower():
            return 'publisher'
    return 'unknown'

def extract_author(fname):
    """Extract author surname from filename e.g. 2025-Nature-Bland.pdf -> bland"""
    base = os.path.splitext(fname)[0]
    parts = base.split('-')
    if len(parts) >= 3:
        return parts[-1].lower().split('_')[0]  # handle Bland_b etc
    return ''

# Load DB titles
conn = sqlite3.connect(DB_PATH)
db_rows = {row[0]: row[1] for row in conn.execute('SELECT filename, title FROM papers') if row[0]}
conn.close()

# Load new_arxiv files, keyed by author
arxiv_files = {}
for fname in os.listdir(ARXIV_DIR):
    if fname.lower().endswith('.pdf'):
        author = extract_author(fname)
        arxiv_files.setdefault(author, []).append(fname)

# Walk papers dir, deduplicate by basename
seen = set()
papers = []
for root, dirs, files in os.walk(PAPERS_DIR):
    for fname in sorted(files):
        if fname.lower().endswith('.pdf') and fname not in seen:
            seen.add(fname)
            papers.append(fname)
papers.sort()

# Build output
lines = []
matched_arxiv = set()

for fname in papers:
    title = db_rows.get(fname, '[not in DB]') or '[no title]'
    stype = source_type(fname)
    author = extract_author(fname)
    lines.append(f"{fname}\t{title}\t{stype}")

    # Check for matching arXiv version
    matches = arxiv_files.get(author, [])
    for arxiv_fname in sorted(matches):
        arxiv_title = db_rows.get(arxiv_fname, '[not yet ingested]') or '[not yet ingested]'
        lines.append(f"  --> {arxiv_fname}\t{arxiv_title}\tarxiv_replacement")
        matched_arxiv.add(arxiv_fname)

# Report any arXiv files with no match
unmatched = []
for fname in os.listdir(ARXIV_DIR):
    if fname.lower().endswith('.pdf') and fname not in matched_arxiv:
        unmatched.append(fname)

if unmatched:
    lines.append('')
    lines.append('--- arXiv files with no matching corpus paper ---')
    for fname in sorted(unmatched):
        lines.append(f"  {fname}\t[no match found]")

with open(OUTPUT_FILE, 'w') as f:
    f.write('\n'.join(lines))

print(f"Wrote {len(papers)} corpus papers to {OUTPUT_FILE}")
print(f"Matched {len(matched_arxiv)} arXiv replacements")
print(f"Unmatched arXiv files: {len(unmatched)}")