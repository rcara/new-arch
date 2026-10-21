"""Connexion SQLite, migrations, transactions d'écriture."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"

from .errors import AppError


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(path):
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript((MIGRATIONS / "001_schema.sql").read_text(encoding="utf-8"))
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 1:
            conn.executescript((MIGRATIONS / "002_concurrency.sql").read_text(encoding="utf-8"))
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 2:
            conn.executescript((MIGRATIONS / "003_v2_foundation.sql").read_text(encoding="utf-8"))
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 3:
            conn.executescript((MIGRATIONS / "004_finances.sql").read_text(encoding="utf-8"))
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 4:
            conn.executescript((MIGRATIONS / "005_inventory.sql").read_text(encoding="utf-8"))
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != 5:
            raise RuntimeError("schema incompatible")
    finally:
        conn.close()
    if os.name == "posix":
        os.chmod(path, 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists():
                os.chmod(sidecar, 0o600)


def ensure_layout(home):
    home = Path(home)
    for relative in ("data", "vault/objects", "vault/staging", "backups", "logs"):
        directory = home / relative
        directory.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(directory, 0o700)
            vault = home / "vault"
            if vault.exists():
                os.chmod(vault, 0o700)
    init_db(home / "data" / "metadata.sqlite")


@contextmanager
def write_tx(ctx, wait=5):
    with ctx.lock.acquire(wait=wait):
        ctx.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            ctx.conn.rollback()
            raise
        else:
            ctx.conn.commit()


def household_row(conn):
    return conn.execute(
        "SELECT id, name, timezone, created_at FROM household WHERE id=1"
    ).fetchone()


def require_household(conn):
    row = household_row(conn)
    if row is None:
        raise AppError(409, "conflict", "Le foyer n'est pas initialisé.")
    return row
