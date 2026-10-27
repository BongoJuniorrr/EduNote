# EduNote

A single-owner AI learning workspace: documents and RAG, notebooks and canvas, chat,
problem solving, guided learning, question generation, research, writing, missions,
Edu Studio, and presentations through Presenton.

**Author:** Tran Huu Vu Phuong (CSE 2025 - Vietnamese-German University)  
**Official demo:** https://edunote.thvphuong.id.vn  
**Repository:** https://github.com/BongoJuniorrr/EduNote  
**Release:** `v0.1.0-beta.1` · Linux x86-64 · first beta

> This is a prerelease for a trusted, single-owner deployment. The functional checks
> below have passed, but the legacy GPU dependency profile still has known security
> advisories. It is **not a zero-vulnerability or unrestricted production release**.
> See the security status below. The demo requires its owner's shared password.

## Run the prebuilt beta

Requirements: Linux x86-64, Docker Engine with Compose v2.30 or later, Python 3, OpenSSL,
32 GB RAM recommended, and at least 80 GB free disk for the full image set and caches.
A configured LLM provider with available quota is required for generation. Internet access is required
for initial model downloads. Model weights, datasets, personal files, and provider
credentials are deliberately not bundled. NVIDIA GPU is optional; local models
run much more slowly on CPU.

1. From the [release page](https://github.com/BongoJuniorrr/EduNote/releases/tag/v0.1.0-beta.1),
   download **all** `EduNote-0.1.0-beta.1-linux-amd64-part*.zip` assets and `SHA256SUMS`.
   Runtime images exceed GitHub's per-file limit, so they are divided across ZIPs.
2. Verify the ZIP checksums: `sha256sum --ignore-missing -c SHA256SUMS`. Extract every ZIP into the
   **same directory**. Part 1 contains this README, the launcher, and source code.
3. Run `bash start.sh`. It checks runtime-part hashes, imports the prebuilt images,
   generates a new private owner password, and starts the containers. No application
   build is needed. Keep `.env` and `.edunote-access/` private.
4. Open http://localhost:3782. Username: **owner**. Read your generated password
   locally from `.edunote-access/password.txt`. Configure LLM, embeddings, parsers,
   search, and optional TTS in Settings. LLM connection tests allow **300 seconds**;
   an upstream proxy may impose a shorter timeout.

For NVIDIA GPUs with the NVIDIA Container Toolkit, set `EMBEDDING_DEVICE=auto` in
`.env`, then run `EDUNOTE_GPU=1 bash start.sh`. CUDA 12.1 / Torch 2.4.1 was tested on
Tesla P100 hardware with driver 535. CPU is the portable default. The release does
not install or change host GPU drivers.

Presenton starts by default. Set its `PRESENTON_OPENAI_BASE_URL`,
`PRESENTON_OPENAI_API_KEY`, and `PRESENTON_OPENAI_MODEL` in `.env` before starting
slides, then recreate it after changes. Presenton's provider is configured
separately from the core Settings page. Use `EDUNOTE_SLIDES=0 bash start.sh` to
omit this optional service. Local Kokoro TTS and heavy GPU OCR require a GPU.

The default bind address is loopback. For a public domain, terminate HTTPS at your
reverse proxy and add the domain's exact Origin to `config/gateway/nginx.conf`.
All UI, API and WebSocket traffic must pass through the owner gateway. Do not
publish the backend port directly. The shared password protects one workspace;
there are no accounts, registrations, tenants, or multi-user isolation guarantees.

## Configure models and document processing

- LLM: OpenAI-compatible APIs, including vLLM, llama.cpp, Ollama/LM Studio and hosted
  endpoints; supported provider adapters can be selected in Settings.
  `LLM_COMPLETION_TRANSPORT=stream` receives completions over SSE and aggregates
  the answer internally. Use `buffered` for a provider without streaming support.
  Streaming cannot overcome an origin that fails to return data before its proxy timeout.
- Embeddings: local Hugging Face sentence-transformers or configured remote APIs.
  E5 multilingual large instruct is a tested 1024-dimensional option with a
  **512-token** model context. Changing model/dimension requires reindexing.
- Recommended starting pipeline: **PyMuPDF for digital PDFs**, **Docling with OCR
  for scans**, and LlamaIndex for retrieval. MinerU Basic ONNX is an alternative
  layout/OCR parser on the tested P100-compatible runtime. Its 10-page FUNSD result
  was weaker than Docling; choose using your own document sample.
- LlamaParse, MinerU HTTP/local, and compatible vision OCR endpoints are optional
  adapters. Remote OCR needs a vision-capable model; a successful text connection
  test does not prove OCR support. DeepSeek OCR adapters have not received a
  public quality score in this release.
- API keys are configured locally. The first launch contains no personal knowledge
  bases, histories, notebooks, or cached model weights.
- Legacy Quiz Gen Plus is hidden. Edu Studio and the Presenton slide page are exposed.

## Build from source

```bash
cp .env.example .env
python3 scripts/initialize_release.py
python3 scripts/setup_single_user_gateway.py
docker compose --profile slides build
# Source builds create the same local image tags as the packaged beta.
docker compose --profile slides up -d --wait --wait-timeout 240
```

The Dockerfile installs the pinned P100 dependency constraints, applies the reviewed
security updates, and checks dependency consistency. Its known advisory status is
published honestly; `pip check` alone is not a vulnerability assessment.
Model weights and external services remain subject to their own availability and licenses.

## Validation and benchmarks

The bundled runtime regression suite passed **153 tests** (4 external integration tests
excluded). The frontend production build and TypeScript checks passed with zero lint
errors; lint warnings remain. Authentication, representative UI routes, the actual
queue worker, code execution, PDF ingestion and source-backed retrieval were checked.
These checks do not guarantee correctness for all inputs. Some long generation flows
could not complete their final rerun because the external provider exhausted its quota.
No internal test histories or deployment reports are included.

Measured on 2026-10-28 (Asia/Ho_Chi_Minh). Results describe this deployment and these
samples; they are not a leaderboard submission, an SLA, or a claim of general correctness.
Only numbers, public dataset IDs and hashes are distributed. No documents or annotations
from benchmark datasets are bundled.

## Retrieval: BEIR / SciFact

Sources: [BEIR](https://github.com/beir-cellar/beir),
[SciFact dataset card](https://huggingface.co/datasets/BeIR/scifact).

All **5,183 abstracts**, all **300 judged test queries**, exact cosine ranking over
normalized 1024-dimensional E5 embeddings through EduNote's production embedding
client. No reranker or generated answer score. E5 instruct query instructions and
passage handling are the production adapter's behavior. Effective model context is
512 tokens; an earlier client config value of 8192 does not increase that context.

| Metric | Value |
| --- | ---: |
| Recall@1 | 0.584278 |
| Recall@5 | 0.751778 |
| Recall@10 | 0.817833 |
| MRR@10 | 0.681210 |
| nDCG@10 | 0.709558 |
| Full measured embedding/retrieval time | 294.178 s |

Results and input hashes: [scifact.json](benchmarks/results/scifact.json).
This is a dense-retrieval baseline, not an end-to-end RAG faithfulness/citation benchmark.

## OCR: FUNSD

Source: [FUNSD](https://guillaumejaume.github.io/FUNSD/),
[dataset terms](https://guillaumejaume.github.io/FUNSD/work/).
FUNSD is for non-commercial research/education; obtain it separately and follow its terms.
First **10 sorted official test document IDs**, identical selection for both parsers.
No tuning on these test labels. Macro-average per document; token scores use normalized
word multisets, while CER/WER preserve output order. Annotation ordering differs from
page reading order, so report both and inspect per-document outliers.

| Parser | Successful | Token precision | Token recall | Token F1 | CER | WER | Mean s/page |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MinerU 4 Basic ONNX | 10/10 | 0.801188 | 0.845364 | 0.780943 | 3.404892 | 1.444815 | 11.2767 |
| Docling + RapidOCR | 10/10 | 0.872840 | 0.807691 | 0.835793 | 0.418580 | 0.556181 | 16.5621 |

CER/WER may exceed 1 for heavy insertions. MinerU's high aggregate CER includes
poor outputs and must not be hidden by token F1. Initial model-load time is included.
This is a small English noisy-form sample, not a Vietnamese, handwriting, table,
or full layout benchmark. See [MinerU](benchmarks/results/funsd-mineru.json) and
[Docling](benchmarks/results/funsd-docling.json) for IDs, hashes, timings and individual scores.

## Current LLM provider performance

Model: `Qwen/Qwen3.5-9B:Q6_K`. **8/8 requests returned HTTP 200 and visible content**.
Fixed counting prompt (integers 1 through 16), max_tokens=64, temperature=0, streaming,
four sequential requests followed by two batches of two concurrent requests. No retries.
No remote endpoint or key is published. These timings include the network/proxy/provider; inference hardware
is **not assumed** to be EduNote's P100 application server.

| Measurement | Seconds |
| --- | ---: |
| First request total / first visible token | 20.4305 / 19.0358 |
| Subsequent sequential total range | 1.8280–1.8752 |
| Two-concurrent total range | 1.8367–3.3942 |
| Overall median total / first visible token | 1.8442 / 0.4502 |
| Overall nearest-rank p95 total / first visible token | 20.4305 / 19.0358 |

p95 includes the first request; with eight samples it is simply the largest observed
value. The first request is not proven to be a true cold start. Identical requests
may benefit from provider caching. The stream did not report token usage, so tokens/s
is deliberately omitted. [Raw observations](benchmarks/results/server-performance.json).

## Authenticated application read load

400 requests, concurrency 8, mixed UI and read-only API routes, all HTTP 200.
Measured through the single-owner gateway against an isolated restored deployment
on the same application server. **34.90 requests/s**, p95 **0.602 s**, p99 **1.611 s**.
See [aggregate measurements](benchmarks/results/load-gateway.json). This is not a GPU generation,
writer contention, sustained soak, or maximum-capacity benchmark.

Application server profile: two Tesla P100 16 GB GPUs, NVIDIA driver 535.309.01;
Python 3.11, Torch 2.4.1+cu121. The OCR/parser profile uses the P100-compatible runtime.
Resource sharing and caches affect timing; no claim of dedicated provider hardware.

## Reproduce

Install the application runtime and download the datasets from their original sources
separately. Run in an isolated workspace; provider calls may incur charges.

```bash
python scripts/validation/public_benchmarks.py --help
python scripts/validation/public_benchmarks.py retrieval --dataset /datasets/scifact --output scifact.json
python scripts/validation/public_benchmarks.py ocr --dataset /datasets/funsd --parser docling --count 10 --output funsd-docling.json
python scripts/benchmarks/server_performance.py --config /private/provider.json --output server-performance.json
```

The private provider JSON contains `base_url`, `model`, and `api_key`. Keep it outside
the repository and remove it after testing. The benchmark script never emits these
credentials or the endpoint. Reproduction requires the same model/runtime and may
produce different timings. Dataset input hashes and FUNSD IDs are supplied to detect
selection differences. No end-to-end answer-quality or security claim follows from
these benchmarks.

## Availability failures observed after the short benchmark

A subsequent direct streaming request to the same Qwen deployment returned HTTP 524
after 125.37 seconds with no visible content. An EduNote probe also received the
provider's nested HTTP 429/524 response. Therefore the eight earlier successes must
not be interpreted as uninterrupted availability. The active Gemini model later
exhausted its provider's free daily quota; later workflow reruns were blocked by
provider HTTP 429. No extra provider generation calls were made after confirming
the exhausted quota.

## Operations

```bash
docker compose --profile slides ps
docker compose --profile slides logs --tail 100
docker compose --profile slides stop
# Restart after editing .env/config; use the GPU override when appropriate.
bash start.sh
```

User files and indexes live in `data/user`, `data/knowledge_bases`, and `data/storage`.
Model cache, runner spool, and Presenton data/databases use named Docker volumes.
Do not remove volumes unless you intend to destroy their data.

Back up `.env`, `.edunote-access/`, `config/`, all `data/` directories, the Presenton
application volume, and a `pg_dump` of its database. Stop/quiesce writers for a
consistent cross-service snapshot. `scripts/validation/backup_restore.py` provides
checksummed snapshots and isolated restore verification; it deliberately refuses
to overwrite a destination. `scripts/backup_edunote.sh` covers core files; set
`EDUNOTE_STORAGE_ROOT=./data/storage` and `EDUNOTE_BACKUP_ROOT=./backups` when using
it outside Compose. Include Presenton dumps/volume exports explicitly.

The ready-to-run package excludes internal reports, internal Markdown, private
folders, model weights, datasets, and all deployment credentials. Vendor licenses
and notices are retained. Only public benchmark measurements are intentionally included in `benchmarks/results/`.

## License and credits

EduNote: Apache-2.0, [LICENSE](LICENSE). Sole EduNote author and maintainer:
**Tran Huu Vu Phuong (CSE 2025 - Vietnamese-German University)**.
Slide Generator integrates **[Presenton](https://github.com/presenton/presenton)**,
an open-source presentation generator licensed under Apache-2.0. Its upstream
project and contributors deserve credit for the slide-generation foundation.
Presenton and other dependencies remain the work of their respective authors;
see [NOTICE](NOTICE) and `presenton/LICENSE`. External model and dataset licenses
are separate from the application license.

## Security status

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
