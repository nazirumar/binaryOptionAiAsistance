#!/bin/sh
# ---------------------------------------------------------------------------
# Database + private-media backup.
#
# Usage (inside the container, via the `backup` profile):
#   docker compose run --rm backup                 # unencrypted .dump
#   GPG_RECIPIENT=you@example.com \
#   docker compose run -e GPG_RECIPIENT=... --rm backup
#
# Output: /app/backups/<timestamp>/  containing
#   - postgres.dump            (custom format, compressed)
#   - postgres.dump.sha256     (integrity digest)
#   - private_media.tar.gz     (screenshots actually on disk)
#   - MANIFEST.txt             (what was captured, from/to, versions)
#
# An untested backup is NOT a recovery plan: run docs/backup_restore.md's
# restore drill regularly and record the result.
#
# DATABASE_URL supplies credentials; nothing is printed by this script.
# ---------------------------------------------------------------------------
set -eu

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${BACKUP_DIR:-/app/backups}/${STAMP}"
mkdir -p "${OUT_DIR}"

log() { printf '[backup] %s\n' "$*" >&2; }

# Parse DATABASE_URL without echoing it. Supports postgres:// and postgresql://.
# Fallback to discrete PG* variables (used by the compose db service).
DB_URL="${DATABASE_URL:-}"
if [ -n "${DB_URL}" ]; then
    _stripped="$(printf '%s' "${DB_URL}" | sed -e 's#^[a-zA-Z][a-zA-Z0-9+.-]*://##')"
    _creds="${_stripped%%@*}"
    _rest="${_stripped#*@}"
    _hostport="${_rest%%/*}"
    _dbname="${_rest#*/}"
    _dbname="${_dbname%%\?*}"
    DB_HOST="${_hostport%%:*}"
    DB_PORT="${_hostport#*:}"
    [ "${DB_PORT}" = "${DB_HOST}" ] && DB_PORT="5432"
    if [ "${_creds}" != "${_rest}" ] && printf '%s' "${_creds}" | grep -q ':'; then
        DB_USER="${_creds%%:*}"
        DB_PASSWORD="${_creds#*:}"
    else
        DB_USER="${_creds}"
        DB_PASSWORD="${PGPASSWORD:-}"
    fi
    DB_NAME="${_dbname}"
else
    DB_HOST="${PGHOST:-db}"
    DB_PORT="${PGPORT:-5432}"
    DB_USER="${POSTGRES_USER:-app}"
    DB_PASSWORD="${POSTGRES_PASSWORD:-}"
    DB_NAME="${POSTGRES_DB:-nazbeen_academy}"
fi

# Never leak the password through `ps` output or logs.
export PGPASSWORD="${DB_PASSWORD}"

log "dumping database '${DB_NAME}' at ${DB_HOST}:${DB_PORT}"
pg_dump \
    --host="${DB_HOST}" \
    --port="${DB_PORT}" \
    --username="${DB_USER}" \
    --dbname="${DB_NAME}" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    > "${OUT_DIR}/postgres.dump"

# Integrity digest so a corrupted archive is detected before you need it.
( cd "${OUT_DIR}" && sha256sum postgres.dump > postgres.dump.sha256 )

log "archiving private screenshot storage"
SCREENSHOT_ROOT="${VISION_SCREENSHOT_ROOT:-/app/private_media/screenshots}"
if [ -d "${SCREENSHOT_ROOT}" ]; then
    tar -czf "${OUT_DIR}/private_media.tar.gz" -C "$(dirname "${SCREENSHOT_ROOT}")" \
        "$(basename "${SCREENSHOT_ROOT}")" 2>/dev/null || \
        log "WARNING: screenshot archive failed (may be empty)"
else
    log "no screenshot directory at ${SCREENSHOT_ROOT}; skipping"
fi

# Optional encryption at rest. Requires gpg in the image and a public key.
if [ -n "${GPG_RECIPIENT:-}" ]; then
    if command -v gpg >/dev/null 2>&1; then
        log "encrypting dump for ${GPG_RECIPIENT}"
        gpg --batch --yes --trust-model always \
            --recipient "${GPG_RECIPIENT}" \
            --output "${OUT_DIR}/postgres.dump.gpg" \
            --encrypt "${OUT_DIR}/postgres.dump"
        rm -f "${OUT_DIR}/postgres.dump" "${OUT_DIR}/postgres.dump.sha256"
    else
        log "WARNING: GPG_RECIPIENT set but gpg is not installed; leaving unencrypted"
    fi
fi

cat > "${OUT_DIR}/MANIFEST.txt" <<EOF
project: Nazbeen Academy Binary Ai Asisstance
created_utc: ${STAMP}
database: ${DB_NAME}
host: ${DB_HOST}:${DB_PORT}
pg_dump_format: custom (compressed)
private_media: $([ -f "${OUT_DIR}/private_media.tar.gz" ] && echo "included" || echo "absent")
encrypted: $([ -n "${GPG_RECIPIENT:-}" ] && echo "yes (${GPG_RECIPIENT})" || echo "no")
EOF

# Permissions: backups may contain user screenshots — keep them owner-only.
chmod -R go-rwx "${OUT_DIR}"

unset PGPASSWORD
log "backup complete: ${OUT_DIR}"
ls -la "${OUT_DIR}" >&2
