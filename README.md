# C2QA Materials Explorer Pipeline

A pipeline for automatically extracting structured materials characterization 
data from scientific publications into a searchable, queryable database.

**Live database: https://c2qa-materials-explorer.onrender.com** — browse 
without installing anything.

---

## What this repository contains

**[Materials Explorer](explorer/)** — the primary tool described in this 
repository. Reads scientific papers (PDFs) and automatically extracts 
structured characterization records (T1, T2, Tc, RRR, loss tangent, and 
~50 other fields) into a searchable database with a browser-based UI.

**[Baby QREM](qrem/)** — a connected quantum resource estimator. Given a 
quantum circuit and a qubit hardware profile, it estimates how many physical 
qubits are needed and how that changes as materials improve. Records from the 
Explorer with device performance data (T1, T2) can be projected directly into 
Baby QREM hardware profiles.

---

## Getting started

**To browse the materials database** — go to 
https://c2qa-materials-explorer.onrender.com. No installation needed.

**To run the Explorer locally or ingest your own papers** — see 
[explorer/README.md](explorer/README.md).

**To run Baby QREM** — see [qrem/README.md](qrem/README.md).

---

## Citation

If you use the Materials Explorer Pipeline in your work, please cite:

> Black, C.T. "A General Pipeline for Digesting Scientific Literature into 
> a Shared Scientific Knowledge Base." arXiv:2606.27384 (2026).
> https://arxiv.org/abs/2606.27384

---

*C2QA Materials Explorer Pipeline — June 2026*  
*Developed in collaboration between C2QA center director and Claude (Anthropic)*