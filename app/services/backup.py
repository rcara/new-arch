"""Sauvegarde cohérente et restauration dans un dossier neuf."""

import json
import os
import shutil
import sqlite3
from pathlib import Path

from ..audit import audit
from ..clock import iso_utc
from ..errors import AppError
from .vault import HEX, object_path


def create_backup(ctx):
    stamp = ctx.clock.now().strftime("%Y%m%dT%H%M%SZ")
    final = Path(ctx.home) / "backups" / f"foyer-{stamp}"
    partial = Path(ctx.home) / "backups" / f".partial-{stamp}"
    if final.exists():
        final = Path(ctx.home) / "backups" / f"foyer-{stamp}-b"
    with ctx.lock.acquire(wait=30):
        if partial.exists():
            shutil.rmtree(partial)
        partial.mkdir(parents=True)
        try:
            snapshot = partial / "metadata.sqlite"
            dest = sqlite3.connect(snapshot)
            try:
                ctx.conn.backup(dest)
            finally:
                dest.close()
            check = sqlite3.connect(snapshot)
            check.row_factory = sqlite3.Row
            try:
                integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise AppError(500, "storage", "Sauvegarde interrompue : base incohérente.")
                version = check.execute("PRAGMA user_version").fetchone()[0]
                rows = check.execute(
                    "SELECT storage_key, sha256, size_bytes FROM stored_file ORDER BY id"
                ).fetchall()
            finally:
                check.close()
            objects = partial / "objects"
            objects.mkdir()
            files = []
            for row in rows:
                source = object_path(ctx.home, row["storage_key"])
                if not source.is_file():
                    raise AppError(500, "storage", "Sauvegarde interrompue : une pièce référencée est absente.")
                data = source.read_bytes()
                import hashlib
                if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                    raise AppError(500, "storage", "Sauvegarde interrompue : une pièce ne correspond pas à son empreinte.")
                target = objects / row["storage_key"]
                target.write_bytes(data)
                if os.name == "posix":
                    os.chmod(target, 0o600)
                files.append({
                    "storage_key": row["storage_key"],
                    "sha256": row["sha256"],
                    "size_bytes": row["size_bytes"],
                })
            manifest = {
                "schema_version": version,
                "created_at": iso_utc(ctx.clock.now()),
                "files": files,
            }
            (partial / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(partial, final)
        except Exception:
            shutil.rmtree(partial, ignore_errors=True)
            audit(ctx.home, ctx.clock, "backup", "error")
            raise
        if os.name == "posix":
            os.chmod(final, 0o700)
    audit(ctx.home, ctx.clock, "backup", "ok")
    return final


def _reject_layout(archive):
    archive = Path(archive).resolve()
    if not archive.is_dir():
        raise AppError(400, "validation", "L'archive de sauvegarde est introuvable.")
    for path in archive.rglob("*"):
        if path.is_symlink():
            raise AppError(400, "validation", "La sauvegarde contient un lien. Restauration refusée.")
        try:
            path.resolve().relative_to(archive)
        except ValueError:
            raise AppError(400, "validation", "La sauvegarde sort de son dossier. Restauration refusée.")
    return archive


def restore_archive(archive, dest, clock):
    archive = _reject_layout(archive)
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise AppError(409, "conflict", "Le dossier de destination n'est pas vide.")
    manifest_path = archive / "manifest.json"
    database = archive / "metadata.sqlite"
    if not manifest_path.is_file() or not database.is_file():
        raise AppError(400, "validation", "La sauvegarde est incomplète.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise AppError(400, "validation", "La base sauvegardée est incohérente.")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise AppError(400, "validation", "La base sauvegardée a des liens cassés.")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != manifest.get("schema_version") or version not in {2, 3, 4, 5}:
            raise AppError(400, "validation", "La version de la sauvegarde n'est pas acceptée.")
        rows = conn.execute("SELECT storage_key, sha256, size_bytes FROM stored_file ORDER BY storage_key").fetchall()
    finally:
        conn.close()
    listed = sorted(manifest.get("files", []), key=lambda item: item["storage_key"])
    expected = [{"storage_key": row["storage_key"], "sha256": row["sha256"], "size_bytes": row["size_bytes"]} for row in rows]
    if listed != expected:
        raise AppError(400, "validation", "Le manifeste ne correspond pas aux pièces.")
    import hashlib
    for item in listed:
        key = item["storage_key"]
        if not isinstance(key, str) or len(key) != 64 or any(ch not in HEX for ch in key):
            raise AppError(400, "validation", "Une clé de pièce est invalide.")
        source = archive / "objects" / key
        if source.is_symlink() or not source.is_file():
            raise AppError(400, "validation", "Une pièce de la sauvegarde est absente.")
        data = source.read_bytes()
        if len(data) != item["size_bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise AppError(400, "validation", "Une pièce de la sauvegarde ne correspond pas à son empreinte.")
    dest.mkdir(parents=True, exist_ok=True)
    for relative in ("data", "vault/objects", "vault/staging", "backups", "logs"):
        (dest / relative).mkdir(parents=True, exist_ok=True)
    shutil.copy2(database, dest / "data" / "metadata.sqlite")
    for item in listed:
        shutil.copy2(archive / "objects" / item["storage_key"], dest / "vault" / "objects" / item["storage_key"])
    restored = sqlite3.connect(dest / "data" / "metadata.sqlite")
    try:
        restored.execute("PRAGMA foreign_keys=ON")
        moment = iso_utc(clock.now())
        restored.execute("BEGIN")
        restored.execute("UPDATE session SET revoked_at=? WHERE revoked_at IS NULL", (moment,))
        restored.execute("COMMIT")
    finally:
        restored.close()
    if os.name == "posix":
        os.chmod(dest / "data" / "metadata.sqlite", 0o600)
        for directory in (dest / "data", dest / "vault", dest / "vault" / "objects", dest / "backups", dest / "logs"):
            os.chmod(directory, 0o700)
    return dest
