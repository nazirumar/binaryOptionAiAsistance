#!/bin/sh
# ---------------------------------------------------------------------------
# Container entrypoint.
#
# Responsibilities, in order:
#   1. wait for dependent services (PostgreSQL / Redis) when asked to
#   2. run pending migrations (only for services that opt in)
#   3. collect static files (only for the service that opts in)
#   4. exec the actual command as PID 1 so signals propagate correctly
#
# Nothing here reads or prints secrets.
# ---------------------------------------------------------------------------
set -eu

log() {
    printf '[entrypoint] %s\n' "$*" >&2
}

# --- Wait for dependencies ---------------------------------------------------
# WAIT_FOR="db:5432 redis:6379" — each entry is host:port.
wait_for() {
    _targets="${1:-}"
    [ -z "$_targets" ] && return 0
    for _target in $_targets; do
        _host="${_target%:*}"
        _port="${_target#*:}"
        log "waiting for ${_host}:${_port}..."
        _tries=0
        # Bounded: never block a deploy forever on an unreachable dependency.
        while [ "$_tries" -lt 60 ]; do
            if (exec 3<>"/dev/tcp/${_host}/${_port}") 2>/dev/null; then
                exec 3>&- 3<&-
                log "${_host}:${_port} is accepting connections"
                break
            fi
            _tries=$((_tries + 1))
            sleep 1
        done
        if [ "$_tries" -ge 60 ]; then
            # Fail loudly rather than booting a half-working service.
            log "ERROR: timed out after 60s waiting for ${_host}:${_port}"
            exit 1
        fi
    done
}

wait_for "${WAIT_FOR:-}"

# --- Migrate -----------------------------------------------------------------
# Only the designated migrate service sets RUN_MIGRATIONS=1 so that several
# replicas never race the same migration.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    log "applying database migrations"
    python manage.py migrate --noinput
fi

# --- Static files ------------------------------------------------------------
# Only one service sets RUN_COLLECTSTATIC=1 (the web service).
if [ "${RUN_COLLECTSTATIC:-0}" = "1" ]; then
    log "collecting static files"
    python manage.py collectstatic --noinput
fi

# --- Optional one-shot checks ------------------------------------------------
if [ "${RUN_SYSTEM_CHECK:-0}" = "1" ]; then
    log "running Django system checks"
    python manage.py check --deploy
fi

log "starting: $*"
# exec replaces the shell so the server receives SIGTERM directly (clean
# shutdown, in-flight requests drained) instead of an orphaned child.
exec "$@"
