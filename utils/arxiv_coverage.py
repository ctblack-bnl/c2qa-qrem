#!/usr/bin/env python3
"""
For each publisher-version paper in the DB, check if an arXiv replacement
exists in utils/new_arxiv/ by matching author surname.
"""
import os, sqlite3, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, 'data/ingested/records.db')
ARXIV_DIR = os.path.join(ROOT, 'utils/new_arxiv')

PUBLISHER_JOURNALS = [
    'Nature', 'NatComm', 'NatPhotonics', 'NatPhys', 'PhysRev', 'PRX', 'PRL',
    'PRB', 'PRA', 'PRD', 'PNAS', 'NanoLett', 'Small', 'Vacuum', 'Quantum',
    'AdvQuantumTech', 'CommPhys', 'JHEP', 'JPhys', 'AIChE', 'InorganicChem',
    'Nanophotonics', 'JStatMech', 'SmallMethods'
]

def is_publisher(fname):
    return any(j.lower() in fname.lower() for j in PUBLISHER_JOURNALS)

def extract_author(fname):
    """Extract author surname from e.g. 2025-Nature-Bland.pdf -> bland"""
    parts = os.path.splitext(fname)[0].split('-')
    return parts[-1].lower() if len(parts) >= 3 else ''

# Load arXiv files available, keyed by author surname
arxiv_available = {}
for fname in os.listdir(ARXIV_DIR):
    if fname.lower().endswith('.pdf'):
        author = extract_author(fname)
        arxiv_available.setdefault(author, []).append(fname)

# Load publisher papers from DB
conn = sqlite3.connect(DB_PATH)
rows = conn.execute('SELECT filename, title, doi FROM papers WHERE outcome="ingested"').fetchall()
conn.close()

publisher_papers = [(f, t, d) for f, t, d in rows if is_publisher(f)]

have_arxiv = []
need_arxiv = []

for fname, title, doi in sorted(publisher_papers):
    author = extract_author(fname)
    matches = arxiv_available.get(author, [])
    if matches:
        have_arxiv.append((fname, title, doi, matches))
    else:
        need_arxiv.append((fname, title, doi))

print(f"\n{'='*70}")
print(f"HAVE arXiv replacement ({len(have_arxiv)} papers):")
print(f"{'='*70}")
for fname, title, doi, matches in have_arxiv:
    print(f"  {fname}")
    print(f"  title: {title}")
    print(f"  doi:   {doi}")
    for m in matches:
        print(f"  arxiv: {m}")
    print()

print(f"\n{'='*70}")
print(f"STILL NEED arXiv version ({len(need_arxiv)} papers):")
print(f"{'='*70}")
for fname, title, doi in need_arxiv:
    print(f"  {fname}")
    print(f"  title: {title}")
    print(f"  doi:   {doi}")
    print()