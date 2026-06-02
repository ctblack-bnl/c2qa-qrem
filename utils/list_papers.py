#!/usr/bin/env python3
"""
List all papers in corpus (ingested + unprocessed) with title and source type.
Output: tab-delimited — filename, title, source_type (arxiv/publisher/unknown)
"""
import os, sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, 'data/ingested/records.db')
PAPERS_DIR = os.path.join(ROOT, 'data/papers')
OUTPUT_FILE = os.path.join(ROOT, 'utils/paper_list.txt')

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

# Load DB titles
conn = sqlite3.connect(DB_PATH)
db_rows = {row[0]: row[1] for row in conn.execute('SELECT filename, title FROM papers') if row[0]}
conn.close()

# Walk papers dir
seen = set()
lines = []
for root, dirs, files in os.walk(PAPERS_DIR):
    for fname in sorted(files):
        if fname.lower().endswith('.pdf') and fname not in seen:
            seen.add(fname)
            title = db_rows.get(fname, '[not in DB]')
            stype = source_type(fname)
            lines.append(f"{fname}\t{title or '[no title]'}\t{stype}")

lines.sort()

with open(OUTPUT_FILE, 'w') as f:
    f.write("filename\ttitle\tsource_type\n")
    f.write('\n'.join(lines))

print(f"Wrote {len(lines)} entries to {OUTPUT_FILE}")
print(f"  arxiv:     {sum(1 for l in lines if l.endswith('arxiv'))}")
print(f"  publisher: {sum(1 for l in lines if l.endswith('publisher'))}")
print(f"  unknown:   {sum(1 for l in lines if l.endswith('unknown'))}")