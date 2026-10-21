"""Médiathèque : catalogue culturel (œuvres) ≠ bibliothèque personnelle (fichiers)."""

import hashlib
import os
import secrets
import uuid
from pathlib import Path
from ..tenancy import hh

from ..audit import audit
from ..clock import iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..validate import text_value
from . import photos as photos_svc
from .modules import require_module

WORK_KINDS = frozenset({"film", "series", "book", "music", "game"})
WORK_KIND_LABEL = {
    "film": "Film",
    "series": "Série",
    "book": "Livre",
    "music": "Musique",
    "game": "Jeu",
}
PROGRESS_STATUSES = frozenset({"wishlist", "in_progress", "done", "dropped", "favorite"})
PROGRESS_LABEL = {
    "wishlist": "Envie",
    "in_progress": "En cours",
    "done": "Terminé",
    "dropped": "Abandonné",
    "favorite": "Favori",
}
ASSET_KINDS = frozenset({"photo", "video", "audio", "other"})
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
}
KIND_BY_MIME = {
    "image/jpeg": "photo",
    "image/png": "photo",
    "image/webp": "photo",
    "audio/mpeg": "audio",
    "audio/ogg": "audio",
    "video/mp4": "video",
    "application/pdf": "other",
}
HEX = set("0123456789abcdef")
MAX_BYTES = 20 * 1024 * 1024


def _require(ctx):
    require_module(ctx, "mediatheque")
    return require_household(ctx.conn, hh(ctx))


def media_root(home):
    return Path(home) / "media" / "objects"


def asset_path(home, key):
    if not isinstance(key, str) or len(key) != 64 or any(ch not in HEX for ch in key):
        raise AppError(500, "storage", "Ouverture impossible.")
    root = media_root(home).resolve()
    path = root / key
    if path.is_symlink():
        raise AppError(500, "storage", "Ouverture impossible.")
    resolved = path.resolve()
    if resolved.parent != root:
        raise AppError(500, "storage", "Ouverture impossible.")
    return path


def ensure_media_layout(home):
    for relative in ("media/objects", "media/staging"):
        directory = Path(home) / relative
        directory.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(directory, 0o700)


def _can_see_work(ctx, person, row):
    if person.get("is_principal") or row["visibility"] == "household" or row["created_by"] == person["id"]:
        return True
    progress = ctx.conn.execute(
        "SELECT 1 FROM media_progress WHERE work_id=? AND person_id=?",
        (row["id"], person["id"]),
    ).fetchone()
    return progress is not None


def _can_see_asset(ctx, person, row):
    if person.get("is_principal") or row["uploaded_by"] == person["id"]:
        return True
    if row["visibility"] == "household":
        return True
    granted = ctx.conn.execute(
        "SELECT 1 FROM media_asset_access WHERE asset_id=? AND person_id=?",
        (row["id"], person["id"]),
    ).fetchone()
    return granted is not None


def list_works(ctx, person, *, kind="", q="", status="", page=1):
    _require(ctx)
    where = [f'w.household_id={hh(ctx)}', "w.archived=0"]
    params = {"person_id": person["id"]}
    if kind:
        if kind not in WORK_KINDS:
            raise AppError(400, "validation", "Type d'œuvre inconnu.")
        where.append("w.kind=:kind")
        params["kind"] = kind
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(w.title LIKE :q ESCAPE '\\' OR w.creator LIKE :q ESCAPE '\\')")
        params["q"] = f"%{escaped}%"
    rows = ctx.conn.execute(
        f"""SELECT w.id, w.public_id, w.kind, w.title, w.creator, w.year, w.notes, w.visibility,
                   w.created_by, w.created_at, w.updated_at,
                   p.status AS my_status, p.progress_label AS my_progress, p.progress_percent AS my_percent,
                   p.rating AS my_rating
            FROM media_work w
            LEFT JOIN media_progress p ON p.work_id=w.id AND p.person_id=:person_id
            WHERE {' AND '.join(where)}
            ORDER BY w.title, w.id LIMIT 300""",
        params,
    ).fetchall()
    photos = photos_svc.active_photo_ids(ctx, "media_work")
    items = []
    for row in rows:
        if not _can_see_work(ctx, person, row):
            continue
        if status and (row["my_status"] or "") != status:
            continue
        items.append({**_work_public(row), "photo_id": photos.get(row["id"])})
    page = max(1, int(page or 1))
    start = (page - 1) * 50
    return {"items": items[start:start + 50], "page": page, "page_size": 50, "total": len(items)}


def _work_public(row):
    return {
        "id": row["id"],
        "public_id": row["public_id"],
        "kind": row["kind"],
        "kind_label": WORK_KIND_LABEL.get(row["kind"], row["kind"]),
        "title": row["title"],
        "creator": row["creator"],
        "year": row["year"],
        "notes": row["notes"],
        "visibility": row["visibility"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "my_status": row["my_status"] if "my_status" in row.keys() else None,
        "my_status_label": PROGRESS_LABEL.get(row["my_status"], row["my_status"]) if "my_status" in row.keys() and row["my_status"] else None,
        "my_progress": row["my_progress"] if "my_progress" in row.keys() else None,
        "my_percent": row["my_percent"] if "my_percent" in row.keys() else None,
        "my_rating": row["my_rating"] if "my_rating" in row.keys() else None,
    }


def get_work(ctx, person, work_id):
    _require(ctx)
    row = ctx.conn.execute(
        f"""SELECT w.id, w.public_id, w.kind, w.title, w.creator, w.year, w.notes, w.visibility,
                  w.created_by, w.created_at, w.updated_at, w.archived,
                  p.status AS my_status, p.progress_label AS my_progress, p.progress_percent AS my_percent,
                  p.rating AS my_rating
           FROM media_work w
           LEFT JOIN media_progress p ON p.work_id=w.id AND p.person_id=?
           WHERE w.id=? AND w.household_id={hh(ctx)}""",
        (person["id"], work_id),
    ).fetchone()
    if row is None or row["archived"]:
        raise AppError(404, "not_found", "Œuvre introuvable.")
    if not _can_see_work(ctx, person, row):
        raise AppError(404, "not_found", "Œuvre introuvable.")
    payload = _work_public(row)
    payload["photo_id"] = photos_svc.active_photo_id(ctx, "media_work", row["id"])
    progress_rows = ctx.conn.execute(
        """SELECT pr.person_id, pe.display_name, pr.status, pr.progress_label, pr.progress_percent, pr.rating
           FROM media_progress pr JOIN person pe ON pe.id=pr.person_id
           WHERE pr.work_id=? ORDER BY pe.display_name""",
        (work_id,),
    ).fetchall()
    # Only show other people's progress if household visibility or principal
    if person.get("is_principal") or row["visibility"] == "household":
        payload["progress"] = [dict(r) for r in progress_rows]
    else:
        payload["progress"] = [dict(r) for r in progress_rows if r["person_id"] == person["id"]]
    return payload


def create_work(ctx, person, data):
    _require(ctx)
    kind = (data.get("kind") or "").strip()
    if kind not in WORK_KINDS:
        raise AppError(400, "validation", "Type d'œuvre inconnu.", {"kind": "Type inconnu."})
    title = text_value(data.get("title"), "title", 200, required=True, label="Le titre")
    creator = text_value(data.get("creator", ""), "creator", 200, required=False, label="Le créateur")
    notes = text_value(data.get("notes", ""), "notes", 4000, required=False, label="La note")
    visibility = (data.get("visibility") or "household").strip()
    if visibility not in {"household", "private"}:
        raise AppError(400, "validation", "Visibilité inconnue.")
    year = data.get("year")
    if year in (None, ""):
        year = None
    else:
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise AppError(400, "validation", "Année invalide.", {"year": "Année invalide."})
        if year < 1000 or year > 2100:
            raise AppError(400, "validation", "Année invalide.", {"year": "Année invalide."})
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO media_work(
                 household_id, public_id, kind, title, creator, year, notes, visibility,
                 created_by, archived, created_at, updated_at
               ) VALUES({hh(ctx)},?,?,?,?,?,?,?,?,0,?,?)""",
            (str(uuid.uuid4()), kind, title, creator, year, notes, visibility, person["id"], moment, moment),
        )
        work_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        initial_status = (data.get("status") or "wishlist").strip()
        if initial_status in PROGRESS_STATUSES:
            ctx.conn.execute(
                """INSERT INTO media_progress(work_id, person_id, status, progress_label, progress_percent, rating, notes, updated_at)
                   VALUES(?,?,?,'',NULL,NULL,'',?)""",
                (work_id, person["id"], initial_status, moment),
            )
    audit(ctx.home, ctx.clock, "media_work_create", kind, person["id"], "media_work", work_id)
    return work_id


def set_progress(ctx, person, work_id, data):
    get_work(ctx, person, work_id)
    status = (data.get("status") or "in_progress").strip()
    if status not in PROGRESS_STATUSES:
        raise AppError(400, "validation", "Statut inconnu.", {"status": "Statut inconnu."})
    progress_label = text_value(data.get("progress_label", ""), "progress_label", 120, required=False, label="La progression")
    notes = text_value(data.get("notes", ""), "notes", 2000, required=False, label="La note")
    percent = data.get("progress_percent")
    if percent in (None, ""):
        percent = None
    else:
        try:
            percent = int(percent)
        except (TypeError, ValueError):
            raise AppError(400, "validation", "Pourcentage invalide.")
        if percent < 0 or percent > 100:
            raise AppError(400, "validation", "Pourcentage invalide.")
    rating = data.get("rating")
    if rating in (None, ""):
        rating = None
    else:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            raise AppError(400, "validation", "Note invalide.")
        if rating < 1 or rating > 5:
            raise AppError(400, "validation", "Note entre 1 et 5.")
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            """INSERT INTO media_progress(work_id, person_id, status, progress_label, progress_percent, rating, notes, updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(work_id, person_id) DO UPDATE SET
                 status=excluded.status,
                 progress_label=excluded.progress_label,
                 progress_percent=excluded.progress_percent,
                 rating=excluded.rating,
                 notes=excluded.notes,
                 updated_at=excluded.updated_at""",
            (work_id, person["id"], status, progress_label, percent, rating, notes, moment),
        )
    return get_work(ctx, person, work_id)


def create_list(ctx, person, data):
    _require(ctx)
    name = text_value(data.get("name"), "name", 120, required=True, label="Le nom")
    list_kind = (data.get("list_kind") or "wishlist").strip()
    if list_kind not in {"wishlist", "collection", "custom"}:
        raise AppError(400, "validation", "Type de liste inconnu.")
    visibility = (data.get("visibility") or "private").strip()
    if visibility not in {"household", "private"}:
        raise AppError(400, "validation", "Visibilité inconnue.")
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO media_list(household_id, public_id, name, list_kind, owner_id, visibility, created_at)
               VALUES({hh(ctx)},?,?,?,?,?,?)""",
            (str(uuid.uuid4()), name, list_kind, person["id"], visibility, moment),
        )
        list_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return list_id


def list_lists(ctx, person):
    _require(ctx)
    rows = ctx.conn.execute(
        f"""SELECT id, public_id, name, list_kind, owner_id, visibility, created_at
           FROM media_list WHERE household_id={hh(ctx)}
           ORDER BY name, id"""
    ).fetchall()
    items = []
    for row in rows:
        if row["visibility"] == "household" or row["owner_id"] == person["id"] or person.get("is_principal"):
            items.append(dict(row))
    return {"items": items}


def add_to_list(ctx, person, list_id, work_id):
    _require(ctx)
    row = ctx.conn.execute(
        f'SELECT id, owner_id, visibility FROM media_list WHERE id=? AND household_id={hh(ctx)}',
        (list_id,),
    ).fetchone()
    if row is None:
        raise AppError(404, "not_found", "Liste introuvable.")
    if row["owner_id"] != person["id"] and not person.get("is_principal"):
        raise AppError(403, "forbidden", "Liste réservée à son propriétaire.")
    get_work(ctx, person, work_id)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            "INSERT OR IGNORE INTO media_list_entry(list_id, work_id, added_at) VALUES(?,?,?)",
            (list_id, work_id, moment),
        )
    return {"list_id": list_id, "work_id": work_id}


def list_assets(ctx, person, *, asset_kind="", collection="", page=1):
    _require(ctx)
    where = [f'household_id={hh(ctx)}', "archived=0"]
    params = {}
    if asset_kind:
        if asset_kind not in ASSET_KINDS:
            raise AppError(400, "validation", "Type de média inconnu.")
        where.append("asset_kind=:asset_kind")
        params["asset_kind"] = asset_kind
    if collection:
        where.append("collection=:collection")
        params["collection"] = collection.strip()
    rows = ctx.conn.execute(
        f"""SELECT id, public_id, title, asset_kind, collection, mime_type, size_bytes,
                   original_name, visibility, uploaded_by, work_id, created_at
            FROM media_asset WHERE {' AND '.join(where)}
            ORDER BY created_at DESC, id DESC LIMIT 300""",
        params,
    ).fetchall()
    items = []
    for row in rows:
        if not _can_see_asset(ctx, person, row):
            continue
        items.append({
            "id": row["id"],
            "public_id": row["public_id"],
            "title": row["title"],
            "asset_kind": row["asset_kind"],
            "collection": row["collection"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "original_name": row["original_name"] if (
                person.get("is_principal") or row["uploaded_by"] == person["id"]
            ) else None,
            "visibility": row["visibility"],
            "uploaded_by": row["uploaded_by"],
            "work_id": row["work_id"],
            "created_at": row["created_at"],
        })
    page = max(1, int(page or 1))
    start = (page - 1) * 50
    return {"items": items[start:start + 50], "page": page, "page_size": 50, "total": len(items)}


def _validate_media_upload(filename, data):
    if not filename or "/" in filename or "\\" in filename or filename.count(".") != 1:
        raise AppError(400, "validation", "Nom de fichier invalide.", {"file": "Une seule extension."})
    if len(filename) > 180:
        raise AppError(400, "validation", "Nom de fichier trop long.")
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    mime = MIME_BY_EXT.get(ext)
    if mime is None:
        raise AppError(415, "unsupported", "Type de fichier non accepté pour la médiathèque.")
    if len(data) < 1 or len(data) > MAX_BYTES:
        raise AppError(413, "too_large", "Le fichier dépasse 20 Mio.")
    # Light magic checks
    if mime == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
        raise AppError(415, "unsupported", "Contenu JPEG invalide.")
    if mime == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AppError(415, "unsupported", "Contenu PNG invalide.")
    if mime == "application/pdf" and not data.startswith(b"%PDF"):
        raise AppError(415, "unsupported", "Contenu PDF invalide.")
    return mime, KIND_BY_MIME[mime]


def store_asset(ctx, person, data, upload):
    _require(ctx)
    ensure_media_layout(ctx.home)
    if upload is None or not getattr(upload, "filename", None):
        raise AppError(400, "validation", "Choisissez un fichier.", {"file": "Choisissez un fichier."})
    chunks = []
    total = 0
    while True:
        chunk = upload.stream.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            raise AppError(413, "too_large", "Le fichier dépasse 20 Mio.")
        chunks.append(chunk)
    raw = b"".join(chunks)
    mime, asset_kind = _validate_media_upload(upload.filename, raw)
    title = text_value(data.get("title") or Path(upload.filename).stem, "title", 200, required=True, label="Le titre")
    collection = text_value(data.get("collection", ""), "collection", 120, required=False, label="La collection")
    visibility = (data.get("visibility") or "private").strip()
    if visibility not in {"household", "private"}:
        raise AppError(400, "validation", "Visibilité inconnue.")
    work_id = data.get("work_id")
    if work_id in (None, ""):
        work_id = None
    else:
        work_id = int(work_id)
        get_work(ctx, person, work_id)
    digest = hashlib.sha256(raw).hexdigest()
    key = secrets.token_hex(32)
    moment = iso_utc(ctx.clock.now())
    staging = Path(ctx.home) / "media" / "staging" / key
    final = asset_path(ctx.home, key)
    staging.parent.mkdir(parents=True, exist_ok=True)
    from flask import current_app, has_app_context
    from ..crypto import CryptoState, seal

    crypto = getattr(ctx, "crypto", None)
    if crypto is None and has_app_context():
        crypto = current_app.config.get("CRYPTO") or CryptoState(enabled=False)
    if crypto is None:
        crypto = CryptoState(enabled=False)
    payload = seal(crypto, raw)
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        with write_tx(ctx):
            ctx.conn.execute(
                f"""INSERT INTO media_asset(
                     household_id, public_id, title, asset_kind, collection, storage_key, mime_type,
                     size_bytes, sha256, original_name, visibility, uploaded_by, work_id, archived, created_at
                   ) VALUES({hh(ctx)},?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
                (
                    str(uuid.uuid4()), title, asset_kind, collection, key, mime,
                    len(raw), digest, upload.filename, visibility, person["id"], work_id, moment,
                ),
            )
            asset_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        os.replace(staging, final)
        if os.name == "posix":
            os.chmod(final, 0o600)
    except Exception:
        if staging.exists():
            staging.unlink(missing_ok=True)
        raise
    audit(ctx.home, ctx.clock, "media_asset_store", asset_kind, person["id"], "media_asset", asset_id)
    return asset_id


def get_asset(ctx, person, asset_id):
    _require(ctx)
    row = ctx.conn.execute(
        f"""SELECT id, public_id, title, asset_kind, collection, storage_key, mime_type, size_bytes,
                  sha256, original_name, visibility, uploaded_by, work_id, created_at, archived
           FROM media_asset WHERE id=? AND household_id={hh(ctx)}""",
        (asset_id,),
    ).fetchone()
    if row is None or row["archived"]:
        raise AppError(404, "not_found", "Fichier média introuvable.")
    if not _can_see_asset(ctx, person, row):
        raise AppError(404, "not_found", "Fichier média introuvable.")
    return dict(row)


def read_asset(ctx, person, asset_id):
    row = get_asset(ctx, person, asset_id)
    path = asset_path(ctx.home, row["storage_key"])
    if not path.is_file():
        raise AppError(500, "storage", "Fichier absent.")
    from flask import current_app, has_app_context
    from ..crypto import CryptoState, open_blob

    crypto = getattr(ctx, "crypto", None)
    if crypto is None and has_app_context():
        crypto = current_app.config.get("CRYPTO") or CryptoState(enabled=False)
    if crypto is None:
        crypto = CryptoState(enabled=False)
    data = open_blob(crypto, path.read_bytes())
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise AppError(500, "storage", "Empreinte incohérente.")
    return data, row["original_name"], row["mime_type"]


def grant_asset(ctx, person, asset_id, target_person_id):
    from .auth import require_principal
    require_principal(person)
    get_asset(ctx, person, asset_id)
    target = ctx.conn.execute(
        f'SELECT id, active FROM person WHERE id=? AND household_id={hh(ctx)}', (target_person_id,)
    ).fetchone()
    if target is None or not target["active"]:
        raise AppError(404, "not_found", "Personne introuvable.")
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            """INSERT OR IGNORE INTO media_asset_access(asset_id, person_id, granted_by, granted_at)
               VALUES(?,?,?,?)""",
            (asset_id, target_person_id, person["id"], moment),
        )


def dashboard(ctx, person):
    _require(ctx)
    works = list_works(ctx, person, status="in_progress", page=1)["items"][:8]
    wishlist = list_works(ctx, person, status="wishlist", page=1)["items"][:8]
    assets = list_assets(ctx, person, page=1)["items"][:8]
    return {"in_progress": works, "wishlist": wishlist, "recent_assets": assets}
