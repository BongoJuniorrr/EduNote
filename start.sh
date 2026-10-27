#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
command -v docker >/dev/null || { echo 'Install Docker Engine and Docker Compose v2 first.' >&2; exit 2; }
docker compose version >/dev/null
# All release ZIP parts must be extracted into this directory before first use.
if ! docker image inspect edunote:0.1.0-beta.1 edunote-code-runner:0.1.0-beta.1 edunote-presenton:0.1.0-beta.1 >/dev/null 2>&1; then
  python3 scripts/load_release_images.py
fi
umask 077
if [[ ! -f .env ]]; then cp .env.example .env; fi
python3 scripts/initialize_release.py
python3 scripts/setup_single_user_gateway.py
args=(-f compose.yaml)
if [[ "${EDUNOTE_GPU:-0}" == 1 ]]; then args+=(-f compose.gpu.yaml); fi
if [[ "${EDUNOTE_SLIDES:-1}" == 1 ]]; then args+=(--profile slides); fi
docker compose "${args[@]}" up -d --no-build --wait --wait-timeout 240
printf 'EduNote started. Default URL: http://localhost:3782
Owner password: .edunote-access/password.txt (kept private).
Configure your LLM and embedding models in Settings.
'
