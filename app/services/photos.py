"""Photos de biens et affiches d'œuvres : une image active par objet, même visibilité que l'objet."""

import hashlib
import os
import secrets
import struct
import zlib
from pathlib import Path

from ..audit import audit
from ..clock import iso_utc
from ..db import write_tx
from ..errors import AppError
from ..tenancy import hh

OBJECT_TYPES = frozenset({"inventory_item", "media_work"})
MAX_PHOTO_BYTES = 10 * 1024 * 1024
EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_DROP = frozenset({b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"})
WEBP_DROP = frozenset({b"EXIF", b"XMP "})


def _invalid(message="Image illisible ou corrompue."):
    return AppError(415, "unsupported", message, {"photo": message})


def sniff(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(PNG_SIGNATURE):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _exif_orientation(tiff):
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return None
    order = "<" if tiff[:2] == b"II" else ">"
    if struct.unpack(order + "H", tiff[2:4])[0] != 42:
        return None
    offset = struct.unpack(order + "I", tiff[4:8])[0]
    if offset + 2 > len(tiff):
        return None
    count = struct.unpack(order + "H", tiff[offset:offset + 2])[0]
    for index in range(count):
        entry = offset + 2 + 12 * index
        if entry + 12 > len(tiff):
            return None
        tag, kind = struct.unpack(order + "HH", tiff[entry:entry + 4])
        if tag == 0x0112 and kind == 3:
            value = struct.unpack(order + "H", tiff[entry + 8:entry + 10])[0]
            return value if 1 <= value <= 8 else None
    return None


def _orientation_segment(orientation):
    tiff = b"MM\x00\x2a" + struct.pack(">IHHHIHHI", 8, 1, 0x0112, 3, 1, orientation, 0, 0)
    body = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def _keep_jpeg_app(marker, body):
    if marker == 0xE0:
        return True
    if marker == 0xE2:
        return body.startswith(b"ICC_PROFILE\x00")
    if marker == 0xEE:
        return body.startswith(b"Adobe")
    return False


def _strip_jpeg(data):
    """Retire EXIF/XMP/IPTC/commentaires et tout ce qui suit EOI ; garde l'orientation seule."""
    size = len(data)
    out = bytearray(b"\xff\xd8")
    orientation = None
    insert_at = 2
    seen_scan = False
    i = 2
    while True:
        if i >= size or data[i] != 0xFF:
            raise _invalid()
        while i < size and data[i] == 0xFF:
            i += 1
        if i >= size:
            raise _invalid()
        marker = data[i]
        i += 1
        if marker == 0xD9:
            if not seen_scan:
                raise _invalid()
            out += b"\xff\xd9"
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            out += bytes((0xFF, marker))
            continue
        if i + 2 > size:
            raise _invalid()
        length = struct.unpack(">H", data[i:i + 2])[0]
        if length < 2 or i + length > size:
            raise _invalid()
        body = data[i + 2:i + length]
        segment = bytes((0xFF, marker)) + data[i:i + length]
        i += length
        if marker == 0xE1:
            if orientation is None and body.startswith(b"Exif\x00\x00"):
                orientation = _exif_orientation(body[6:])
            continue
        if marker == 0xFE or (0xE0 <= marker <= 0xEF and not _keep_jpeg_app(marker, body)):
            continue
        out += segment
        if marker == 0xE0 and insert_at == 2 and len(out) == 2 + len(segment):
            insert_at = len(out)
        if marker == 0xDA:
            seen_scan = True
            j = i
            while True:
                j = data.find(b"\xff", j)
                if j < 0 or j + 1 >= size:
                    raise _invalid()
                following = data[j + 1]
                if following == 0x00 or 0xD0 <= following <= 0xD7:
                    j += 2
                    continue
                if following == 0xFF:
                    j += 1
                    continue
                break
            out += data[i:j]
            i = j
    if orientation and orientation != 1:
        out[insert_at:insert_at] = _orientation_segment(orientation)
    return bytes(out)


def _strip_png(data):
    out = bytearray(PNG_SIGNATURE)
    i = len(PNG_SIGNATURE)
    first = True
    while True:
        if i + 12 > len(data):
            raise _invalid()
        length = struct.unpack(">I", data[i:i + 4])[0]
        kind = data[i + 4:i + 8]
        end = i + 12 + length
        if end > len(data):
            raise _invalid()
        payload = data[i + 8:i + 8 + length]
        crc = struct.unpack(">I", data[i + 8 + length:end])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise _invalid()
        if first and kind != b"IHDR":
            raise _invalid()
        first = False
        if kind not in PNG_DROP:
            out += data[i:end]
        i = end
        if kind == b"IEND":
            return bytes(out)


def _strip_webp(data):
    declared = struct.unpack("<I", data[4:8])[0]
    if declared < 4 or 8 + declared > len(data):
        raise _invalid()
    end = 8 + declared
    body = bytearray()
    has_image = False
    i = 12
    while i < end:
        if i + 8 > end:
            raise _invalid()
        kind = data[i:i + 4]
        length = struct.unpack("<I", data[i + 4:i + 8])[0]
        padded = length + (length & 1)
        if i + 8 + length > end:
            raise _invalid()
        payload = bytearray(data[i + 8:i + 8 + length])
        i += 8 + padded
        if kind in WEBP_DROP:
            continue
        if kind == b"VP8X" and payload:
            payload[0] &= ~(0x08 | 0x04) & 0xFF
        if kind in (b"VP8 ", b"VP8L", b"VP8X"):
            has_image = True
        body += kind + struct.pack("<I", length) + payload + (b"\x00" if length & 1 else b"")
    if not has_image:
        raise _invalid()
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + bytes(body)


def sanitize(data):
    """Type réel (JPEG, PNG, WebP) et image sans métadonnées (EXIF, GPS, XMP, textes)."""
    mime = sniff(data)
    if mime is None:
        raise _invalid("Format non accepté : JPEG, PNG ou WebP uniquement.")
    if mime == "image/jpeg":
        clean = _strip_jpeg(data)
    elif mime == "image/png":
        clean = _strip_png(data)
    else:
        clean = _strip_webp(data)
    return mime, clean


def _read_upload(upload):
    if upload is None or not getattr(upload, "filename", None):
        raise AppError(400, "validation", "Choisissez une image.", {"photo": "Choisissez une image."})
    ext = Path(upload.filename).suffix.lower()
    if ext not in EXTENSIONS:
        raise _invalid("Format non accepté : JPEG, PNG ou WebP uniquement.")
    chunks = []
    total = 0
    while True:
        chunk = upload.stream.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_PHOTO_BYTES:
            raise AppError(413, "too_large", "L'image dépasse 10 Mio.", {"photo": "L'image dépasse 10 Mio."})
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        raise AppError(400, "validation", "Image vide.", {"photo": "Image vide."})
    return raw


def require_object(ctx, person, object_type, object_id):
    """Même contrôle que la fiche : module actif, foyer actif, visibilité de l'objet (sinon 404)."""
    if object_type == "inventory_item":
        from .inventory import get_item
        return get_item(ctx, person, object_id)
    if object_type == "media_work":
        from .media import get_work
        return get_work(ctx, person, object_id)
    raise AppError(404, "not_found", "Introuvable.")


def _crypto(ctx):
    from flask import current_app, has_app_context
    from ..crypto import CryptoState

    crypto = getattr(ctx, "crypto", None)
    if crypto is None and has_app_context():
        crypto = current_app.config.get("CRYPTO")
    return crypto or CryptoState(enabled=False)


def _active_row(ctx, object_type, object_id):
    return ctx.conn.execute(
        f"""SELECT id, storage_key, mime_type, size_bytes, sha256 FROM object_photo
           WHERE household_id={hh(ctx)} AND object_type=? AND object_id=? AND archived=0""",
        (object_type, int(object_id)),
    ).fetchone()


def active_photo_id(ctx, object_type, object_id):
    row = _active_row(ctx, object_type, object_id)
    return row["id"] if row else None


def active_photo_ids(ctx, object_type):
    rows = ctx.conn.execute(
        f"""SELECT object_id, id FROM object_photo
           WHERE household_id={hh(ctx)} AND object_type=? AND archived=0""",
        (object_type,),
    ).fetchall()
    return {row["object_id"]: row["id"] for row in rows}


def store_photo(ctx, person, object_type, object_id, upload):
    from ..crypto import seal
    from .media import asset_path, ensure_media_layout

    require_object(ctx, person, object_type, object_id)
    mime, clean = sanitize(_read_upload(upload))
    ensure_media_layout(ctx.home)
    key = secrets.token_hex(32)
    staging = Path(ctx.home) / "media" / "staging" / key
    final = asset_path(ctx.home, key)
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, seal(_crypto(ctx), clean))
        os.fsync(fd)
    finally:
        os.close(fd)
    moment = iso_utc(ctx.clock.now())
    try:
        with write_tx(ctx):
            previous = _active_row(ctx, object_type, object_id)
            if previous is not None:
                ctx.conn.execute("UPDATE object_photo SET archived=1 WHERE id=?", (previous["id"],))
            ctx.conn.execute(
                f"""INSERT INTO object_photo(
                     household_id, object_type, object_id, storage_key, mime_type, size_bytes, sha256,
                     uploaded_by, archived, created_at
                   ) VALUES({hh(ctx)},?,?,?,?,?,?,?,0,?)""",
                (object_type, int(object_id), key, mime, len(clean), hashlib.sha256(clean).hexdigest(),
                 person["id"], moment),
            )
            photo_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        os.replace(staging, final)
        if os.name == "posix":
            os.chmod(final, 0o600)
    except Exception:
        staging.unlink(missing_ok=True)
        raise
    if previous is not None:
        asset_path(ctx.home, previous["storage_key"]).unlink(missing_ok=True)
    audit(ctx.home, ctx.clock, "photo_store", object_type, person["id"], object_type, int(object_id))
    return photo_id


def remove_photo(ctx, person, object_type, object_id):
    from .media import asset_path

    require_object(ctx, person, object_type, object_id)
    with write_tx(ctx):
        row = _active_row(ctx, object_type, object_id)
        if row is None:
            raise AppError(404, "not_found", "Aucune photo.")
        ctx.conn.execute("UPDATE object_photo SET archived=1 WHERE id=?", (row["id"],))
    asset_path(ctx.home, row["storage_key"]).unlink(missing_ok=True)
    audit(ctx.home, ctx.clock, "photo_remove", object_type, person["id"], object_type, int(object_id))


def read_photo(ctx, person, object_type, object_id):
    from ..crypto import open_blob
    from .media import asset_path

    require_object(ctx, person, object_type, object_id)
    row = _active_row(ctx, object_type, object_id)
    if row is None:
        raise AppError(404, "not_found", "Aucune photo.")
    path = asset_path(ctx.home, row["storage_key"])
    if not path.is_file():
        raise AppError(500, "storage", "Fichier absent.")
    data = open_blob(_crypto(ctx), path.read_bytes())
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise AppError(500, "storage", "Empreinte incohérente.")
    return data, row["mime_type"]
