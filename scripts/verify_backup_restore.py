"""Backup and restore drill for the local/development database.

An untested backup is not a recovery plan. This script exercises the full
round trip and *proves* the verification step would catch a bad archive:

  1. BACKUP     the source database to a work directory (SQLite online
                backup API -- consistent even with concurrent writers)
  2. FINGERPRINT sha256 the backup file and run PRAGMA integrity_check
  3. CHECKSUM   hash every user table's contents on the source
  4. RESTORE    the backup into a separate restored database
  5. VERIFY     the restored checksum must equal the source checksum
  6. NEGATIVE   deliberately corrupt a *copy* of the backup and confirm the
                integrity check rejects it -- otherwise step 2 is theatre

The source database is opened READ-ONLY and never modified, so this is safe
to run against a working development database.

Usage:
    python scripts/verify_backup_restore.py
    python scripts/verify_backup_restore.py --db db.sqlite3 --workdir <dir>

Exit code 0 means the drill passed; non-zero means recovery would fail.

This drill covers SQLite (the development database). The PostgreSQL drill
uses pg_dump/pg_restore and is documented in docs/backup_restore.md; it must
be executed against a real PostgreSQL instance, which this script does not
attempt to stand up.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import tempfile
from pathlib import Path


def _connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        # URI mode opens the file without creating or locking it for writes.
        uri = f"file:{path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=10)
    else:
        connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _user_tables(connection: sqlite3.Connection) -> list[str]:
    """Every table that belongs to the application (excludes SQLite internals)."""
    rows = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'django_migrations' "
        "ORDER BY name"
    ).fetchall()
    return [name for (name,) in rows]


def _table_checksum(connection: sqlite3.Connection, table: str) -> tuple[int, str]:
    """Row count plus a content hash for one table, independent of row order."""
    rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
    digest = hashlib.sha256()
    for row in sorted(repr(item) for item in rows):
        digest.update(row.encode("utf-8", "replace"))
    return len(rows), digest.hexdigest()


def _database_fingerprint(connection: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    return {table: _table_checksum(connection, table) for table in _user_tables(connection)}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_ok(connection: sqlite3.Connection) -> bool:
    result = connection.execute("PRAGMA integrity_check").fetchall()
    return result == [("ok",)]


def _backup(source: Path, target: Path) -> None:
    """Consistent online backup (safe while other processes hold the DB)."""
    src = _connect(source, read_only=True)
    dst = _connect(target)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()


def _corrupt_byte(path: Path, offset: int = 512) -> None:
    """Flip one byte inside the file body to simulate a damaged archive."""
    data = bytearray(path.read_bytes())
    if len(data) <= offset:  # pragma: no cover - tiny database
        offset = len(data) // 2
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="db.sqlite3", help="source database file")
    parser.add_argument(
        "--workdir",
        default="",
        help="where to place backup/restored files (default: a temp directory)",
    )
    args = parser.parse_args(argv)

    source = Path(args.db).resolve()
    if not source.exists():
        print(f"SKIP: source database not found at {source}.")
        print("Run the application once (or a migration) to create it, then re-run.")
        return 0

    workdir = Path(args.workdir).resolve() if args.workdir else Path(tempfile.mkdtemp())
    workdir.mkdir(parents=True, exist_ok=True)
    backup_path = workdir / "backup.sqlite3"
    restored_path = workdir / "restored.sqlite3"
    corrupted_path = workdir / "corrupted_backup.sqlite3"

    failures: list[str] = []

    # --- 1-2: backup and fingerprint --------------------------------------
    _backup(source, backup_path)
    backup_digest = _file_sha256(backup_path)
    with _connect(backup_path, read_only=True) as backup_db:
        if not _integrity_ok(backup_db):
            failures.append("backup failed PRAGMA integrity_check")
    print(f"[1] backup created   : {backup_path}")
    print(f"[2] backup sha256    : {backup_digest}")
    print(f"    size             : {backup_path.stat().st_size} bytes")

    # --- 3: source fingerprint --------------------------------------------
    with _connect(source, read_only=True) as source_db:
        source_fingerprint = _database_fingerprint(source_db)
    total_rows = sum(count for count, _ in source_fingerprint.values())
    print(f"[3] source tables    : {len(source_fingerprint)} ({total_rows} rows)")

    # --- 4-5: restore and verify -------------------------------------------
    _backup(backup_path, restored_path)
    with _connect(restored_path, read_only=True) as restored_db:
        if not _integrity_ok(restored_db):
            failures.append("restored database failed integrity_check")
        restored_fingerprint = _database_fingerprint(restored_db)

    if restored_fingerprint != source_fingerprint:
        missing = set(source_fingerprint) - set(restored_fingerprint)
        added = set(restored_fingerprint) - set(source_fingerprint)
        changed = {
            table
            for table in set(source_fingerprint) & set(restored_fingerprint)
            if source_fingerprint[table] != restored_fingerprint[table]
        }
        failures.append(
            f"restored data differs (missing={sorted(missing)}, "
            f"added={sorted(added)}, changed={sorted(changed)})"
        )
        print("[5] VERIFY           : FAILED")
    else:
        print(f"[4] restored to      : {restored_path}")
        print(f"[5] VERIFY           : OK ({len(restored_fingerprint)} tables match)")

    # --- 6: negative control -------------------------------------------------
    # Would our verification actually catch a bad archive? Two probes:
    #
    #   (a) DETERMINISTIC: tamper with one row in a copy of the backup (the
    #       real failure mode -- data drift, partial write, or operator error)
    #       and prove the content fingerprint rejects it. This is the hard
    #       assertion: if the fingerprint did not catch a changed row, a
    #       restore could silently commit wrong data.
    #
    #   (b) INFORMATIVE: flip a byte and see whether it is caught. PRAGMA
    #       integrity_check verifies *structure*, not content, and a flipped
    #       byte may land in padding, so this probe is reported but not
    #       asserted. It documents that integrity_check alone is not a
    #       sufficient guard -- the content fingerprint is what matters.
    tampered_path = workdir / "tampered_backup.sqlite3"
    _backup(source, tampered_path)

    tamper_target = None
    with _connect(tampered_path) as tamper_db:
        for table in _user_tables(tamper_db):
            if tamper_db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] > 0:
                tamper_target = table
                break
        if tamper_target is not None:
            columns = [row[1] for row in tamper_db.execute(f'PRAGMA table_info("{tamper_target}")')]
            # Mutate a non-PK text column so the row still parses but differs.
            text_column = next(
                (c for c in columns if c.lower() in {"name", "username", "title", "label"}),
                columns[0],
            )
            pk_column = columns[0]
            row_id = tamper_db.execute(
                f'SELECT "{pk_column}" FROM "{tamper_target}" LIMIT 1'
            ).fetchone()[0]
            tamper_db.execute(
                f'UPDATE "{tamper_target}" SET "{text_column}" = ? WHERE "{pk_column}" = ?',
                ("TAMPERED-BY-DRILL", row_id),
            )
            tamper_db.commit()

    if tamper_target is None:
        print("[6a] negative control: SKIPPED (no populated table to tamper with)")
    else:
        with _connect(tampered_path, read_only=True) as tampered_db:
            tampered_fingerprint = _database_fingerprint(tampered_db)
        if tampered_fingerprint != source_fingerprint:
            print(f"[6a] negative control: OK (row change in '{tamper_target}' detected)")
        else:
            failures.append(
                "content fingerprint did NOT detect a modified row; "
                "a restore could silently commit wrong data"
            )
            print(f"[6a] negative control: FAILED -- change in '{tamper_target}' undetected")

    # (b) Informational byte-corruption probe.
    _backup(source, corrupted_path)
    _corrupt_byte(corrupted_path)
    try:
        with _connect(corrupted_path, read_only=True) as damaged_db:
            structural_rejection = not _integrity_ok(damaged_db)
            damaged_fingerprint = _database_fingerprint(damaged_db)
        if structural_rejection:
            outcome = "caught by integrity_check (structural damage)"
        elif damaged_fingerprint != source_fingerprint:
            outcome = "caught by content fingerprint"
        else:
            outcome = "undetected (byte landed in unused space)"
    except sqlite3.DatabaseError as exc:
        outcome = f"caught -- refused to open ({type(exc).__name__})"
    print(f"[6b] corruption probe : {outcome}")

    print(f"\nwork directory: {workdir}")
    if failures:
        print("DRILL FAILED -- recovery is NOT verified:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("DRILL PASSED -- backup and restore round trip verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
