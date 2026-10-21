"""Coffre : dépôt, remplacement et retrait. Les octets restent hors du web."""

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

from .auth import require_principal
from ..audit import audit
from ..clock import iso_utc
from ..errors import AppError
from ..validate import MAX_FILE_BYTES, validate_file

HEX = set("0123456789abcdef")


def object_path(home, key):
    if not isinstance(key, str) or len(key) != 64 or any(ch not in HEX for ch in key):
        raise AppError(500, "storage", "Ouverture impossible.")
    root = (Path(home) / "vault" / "objects").resolve()
    path = root / key
    if path.is_symlink():
        raise AppError(500, "storage", "Ouverture impossible.")
    resolved = path.resolve()
    if resolved.parent != root:
        raise AppError(500, "storage", "Ouverture impossible.")
    return path


def _fsync_dir(directory):
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _crypto_state(ctx=None):
    from flask import current_app, has_app_context
    from ..crypto import CryptoState

    if ctx is not None and getattr(ctx, "crypto", None) is not None:
        return ctx.crypto
    if has_app_context():
        return current_app.config.get("CRYPTO") or CryptoState(enabled=False)
    return CryptoState(enabled=False)


def _write_object(home, key, data, *, crypto=None):
    from ..crypto import seal

    staging = Path(home) / "vault" / "staging" / key
    final = object_path(home, key)
    staging.parent.mkdir(parents=True, exist_ok=True)
    state = crypto if crypto is not None else _crypto_state()
    payload = seal(state, data)
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(staging, final)
    if os.name == "posix":
        os.chmod(final, 0o600)
    _fsync_dir(final.parent)
    return final


def _read_upload(storage):
    chunks = []
    total = 0
    while True:
        chunk = storage.stream.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise AppError(413, "too_large", "Le fichier dépasse 20 Mio.")
        chunks.append(chunk)
    return b"".join(chunks)


def _insert_file(conn, milestone_id, original_name, key, mime, size, digest, person_id, moment, avoid_id=None):
    new_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM stored_file").fetchone()[0]
    if avoid_id is not None and new_id == avoid_id:
        new_id = avoid_id + 1
    conn.execute(
        """INSERT INTO stored_file(id, milestone_id, original_name, storage_key, mime_type, size_bytes,
           sha256, uploaded_by, created_at, version)
           VALUES(?,?,?,?,?,?,?,?,?,1)""",
        (new_id, milestone_id, original_name, key, mime, size, digest, person_id, moment),
    )
    return new_id


def store_file(ctx, person, milestone_id, upload, confirm, failpoint=None):
    require_principal(person)
    if confirm is not True:
        raise AppError(400, "validation", "Le dépôt doit être confirmé.", {"confirm": "Confirmation requise."})
    if isinstance(milestone_id, str) and milestone_id.isdigit():
        milestone_id = int(milestone_id)
    if isinstance(milestone_id, bool) or not isinstance(milestone_id, int):
        raise AppError(400, "validation", "Échéance requise.", {"milestone_id": "Choisissez un repère."})
    if upload is None or not getattr(upload, "filename", None):
        raise AppError(400, "validation", "Choisissez un fichier.", {"file": "Choisissez un fichier."})
    exists = ctx.conn.execute("SELECT id FROM milestone WHERE id=?", (milestone_id,)).fetchone()
    if exists is None:
        raise AppError(404, "not_found", "Introuvable.")
    data = _read_upload(upload)
    original_name, mime = validate_file(data, upload.filename)
    digest = hashlib.sha256(data).hexdigest()
    key = secrets.token_hex(32)
    crypto = _crypto_state(ctx)
    with ctx.lock.acquire():
        _write_object(ctx.home, key, data, crypto=crypto)
        if failpoint == "after_rename":
            object_path(ctx.home, key).unlink(missing_ok=True)
            raise RuntimeError("storage")
        try:
            with _immediate(ctx):
                if failpoint == "before_commit":
                    raise RuntimeError("storage")
                current = ctx.conn.execute(
                    "SELECT id FROM stored_file WHERE milestone_id=?",
                    (milestone_id,),
                ).fetchone()
                if current is not None:
                    raise AppError(409, "conflict", "Une pièce est déjà liée. Passez par le remplacement explicite.")
                new_id = _insert_file(
                    ctx.conn, milestone_id, original_name, key, mime, len(data), digest, person["id"], iso_utc(ctx.clock.now())
                )
        except Exception:
            object_path(ctx.home, key).unlink(missing_ok=True)
            raise
    audit(ctx.home, ctx.clock, "file_store", "ok", person["id"], "file", new_id)
    return {"id": new_id, "original_name": original_name, "created_at": iso_utc(ctx.clock.now()), "milestone_id": milestone_id}


def replace_file(ctx, person, file_id, upload, expected_version, confirm, failpoint=None):
    require_principal(person)
    if confirm is not True:
        raise AppError(400, "validation", "Le remplacement doit être confirmé.", {"confirm": "Confirmation requise."})
    if isinstance(expected_version, str) and expected_version.isdigit():
        expected_version = int(expected_version)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise AppError(409, "conflict", "Rechargez la pièce avant de la remplacer.")
    if upload is None or not getattr(upload, "filename", None):
        raise AppError(400, "validation", "Choisissez un fichier.", {"file": "Choisissez un fichier."})
    current = ctx.conn.execute("SELECT id, version FROM stored_file WHERE id=?", (file_id,)).fetchone()
    if current is None:
        raise AppError(404, "not_found", "Introuvable.")
    data = _read_upload(upload)
    original_name, mime = validate_file(data, upload.filename)
    digest = hashlib.sha256(data).hexdigest()
    key = secrets.token_hex(32)
    crypto = _crypto_state(ctx)
    with ctx.lock.acquire():
        _write_object(ctx.home, key, data, crypto=crypto)
        old_key = None
        try:
            with _immediate(ctx):
                row = ctx.conn.execute(
                    "SELECT id, version, storage_key, milestone_id FROM stored_file WHERE id=?",
                    (file_id,),
                ).fetchone()
                if row is None:
                    raise AppError(404, "not_found", "Introuvable.")
                if row["version"] != expected_version:
                    raise AppError(409, "conflict", "Cette pièce a changé. Rechargez le coffre.")
                old_key = row["storage_key"]
                milestone_id = row["milestone_id"]
                ctx.conn.execute("DELETE FROM stored_file WHERE id=?", (file_id,))
                new_id = _insert_file(
                    ctx.conn, milestone_id, original_name, key, mime, len(data), digest, person["id"],
                    iso_utc(ctx.clock.now()), avoid_id=file_id,
                )
        except Exception:
            object_path(ctx.home, key).unlink(missing_ok=True)
            raise
        if old_key and old_key != key and failpoint != "after_commit_before_cleanup":
            try:
                object_path(ctx.home, old_key).unlink(missing_ok=True)
            except OSError:
                audit(ctx.home, ctx.clock, "file_replace_cleanup", "error", person["id"], "file", new_id)
    audit(ctx.home, ctx.clock, "file_replace", "ok", person["id"], "file", new_id)
    return {"id": new_id, "original_name": original_name, "milestone_id": milestone_id}


def delete_file(ctx, person, file_id, confirm):
    require_principal(person)
    if confirm is not True:
        raise AppError(400, "validation", "Le retrait doit être confirmé.", {"confirm": "Confirmation requise."})
    with ctx.lock.acquire():
        with _immediate(ctx):
            row = ctx.conn.execute("SELECT storage_key FROM stored_file WHERE id=?", (file_id,)).fetchone()
            if row is None:
                raise AppError(404, "not_found", "Introuvable.")
            key = row["storage_key"]
            ctx.conn.execute("DELETE FROM stored_file WHERE id=?", (file_id,))
        object_path(ctx.home, key).unlink(missing_ok=True)
    audit(ctx.home, ctx.clock, "file_delete", "ok", person["id"], "file", file_id)


class _immediate:
    def __init__(self, ctx):
        self.ctx = ctx

    def __enter__(self):
        self.ctx.conn.execute("BEGIN IMMEDIATE")
        return self.ctx.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.ctx.conn.commit()
        else:
            self.ctx.conn.rollback()
        return False


def list_files(ctx, person):
    if person["is_principal"]:
        rows = ctx.conn.execute(
            """SELECT f.id, f.original_name, f.created_at, f.version, f.milestone_id, m.name AS milestone_name
               FROM stored_file f JOIN milestone m ON m.id=f.milestone_id
               ORDER BY f.created_at, f.id"""
        ).fetchall()
    else:
        rows = ctx.conn.execute(
            """SELECT f.id, f.original_name, f.created_at, f.version
               FROM stored_file f
               JOIN file_access a ON a.file_id=f.id AND a.person_id=?
               ORDER BY f.created_at, f.id""",
            (person["id"],),
        ).fetchall()
        return [
            {"id": row["id"], "original_name": row["original_name"], "created_at": row["created_at"], "version": row["version"]}
            for row in rows
        ]
    items = []
    for row in rows:
        item = {
            "id": row["id"],
            "original_name": row["original_name"],
            "created_at": row["created_at"],
            "version": row["version"],
        }
        if person["can_view_index"]:
            item["milestone_id"] = row["milestone_id"]
            item["milestone_name"] = row["milestone_name"]
        items.append(item)
    return items


def read_file(ctx, person, file_id):
    row = ctx.conn.execute(
        """SELECT f.id, f.original_name, f.storage_key, f.mime_type, f.size_bytes, f.sha256
           FROM stored_file f
           JOIN person p ON p.id=?
           WHERE f.id=? AND p.active=1 AND (
             p.is_principal=1 OR EXISTS(SELECT 1 FROM file_access a WHERE a.file_id=f.id AND a.person_id=p.id)
           )""",
        (person["id"], file_id),
    ).fetchone()
    if row is None:
        raise AppError(404, "not_found", "Introuvable.")
    path = object_path(ctx.home, row["storage_key"])
    if not path.is_file():
        audit(ctx.home, ctx.clock, "file_open", "missing", person["id"], "file", file_id)
        if person["is_principal"]:
            raise AppError(500, "storage", "La pièce est introuvable dans le stockage. La référence est conservée.")
        raise AppError(500, "storage", "Ouverture impossible.")
    from ..crypto import open_blob

    sealed = path.read_bytes()
    data = open_blob(_crypto_state(ctx), sealed)
    digest = hashlib.sha256(data).hexdigest()
    if digest != row["sha256"] or len(data) != row["size_bytes"]:
        audit(ctx.home, ctx.clock, "file_open", "mismatch", person["id"], "file", file_id)
        if person["is_principal"]:
            raise AppError(500, "storage", "La pièce ne correspond plus à son empreinte. La référence est conservée.")
        raise AppError(500, "storage", "Ouverture impossible.")
    audit(ctx.home, ctx.clock, "file_open", "ok", person["id"], "file", file_id)
    return data, row["original_name"], row["mime_type"]


def reconcile(home, conn, object_grace=86400, staging_grace=3600):
    now = time.time()
    referenced = {
        row["storage_key"]
        for row in conn.execute("SELECT storage_key FROM stored_file").fetchall()
    }
    objects = Path(home) / "vault" / "objects"
    staging = Path(home) / "vault" / "staging"
    _sweep(objects, referenced, now, object_grace, keep_referenced=True)
    _sweep(staging, set(), now, staging_grace, keep_referenced=False)


def _sweep(directory, referenced, now, grace, keep_referenced):
    if not directory.exists():
        return
    for entry in directory.iterdir():
        if entry.name.startswith("."):
            continue
        try:
            age = now - entry.lstat().st_mtime
        except OSError:
            continue
        if age < grace:
            continue
        if keep_referenced and entry.name in referenced:
            continue
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
