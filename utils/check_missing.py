#!/usr/bin/env python3
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ledger = json.load(open(os.path.join(ROOT, 'data/ingested/processed_ledger.json')))
entries = {os.path.basename(e['filename']): e for e in ledger.get('processed', []) if e.get('filename')}

not_in_db = [
    '2025-Nanophotonics-Yang.pdf',
    '2025-NatComm-Ding.pdf',
    '2025-PRA-Dai.pdf',
    '2025-PRL-Chang.pdf',
    '2025-PRL-Hazra.pdf',
    '2025-PRLApplied-Wu.pdf',
    '2025-PRXQuantum-Hays.pdf',
    '2025-PRXQuantum-Maiti.pdf',
    '2025-PhysRevB-Lambert.pdf',
    '2025-PhysRevLett-Delord.pdf',
    '2025-arXiv-Dakkis.pdf',
    '2025-arXiv-Shao.pdf',
    '2025-arXiv-Yang.pdf',
    '2026-NatPhotonics-Zhou.pdf',
    '2026-NatPhys-Yang.pdf',
    '2026-PRXQuantum-Hardy.pdf',
    '2026-PhysRevB-Nangoi.pdf',
    '2026-PhysRevB-Turiansky.pdf',
    '2026-Small-Wehmeier.pdf',
    '2026-Vacuum-Chattaraj.pdf',
    '2026-arXiv-Marcenac.pdf',
    '2026-arXiv-WangX.pdf',
    '2026-arXiv-Yama.pdf',
]

print(f"{'Filename':<45} {'Status':<15} Outcome")
print('-' * 100)
for fname in sorted(not_in_db):
    if fname in entries:
        e = entries[fname]
        print(f"{fname:<45} {'in ledger':<15} {e.get('outcome','?')} — {e.get('reason','')}")
    else:
        print(f"{fname:<45} {'NOT IN LEDGER':<15} never processed")
