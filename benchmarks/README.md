# Published beta benchmark results

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

Results and input hashes: [scifact.json](results/scifact.json).
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
or full layout benchmark. See [MinerU](results/funsd-mineru.json) and
[Docling](results/funsd-docling.json) for IDs, hashes, timings and individual scores.

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
is deliberately omitted. [Raw observations](results/server-performance.json).

## Authenticated application read load

400 requests, concurrency 8, mixed UI and read-only API routes, all HTTP 200.
Measured through the single-owner gateway against an isolated restored deployment
on the same application server. **34.90 requests/s**, p95 **0.602 s**, p99 **1.611 s**.
See [all request timings](results/load-gateway.json). This is not a GPU generation,
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
the exhausted quota. Historical passing workflows and current blocked reruns are
distinguished in the package validation record.
