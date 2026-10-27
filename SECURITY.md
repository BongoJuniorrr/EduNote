# Beta security status

The first beta is intended for a trusted, single-owner deployment behind the shared
owner password and HTTPS. It has **not** cleared the production dependency-security
gate. Do not interpret the prerelease or functional test results as a security certification.

The reviewed Python runtime scan dated 2026-10-28 reports 56 advisory entries across:

| Package | Bundled version | Advisory entries | Reported fixed versions |
| --- | --- | --- | --- |
| Pillow | 12.3.0 | 38 | 13.0.0 |
| lightrag-hku | 1.4.16 | 9 | 1.5.4 / 1.5.5 |
| transformers | 4.57.6 | 9 | Up to 5.10.0 required across findings |

Entries can overlap CVEs; this is not a count of unique vulnerabilities. The patch
set reduced the initial scan from 112 entries to 56, without suppressing findings.
RAGAnything currently requires LightRAG <1.5, Gradio requires Pillow <13, and tested
new Transformers releases were incompatible with the verified P100 Torch 2.4.1
runtime. Upgrading these together needs a separate runtime migration and rerunning
parser/RAG/model acceptance tests; forcing incompatible installs is not a fix.
OS packages and optional Presenton dependencies have not been comprehensively audited.

Mitigations do not close these findings: use trusted documents/models, keep remote
model code execution disabled, bind only the authenticated gateway, isolate code
execution, keep secrets private, and preserve tested backups. Avoid deploying this
legacy profile as an unrestricted public service or processing hostile documents.

To report a vulnerability, use GitHub private vulnerability reporting when enabled,
or contact the repository owner privately. Do not put passwords, API keys, private
files, or exploit details for an unpatched deployment in a public issue.
