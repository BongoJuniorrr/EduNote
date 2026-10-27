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
> See [SECURITY.md](SECURITY.md). The demo requires its owner's shared password.

## Run the prebuilt beta

Requirements: Linux x86-64, Docker Engine with Compose v2, Python 3, OpenSSL,
32 GB RAM recommended, and about 40 GB free disk for the full image set and caches.
A configured LLM provider with available quota is required for generation. Internet access is required
for initial model downloads. Model weights, datasets, personal files, and provider
credentials are deliberately not bundled. NVIDIA GPU is optional; local models
run much more slowly on CPU.

1. From the [release page](https://github.com/BongoJuniorrr/EduNote/releases/tag/v0.1.0-beta.1),
   download **all** `EduNote-0.1.0-beta.1-linux-amd64-part*.zip` assets and `SHA256SUMS`.
   Runtime images exceed GitHub's per-file limit, so they are divided across ZIPs.
2. Verify the ZIP checksums: `sha256sum -c SHA256SUMS`. Extract every ZIP into the
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

## Validation and measurements

The release was evaluated against the configured deployment, not just mocked providers:

| Check | Observed result |
| --- | --- |
| Python regression baseline | 132 passed, 4 deselected; external integration suites excluded |
| Frontend | Production build and TypeScript checks passed; 0 lint errors, warnings remain |
| Browser routes | 16 representative pages, no observed page errors |
| Business workflows | Chat/history, notebook/canvas, solver/code, question generation, guide, research, missions, Co-Writer, and Edu Studio exercised |
| RAG | PDF ingestion, persistence, incremental update and source-backed retrieval exercised |
| Worker recovery | Interrupted leased work recovered by a replacement worker |
| Restore drill | 2,404 files checked; SQLite integrity and isolated Presenton PostgreSQL restore verified |
| HTTP read load | 400 requests, concurrency 8, all HTTP 200; see benchmark results |

These are representative acceptance checks, not exhaustive proof that every possible
input or model response is correct. Final package smoke and worker dispatch checks
are recorded in `benchmarks/results/package-validation.json`.

[Benchmark methods, raw numerical results and limitations](benchmarks/README.md) include
BEIR/SciFact retrieval, FUNSD OCR, authenticated HTTP load, and eight real streaming
requests against the configured Qwen server. No benchmark dataset or user content
is redistributed.

To repeat a read-only smoke/load check on your own deployment:

```bash
python3 -m pip install httpx
python3 scripts/verify_release.py --base-url http://localhost:3782 --password-file .edunote-access/password.txt
python3 scripts/validation/load_check.py --base-url http://localhost:3782 --password-file .edunote-access/password.txt --requests 400 --concurrency 8 --output load-result.json
```

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
and notices are retained. Benchmark reports in `benchmarks/` are intentionally
public release documentation.

## License and credits

EduNote: Apache-2.0, [LICENSE](LICENSE). Sole EduNote author and maintainer:
**Tran Huu Vu Phuong (CSE 2025 - Vietnamese-German University)**.
Presenton and other dependencies remain the work of their respective authors;
see [NOTICE](NOTICE) and `presenton/LICENSE`. External model and dataset licenses
are separate from the application license.
