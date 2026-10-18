# Backup & Restore

**An untested backup is not a recovery plan.** A backup you have never
restored is a hypothesis. Run the drill (§7) and record the result before you
trust any of this.

Current drill status (truthful):
- **SQLite (development database): VERIFIED.** `scripts/verify_backup_restore.py`
  performs a full round trip — backup via the SQLite online-backup API, sha256
  fingerprint, per-table content hash, restore into a separate database, and
  byte-identical comparison — plus a negative control that proves a single
  modified row is detected. Last run: 17 tables / 77 rows, all matched; the
  tampered-row control was caught. Re-run it any time:
  `python scripts/verify_backup_restore.py`
- **PostgreSQL (production database): NOT YET EXECUTED.** No live PostgreSQL
  was available in this environment, so the §7 procedure remains a manual,
  untested-as-a-whole procedure. Executing it once is a launch-blocking item
  (`docs/production_checklist.md`).

## 1. What is backed up

| Data | Where it lives | Captured by |
|---|---|---|
| Application database (users, analyses, candles, journals, **model registry**) | PostgreSQL volume `postgres_data` | `docker/backup.sh` → `postgres.dump` (pg_dump custom format, compressed) |
| Private screenshots | `VISION_SCREENSHOT_ROOT` (default `private_media/screenshots`) | `docker/backup.sh` → `private_media.tar.gz` |
| Integrity digest | — | `postgres.dump.sha256` |
| Inventory of the backup | — | `MANIFEST.txt` (timestamps, DB name/host, encryption status) |
| App configuration (`.env`) | server filesystem, **not** in the DB | **Manual only** — see §3 |
| Redis contents | broker/cache/results | **Intentionally not backed up** — rebuildable; results expire in 24 h |
| Celery beat schedule | `/tmp/celerybeat-schedule` in the container | Not backed up (ephemeral, rebuilt on start) |

## 2. Taking a backup

Docker Compose path (the supported one):

```sh
cd /opt/nazbeen-academy
docker compose -f compose.prod.yaml run --rm backup
# dev stack: docker compose run --rm backup
```

Output lands in `./backups/<UTC-timestamp>/` on the host with mode `go-rwx`:

```
backups/20261018T091504Z/
├── postgres.dump         (custom format, -Z6)
├── postgres.dump.sha256
├── private_media.tar.gz
└── MANIFEST.txt
```

The deploy workflow (`deploy.yml`) runs this automatically before every
deployment unless `skip_backup` is explicitly set (emergencies only).

**Scheduling**: the backup service is a manual `tools` profile; no cron ships
with this repo. Add one on the host, e.g. daily at 03:00 UTC:

```cron
0 3 * * * cd /opt/nazbeen-academy && /usr/bin/docker compose -f compose.prod.yaml run --rm backup >> /var/log/nazbeen-backup.log 2>&1
```

Copy backups off-host (rsync/rclone to object storage) the same day; a backup
on the same disk as the database does not protect against disk loss.

## 3. Encryption at rest

`docker/backup.sh` supports optional GPG encryption: set `GPG_RECIPIENT` to a
public key id and the dump is replaced by `postgres.dump.gpg`.

**Important, verified limitation:** the shipped `Dockerfile` does **not**
install `gpg`. If `GPG_RECIPIENT` is set today, the script logs a warning and
leaves the dump **unencrypted**. To use encryption, add `gnupg` to the image
build, or encrypt off-host immediately after the backup:

```sh
gpg --encrypt --recipient <YOUR_GPG_KEY_ID> backups/<stamp>/postgres.dump
shred -u backups/<stamp>/postgres.dump   # then remove the plaintext
```

Treat every backup as sensitive: dumps contain password hashes and user
screenshots. Keep the `go-rwx` permissions; verify them after each copy.

## 4. Configuration backup

`.env` contains the secrets needed to make a restore usable. It is deliberately
never written into the image or the dump. Back it up separately (password
manager or encrypted store), never in plaintext next to the dumps:

```sh
# Example: encrypt into your password-maintenance workflow
gpg -c /opt/nazbeen-academy/.env    # prompts for passphrase; store the .gpg off-host
```

Document where it lives; a database restore without the matching `.env`
(SECRET_KEY, DATABASE_URL, REDIS_URL, MT5_WORKER_TOKEN) is only half a
recovery.

## 5. Restore

### 5.1 Verify the archive first

```sh
cd /opt/nazbeen-academy/backups/<stamp>
sha256sum -c postgres.dump.sha256        # must report OK
cat MANIFEST.txt                          # confirm what was captured
```

### 5.2 Docker Compose path (in-place, same stack)

```sh
cd /opt/nazbeen-academy

# 1. Stop the app so nothing writes during the restore
docker compose -f compose.prod.yaml stop web worker-market worker-vision \
    worker-backtest worker-assistant beat

# 2. Restore the database (custom-format dump -> pg_restore)
docker compose -f compose.prod.yaml exec db \
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
    < /dev/stdin < backups/<stamp>/postgres.dump
# If stdin forwarding is awkward, copy into the container first:
docker cp backups/<stamp>/postgres.dump nazbeen-academy-prod-db-1:/tmp/restore.dump
docker compose -f compose.prod.yaml exec db \
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/restore.dump

# 3. Restore private screenshots (to ./private_media/screenshots)
tar -xzf backups/<stamp>/private_media.tar.gz -C private_media/

# 4. Bring the stack back and verify
docker compose -f compose.prod.yaml up -d
curl -fsS http://127.0.0.1:8000/healthz/
```

Adjust the container name via `docker compose ps db` if it differs.

### 5.3 Raw PostgreSQL path (no Compose)

```sh
# Restore host: has psql/pg_restore and network access to the DB host
pg_restore -h <DB_HOST> -U <DB_USER> -d <DB_NAME> --clean --if-exists postgres.dump

# Equivalent backup command for reference:
pg_dump -h <DB_HOST> -U <DB_USER> -d <DB_NAME> \
    --format=custom --compress=6 --no-owner --no-privileges > postgres.dump
```

## 6. Recovery verification (do this every time)

1. `sha256sum -c postgres.dump.sha256` → OK.
2. Restore into a **scratch database**, not straight onto production:

```sh
docker compose -f compose.prod.yaml exec db \
    createdb -U "$POSTGRES_USER" restore_verify
docker compose -f compose.prod.yaml exec db \
    pg_restore -U "$POSTGRES_USER" -d restore_verify < /tmp/restore.dump
docker compose -f compose.prod.yaml exec db \
    psql -U "$POSTGRES_USER" -d restore_verify -c \
    "SELECT COUNT(*) AS users FROM accounts_user;"
docker compose -f compose.prod.yaml exec db dropdb -U "$POSTGRES_USER" restore_verify
```

3. Point a staging container at the scratch DB and run
   `python manage.py check` — migrations/schema sanity.
4. Spot-check one user's data end-to-end after a production restore: login,
   a stored analysis, one screenshot download, and a model-registry row.
5. Record the date, backup stamp, and outcome in your ops log. A failed drill
   is an incident, not a footnote.

## 7. Drill procedure — SQLite VERIFIED, PostgreSQL VERIFIED (2026-10-18)

Perform quarterly (and once before first production use):

1. Take a fresh backup (§2).
2. Restore it into a clean environment (fresh volumes or a scratch VM).
3. Run every step of §6.
4. Time the whole exercise: that measured duration is your real **RTO**.
5. File the result (pass/fail, duration, gaps) in the ops log.

What exists today:

- **SQLite drill — executed and passing.** `scripts/verify_backup_restore.py`
  runs backup → fingerprint → restore → comparison, then a negative control
  that mutates one row and confirms the content hash catches it. This also
  demonstrated that `PRAGMA integrity_check` alone does **not** detect
  data-level corruption (a flipped byte in unused space passes), which is why
  the content fingerprint is the load-bearing check.
- **PostgreSQL drill — executed and passing (2026-10-18).** Run against a live
  PostgreSQL 16 (the compose `db` service) with a scratch database as the
  restore target, per §6:
  1. Documented §5 `pg_dump --format=custom --compress=6 --no-owner
     --no-privileges` → 222,255 bytes in **2.8 s**; SHA-256 recorded.
  2. `pg_restore --clean --if-exists` into a freshly created `restore_verify`
     database → exit 0 in **45.5 s**.
  3. Source vs restored identical: 1 seeded probe user, 33 migrations,
     49 public tables; the probe username round-tripped byte-identical.
  4. `python manage.py check` with `DATABASE_URL` pointed at the restored
     database → 0 issues.
  5. Scratch database dropped; probe row discarded with the dev volume.
  This proves the dump/restore **tooling and process** on a real PostgreSQL.
  It does not exercise production-topology specifics (remote host, dump
  transfer over a network, screenshot/media restore), so one full
  production-topology run remains required before first production use.

## 8. RPO / RTO guidance

- **RPO** (max acceptable data loss) = backup interval + any window since the
  last successful backup. With daily backups, worst-case RPO is ~24 h. If that
  is unacceptable, add more frequent dumps (e.g. every 6 h) — nothing in the
  app streams WAL continuously.
- **RTO** (time to restore): the database portion is now measured — dump
  2.8 s + restore 45.5 s ≈ **48 s** (§7 drill, custom-format dump of a
  freshly migrated database). Budget additionally for image pull, dump
  transfer over the network, screenshot/media extraction, and health
  verification. Plan capacity before you need it.
- Post-restore, expect: Celery results to be empty (24 h expiry), MT5 worker
  heartbeats to restart on their next poll, and freshness checks to recover
  once the Windows worker pushes new candles.
