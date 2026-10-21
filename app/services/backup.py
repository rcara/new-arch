"""Sauvegarde cohérente et restauration dans un dossier neuf (vault + média)."""

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

from ..audit import audit
from ..clock import iso_utc
from ..errors import AppError
from .media import asset_path, ensure_media_layout
from .vault import HEX, object_path

ACCEPTED_SCHEMA = frozenset({2, 3, 4, 5, 6, 7})


def _copy_hashed_objects(home, rows, source_resolver, dest_dir, crypto=None):
    """Copie les blobs ; vérifie l'empreinte du clair (déchiffre si NAE1)."""
    from ..crypto import CryptoState, is_ciphertext, open_blob, require_unlocked

    state = crypto or CryptoState(enabled=False)
    dest_dir.mkdir(parents=True, exist_ok=True)
    listed = []
    for row in rows:
        source = source_resolver(home, row["storage_key"])
        if not source.is_file():
            raise AppError(500, "storage", "Sauvegarde interrompue : une pièce référencée est absente.")
        on_disk = source.read_bytes()
        if is_ciphertext(on_disk):
            require_unlocked(state)
            plain = open_blob(state, on_disk)
        else:
            plain = on_disk
        if len(plain) != row["size_bytes"] or hashlib.sha256(plain).hexdigest() != row["sha256"]:
            raise AppError(500, "storage", "Sauvegarde interrompue : une pièce ne correspond pas à son empreinte.")
        # Conserve le format disque (chiffré si activé) dans l'archive.
        target = dest_dir / row["storage_key"]
        target.write_bytes(on_disk)
        if os.name == "posix":
            os.chmod(target, 0o600)
        listed.append({
            "storage_key": row["storage_key"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "sealed": is_ciphertext(on_disk),
        })
    return listed


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
                vault_rows = check.execute(
                    "SELECT storage_key, sha256, size_bytes FROM stored_file ORDER BY id"
                ).fetchall()
                media_rows = []
                tables = {
                    row[0]
                    for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "media_asset" in tables:
                    media_rows = check.execute(
                        "SELECT storage_key, sha256, size_bytes FROM media_asset WHERE archived=0 ORDER BY id"
                    ).fetchall()
            finally:
                check.close()
            crypto = getattr(ctx, "crypto", None)
            files = _copy_hashed_objects(ctx.home, vault_rows, object_path, partial / "objects", crypto=crypto)
            media_files = _copy_hashed_objects(ctx.home, media_rows, asset_path, partial / "media", crypto=crypto)
            crypto_meta = Path(ctx.home) / "data" / "crypto.json"
            blobs_sealed = any(item.get("sealed") for item in files + media_files)
            if blobs_sealed and crypto_meta.is_file():
                shutil.copy2(crypto_meta, partial / "crypto.json")
            manifest = {
                "manifest_version": 2,
                "schema_version": version,
                "created_at": iso_utc(ctx.clock.now()),
                "files": files,
                "media_files": media_files,
                "at_rest_encryption": bool(blobs_sealed),
            }
            (partial / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
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


def _verify_object_bundle(archive_subdir, listed, expected_rows):
    from ..crypto import is_ciphertext

    expected_by_key = {
        row["storage_key"]: {"sha256": row["sha256"], "size_bytes": row["size_bytes"]}
        for row in expected_rows
    }
    sorted_listed = sorted(listed, key=lambda item: item["storage_key"])
    if [item["storage_key"] for item in sorted_listed] != sorted(expected_by_key.keys()):
        raise AppError(400, "validation", "Le manifeste ne correspond pas aux pièces.")
    for item in sorted_listed:
        key = item["storage_key"]
        if not isinstance(key, str) or len(key) != 64 or any(ch not in HEX for ch in key):
            raise AppError(400, "validation", "Une clé de pièce est invalide.")
        exp = expected_by_key[key]
        if item.get("sha256") != exp["sha256"] or item.get("size_bytes") != exp["size_bytes"]:
            raise AppError(400, "validation", "Le manifeste ne correspond pas aux pièces.")
        source = archive_subdir / key
        if source.is_symlink() or not source.is_file():
            raise AppError(400, "validation", "Une pièce de la sauvegarde est absente.")
        data = source.read_bytes()
        sealed = bool(item.get("sealed")) or is_ciphertext(data)
        if sealed:
            if not is_ciphertext(data):
                raise AppError(400, "validation", "Une pièce chiffrée de la sauvegarde est invalide.")
        else:
            if len(data) != item["size_bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise AppError(400, "validation", "Une pièce de la sauvegarde ne correspond pas à son empreinte.")


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
        if version != manifest.get("schema_version") or version not in ACCEPTED_SCHEMA:
            raise AppError(400, "validation", "La version de la sauvegarde n'est pas acceptée.")
        vault_rows = conn.execute(
            "SELECT storage_key, sha256, size_bytes FROM stored_file ORDER BY storage_key"
        ).fetchall()
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        media_rows = []
        if "media_asset" in tables:
            media_rows = conn.execute(
                "SELECT storage_key, sha256, size_bytes FROM media_asset WHERE archived=0 ORDER BY storage_key"
            ).fetchall()
    finally:
        conn.close()

    vault_listed = sorted(manifest.get("files", []), key=lambda item: item["storage_key"])
    _verify_object_bundle(archive / "objects", vault_listed, vault_rows)

    media_listed = sorted(manifest.get("media_files", []), key=lambda item: item["storage_key"])
    # Anciennes sauvegardes sans media_files : OK seulement si aucune asset en base
    if media_rows and "media_files" not in manifest:
        raise AppError(400, "validation", "La sauvegarde omet les fichiers média référencés.")
    if media_rows or media_listed:
        media_dir = archive / "media"
        if not media_dir.is_dir() and media_listed:
            raise AppError(400, "validation", "Le dossier média de la sauvegarde est absent.")
        _verify_object_bundle(media_dir if media_dir.is_dir() else archive / "media", media_listed, media_rows)

    dest.mkdir(parents=True, exist_ok=True)
    for relative in ("data", "vault/objects", "vault/staging", "media/objects", "media/staging", "backups", "logs"):
        (dest / relative).mkdir(parents=True, exist_ok=True)
    shutil.copy2(database, dest / "data" / "metadata.sqlite")
    crypto_src = archive / "crypto.json"
    if crypto_src.is_file():
        shutil.copy2(crypto_src, dest / "data" / "crypto.json")
        if os.name == "posix":
            os.chmod(dest / "data" / "crypto.json", 0o600)
    for item in vault_listed:
        shutil.copy2(archive / "objects" / item["storage_key"], dest / "vault" / "objects" / item["storage_key"])
    for item in media_listed:
        shutil.copy2(archive / "media" / item["storage_key"], dest / "media" / "objects" / item["storage_key"])
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
        for directory in (
            dest / "data", dest / "vault", dest / "vault" / "objects",
            dest / "media", dest / "media" / "objects", dest / "backups", dest / "logs",
        ):
            if directory.exists():
                os.chmod(directory, 0o700)
    ensure_media_layout(dest)
    return dest
