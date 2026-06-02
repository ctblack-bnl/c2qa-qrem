#!/usr/bin/env python3
"""Show all papers in the DB with 1 or more extracted samples."""
import sqlite3, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
conn = sqlite3.connect(os.path.join(ROOT, 'data/ingested/records.db'))
rows = conn.execute('''
    SELECT filename, title, num_samples
    FROM papers
    WHERE num_samples >= 1
    ORDER BY num_samples DESC, filename
''').fetchall()
print(f"{'Samples':<10} {'Filename':<45} Title")
print('-' * 120)
for r in rows:
    print(f"{r[2]:<10} {r[0]:<45} {r[1] or '[no title]'}")
print(f"\nTotal: {len(rows)} papers with 1+ samples")
