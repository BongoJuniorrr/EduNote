#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "${PROJECT_ROOT}"
BACKUP_ROOT="${EDUNOTE_BACKUP_ROOT:-./backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
exec 9>"${EDUNOTE_BACKUP_LOCK:-/tmp/edunote-backup.lock}"
flock -n 9 || { printf 'Another backup is running\n' >&2; exit 2; }
DEPLOYMENT_COPY="$(mktemp -d "${TMPDIR:-/tmp}/edunote-deployment-backup.XXXXXXXX")"
cleanup_deployment_copy() {
  python3 -c 'import shutil,sys; shutil.rmtree(sys.argv[1])' "${DEPLOYMENT_COPY}"
}
trap cleanup_deployment_copy EXIT
for file in .env EduNote.env compose.yaml compose.gpu.yaml start.sh README.md Dockerfile docker-compose.prod.yml docker-compose.release.yml docker-compose.access.yml requirements.txt constraints.runtime.txt constraints.security.txt; do
  if [[ -f "${PROJECT_ROOT}/${file}" ]]; then
    install -m 600 -- "${PROJECT_ROOT}/${file}" "${DEPLOYMENT_COPY}/${file}"
  fi
done
if [[ -d "${PROJECT_ROOT}/.edunote-access" ]]; then
  mkdir -m 700 "${DEPLOYMENT_COPY}/access"
  for file in password.txt owner.htpasswd; do
    install -m 600 -- "${PROJECT_ROOT}/.edunote-access/${file}" "${DEPLOYMENT_COPY}/access/${file}"
  done
fi
# Stop/quiesce all application writers before a cross-service recovery point.
# PostgreSQL must be dumped separately with pg_dump; add its private directory
# with EDUNOTE_DATABASE_DUMP_ROOT. Models/caches can be downloaded again.
SOURCES=(
  --source "deployment=${DEPLOYMENT_COPY}"
  --source "user=${PROJECT_ROOT}/data/user"
  --source "knowledge_bases=${PROJECT_ROOT}/data/knowledge_bases"
  --source "config=${PROJECT_ROOT}/config"
  --source "storage=${EDUNOTE_STORAGE_ROOT:-./data/storage}"
)
if [[ -n "${EDUNOTE_DATABASE_DUMP_ROOT:-}" ]]; then
  SOURCES+=(--source "database_dumps=${EDUNOTE_DATABASE_DUMP_ROOT}")
fi
if [[ -n "${EDUNOTE_PRESENTON_DATA_ROOT:-}" ]]; then
  SOURCES+=(--source "presenton=${EDUNOTE_PRESENTON_DATA_ROOT}")
fi
python3 "${PROJECT_ROOT}/scripts/validation/backup_restore.py" snapshot \
  "${SOURCES[@]}" --snapshot "${BACKUP_ROOT}/snapshots/${TIMESTAMP}"
printf '%s\n' "${TIMESTAMP}" > "${BACKUP_ROOT}/snapshots/LATEST"
printf 'Verified snapshot: %s\n' "${BACKUP_ROOT}/snapshots/${TIMESTAMP}"
