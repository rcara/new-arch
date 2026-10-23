"""D7 — photos de biens et affiches d'œuvres : dépôt, refus, visibilité, foyers, migration 008."""

import io
import json
import shutil
import sqlite3
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import MIGRATIONS, connect, init_db
from app.errors import AppError
from app.services.backup import create_backup, restore_archive
from app.services.photos import MAX_PHOTO_BYTES, sanitize
from tests.test_flows import HOST, ORIGIN, PASSWORD, Web


def _png(width=4, height=4, text=b""):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\x20\x60\x80" * width for _ in range(height))
    body = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    if text:
        body += chunk(b"tEXt", b"Comment\x00" + text)
    body += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + body


def _segment(marker, payload):
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def _exif(orientation, extra=b""):
    entries = [(0x0112, 3, 1, struct.pack(">HH", orientation, 0)), (0x8825, 4, 1, struct.pack(">I", 0))]
    ifd = struct.pack(">H", len(entries)) + b"".join(
        struct.pack(">HHI", tag, kind, count) + value for tag, kind, count, value in entries
    ) + struct.pack(">I", 0)
    return b"Exif\x00\x00" + b"MM\x00\x2a" + struct.pack(">I", 8) + ifd + extra


def _jpeg(orientation=6, trailer=b""):
    return (
        b"\xff\xd8"
        + _segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
        + _segment(0xE1, _exif(orientation, b"GPS 46.2044N 6.1432E Canon EOS"))
        + _segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>Camille</x:xmpmeta>")
        + _segment(0xED, b"Photoshop 3.0\x00IPTC secret")
        + _segment(0xFE, b"commentaire prive")
        + _segment(0xDB, b"\x00" + bytes(range(64)))
        + _segment(0xC0, b"\x08\x00\x01\x00\x01\x01\x01\x11\x00")
        + _segment(0xC4, b"\x00" + b"\x00" * 16)
        + _segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
        + b"\x12\xff\x00\x34\xff\xd0\x56"
        + b"\xff\xd9"
        + trailer
    )


def _webp():
    def chunk(kind, payload):
        return kind + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) & 1 else b"")

    vp8x = bytes((0x08 | 0x04, 0, 0, 0)) + b"\x00\x00\x00" + b"\x00\x00\x00"
    body = chunk(b"VP8X", vp8x) + chunk(b"VP8L", b"\x2f\x00\x00\x00\x00") + chunk(b"EXIF", b"MM\x00\x2aGPS") + chunk(b"XMP ", b"<xmp/>")
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def world(tmp_path, clock):
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    return web, app, home, clock


def _send(web, url, filename, content):
    data = {"csrf_token": web.token, "photo": (io.BytesIO(content), filename)}
    response = web.c.post(url, data=data, headers={"Host": HOST, "Origin": ORIGIN}, follow_redirects=True)
    web._take(response)
    return response


def _add_member(web, name, username):
    web.submit("/personnes", {
        "display_name": name, "relationship": "coloc", "with_account": "oui",
        "username": username, "password": PASSWORD, "password_confirm": PASSWORD,
    })


def _item(web, name, visibility="household"):
    created = web.api("POST", "/api/inventory/items", {"name": name, "visibility": visibility, "condition": "good"})
    assert created.status_code == 201, created.get_json()
    return created.get_json()["id"]


def _work(web, title, visibility="household"):
    created = web.api("POST", "/api/media/works", {"kind": "film", "title": title, "visibility": visibility})
    assert created.status_code == 201, created.get_json()
    return created.get_json()["id"]


def _photo_rows(home):
    conn = connect(home / "data" / "metadata.sqlite")
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM object_photo ORDER BY id")]
    finally:
        conn.close()


# --- Nettoyage des métadonnées ---------------------------------------------------------------

def test_jpeg_metadata_stripped_orientation_kept():
    mime, clean = sanitize(_jpeg(orientation=6, trailer=b"MOTION-PHOTO-VIDEO GPS"))
    assert mime == "image/jpeg"
    for secret in (b"GPS", b"Canon", b"xmpmeta", b"IPTC", b"commentaire", b"MOTION"):
        assert secret not in clean
    assert clean.endswith(b"\xff\xd9")
    assert b"\xff\xdb" in clean and b"\xff\xc0" in clean and b"\x12\xff\x00\x34\xff\xd0\x56" in clean
    exif_at = clean.index(b"Exif\x00\x00")
    assert clean.index(b"JFIF") < exif_at
    assert struct.unpack(">H", clean[exif_at + 6 + 8 + 2 + 8:exif_at + 6 + 8 + 2 + 10])[0] == 6
    _, upright = sanitize(_jpeg(orientation=1))
    assert b"Exif" not in upright


def test_png_and_webp_metadata_stripped():
    mime, clean = sanitize(_png(text=b"GPS 46.2N"))
    assert mime == "image/png"
    assert b"tEXt" not in clean and b"GPS" not in clean
    assert clean == _png()
    mime, clean = sanitize(_webp())
    assert mime == "image/webp"
    assert b"EXIF" not in clean and b"XMP " not in clean and b"GPS" not in clean
    assert clean[12:16] == b"VP8X" and clean[20] & 0x0C == 0
    assert struct.unpack("<I", clean[4:8])[0] == len(clean) - 8


@pytest.mark.parametrize("data", [
    b"GIF89a" + b"\x00" * 20,
    b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
    _png()[:-6] + b"\x00\x00\x00\x00\x00\x00",
    _jpeg()[:40],
    b"RIFF\x04\x00\x00\x00WEBP",
])
def test_sanitize_rejects_invalid(data):
    with pytest.raises(AppError) as caught:
        sanitize(data)
    assert caught.value.status == 415


# --- Dépôt, affichage, remplacement, retrait -------------------------------------------------

def test_item_photo_upload_display_replace_remove(world):
    web, app, home, clock = world
    item_id = _item(web, "Lave-linge")
    web.get(f"/inventaire/{item_id}")
    page = _send(web, f"/inventaire/{item_id}/photo", "IMG_0042.JPG", _jpeg())
    assert page.status_code == 200
    assert b"Photo enregistr" in page.data
    rows = _photo_rows(home)
    assert len(rows) == 1 and rows[0]["object_type"] == "inventory_item" and rows[0]["household_id"] == 1
    photo_url = f"/inventaire/{item_id}/photo?v={rows[0]['id']}".encode()
    assert photo_url in page.data
    assert b'alt="Photo du bien : Lave-linge"' in page.data

    served = web.get(f"/inventaire/{item_id}/photo")
    assert served.status_code == 200
    assert served.mimetype == "image/jpeg"
    assert served.headers["X-Content-Type-Options"] == "nosniff"
    assert b"GPS" not in served.data and b"Canon" not in served.data
    stored = (home / "media" / "objects" / rows[0]["storage_key"]).read_bytes()
    assert b"GPS" not in stored and b"IMG_0042" not in stored

    gallery = web.get("/inventaire")
    assert photo_url in gallery.data and b"item-thumb--photo" in gallery.data
    assert b'class="item-thumb" aria-hidden="true">L<' not in gallery.data

    web.get(f"/inventaire/{item_id}")
    _send(web, f"/inventaire/{item_id}/photo", "neuf.png", _png())
    rows = _photo_rows(home)
    assert [row["archived"] for row in rows] == [1, 0]
    assert not (home / "media" / "objects" / rows[0]["storage_key"]).exists()
    assert web.get(f"/inventaire/{item_id}/photo").mimetype == "image/png"

    removed = web.submit(f"/inventaire/{item_id}/photo/retirer", {})
    assert removed.status_code == 200 and b"Photo retir" in removed.data
    assert all(row["archived"] for row in _photo_rows(home))
    assert web.get(f"/inventaire/{item_id}/photo").status_code == 404
    gallery = web.get("/inventaire")
    assert b'class="item-thumb" aria-hidden="true">L<' in gallery.data


def test_work_poster_upload_and_gallery(world):
    web, app, home, clock = world
    work_id = _work(web, "Le Grand Bleu")
    web.get(f"/mediatheque/oeuvres/{work_id}")
    page = _send(web, f"/mediatheque/oeuvres/{work_id}/affiche", "affiche.webp", _webp())
    assert page.status_code == 200
    rows = _photo_rows(home)
    assert rows[0]["object_type"] == "media_work" and rows[0]["mime_type"] == "image/webp"
    served = web.get(f"/mediatheque/oeuvres/{work_id}/affiche")
    assert served.status_code == 200 and served.mimetype == "image/webp"
    catalogue = web.get("/mediatheque")
    assert f"/mediatheque/oeuvres/{work_id}/affiche?v={rows[0]['id']}".encode() in catalogue.data
    assert b"poster-art--photo" in catalogue.data
    other = _work(web, "Sans affiche")
    catalogue = web.get("/mediatheque")
    assert f"/mediatheque/oeuvres/{other}/affiche".encode() not in catalogue.data
    assert b'<span class="poster-art" aria-hidden="true">' in catalogue.data


@pytest.mark.parametrize("filename,content,status", [
    ("anim.gif", b"GIF89a" + b"\x00" * 20, 415),
    ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", 415),
    ("faux.jpg", b"%PDF-1.7 pas une image", 415),
    ("casse.png", _png()[:30], 415),
    ("vide.jpg", b"", 400),
    ("enorme.jpg", b"\xff\xd8\xff" + b"\x00" * MAX_PHOTO_BYTES, 413),
])
def test_upload_rejections(world, filename, content, status):
    web, app, home, clock = world
    item_id = _item(web, "Vélo")
    web.get(f"/inventaire/{item_id}")
    response = _send(web, f"/inventaire/{item_id}/photo", filename, content)
    assert response.status_code == status
    assert b'role="alert"' in response.data and b'aria-invalid="true"' in response.data
    assert _photo_rows(home) == []
    assert list((home / "media" / "staging").iterdir()) == []


def test_upload_requires_csrf_and_login(world):
    web, app, home, clock = world
    item_id = _item(web, "Vélo")
    forged = web.c.post(
        f"/inventaire/{item_id}/photo",
        data={"photo": (io.BytesIO(_png()), "a.png")},
        headers={"Host": HOST, "Origin": ORIGIN},
    )
    assert forged.status_code in (400, 403)
    assert _photo_rows(home) == []
    web.get(f"/inventaire/{item_id}")
    _send(web, f"/inventaire/{item_id}/photo", "a.png", _png())
    web.submit("/deconnexion", {}, follow=False)
    anonymous = web.get(f"/inventaire/{item_id}/photo")
    assert anonymous.status_code == 302 and "/connexion" in anonymous.headers["Location"]


# --- Visibilité et cloisonnement -------------------------------------------------------------

def test_private_photos_never_leak_to_other_members(world):
    web, app, home, clock = world
    _add_member(web, "Sam", "sam")
    private_item = _item(web, "Bijou familial", "private")
    shared_item = _item(web, "Canapé")
    private_work = _work(web, "Journal intime", "private")
    for url in (f"/inventaire/{private_item}/photo", f"/inventaire/{shared_item}/photo",
                f"/mediatheque/oeuvres/{private_work}/affiche"):
        web.get("/inventaire")
        assert _send(web, url, "p.png", _png()).status_code == 200
    assert len(_photo_rows(home)) == 3

    web.submit("/deconnexion", {}, follow=False)
    web.login("sam")
    assert web.get(f"/inventaire/{private_item}/photo").status_code == 404
    assert web.get(f"/mediatheque/oeuvres/{private_work}/affiche").status_code == 404
    assert web.get(f"/inventaire/{shared_item}/photo").status_code == 200
    gallery = web.get("/inventaire")
    assert f"/inventaire/{private_item}/photo".encode() not in gallery.data
    assert f"/inventaire/{shared_item}/photo".encode() in gallery.data
    assert f"/mediatheque/oeuvres/{private_work}/affiche".encode() not in web.get("/mediatheque").data

    web.get("/inventaire")
    assert _send(web, f"/inventaire/{private_item}/photo", "x.png", _png()).status_code == 404
    assert web.submit(f"/inventaire/{private_item}/photo/retirer", {}).status_code == 404
    assert web.submit(f"/mediatheque/oeuvres/{private_work}/affiche/retirer", {}).status_code == 404
    assert [row["archived"] for row in _photo_rows(home)] == [0, 0, 0]


def test_backup_and_restore_include_photos(world, tmp_path):
    web, app, home, clock = world
    item_id = _item(web, "Piano")
    web.get("/inventaire")
    _send(web, f"/inventaire/{item_id}/photo", "piano.jpg", _jpeg())
    key = _photo_rows(home)[0]["storage_key"]
    conn = connect(home / "data" / "metadata.sqlite")
    archive = create_backup(Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"]))
    conn.close()
    manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 9
    assert key in {item["storage_key"] for item in manifest["media_files"]}
    dest = tmp_path / "restaure"
    restore_archive(archive, dest, clock)
    assert (dest / "media" / "objects" / key).read_bytes() == (home / "media" / "objects" / key).read_bytes()


# --- Migration 008 sur une copie de base existante ---------------------------------------------

def _v7_database(path):
    conn = sqlite3.connect(path)
    for name in ("001_schema", "002_concurrency", "003_v2_foundation", "004_finances",
                 "005_inventory", "006_mediatheque", "007_multi_household"):
        conn.executescript((MIGRATIONS / f"{name}.sql").read_text(encoding="utf-8"))
    t = "2027-02-20T09:00:00Z"
    conn.execute("INSERT INTO household(id, name, timezone, created_at) VALUES(1,'Démo','Europe/Zurich',?)", (t,))
    conn.execute("INSERT INTO person(id, display_name, is_principal, created_at, household_id) VALUES(1,'Roger',1,?,1)", (t,))
    conn.execute(
        """INSERT INTO inventory_item(public_id, name, created_by, created_at, updated_at, visibility)
           VALUES(?, 'Lave-linge', 1, ?, ?, 'private')""",
        ("a" * 36, t, t),
    )
    conn.execute(
        """INSERT INTO media_work(public_id, kind, title, created_by, created_at, updated_at)
           VALUES(?, 'book', 'Le Petit Prince', 1, ?, ?)""",
        ("b" * 36, t, t),
    )
    conn.commit()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    conn.close()


def _snapshot(path):
    conn = sqlite3.connect(path)
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}
    finally:
        conn.close()


def test_migration_008_on_copy_of_existing_v7_database(tmp_path):
    original = tmp_path / "prod" / "metadata.sqlite"
    original.parent.mkdir()
    _v7_database(original)
    before = _snapshot(original)
    copy = tmp_path / "copie" / "metadata.sqlite"
    copy.parent.mkdir()
    shutil.copy2(original, copy)

    init_db(copy)
    after = _snapshot(copy)
    added = {"object_photo", "sejour", "sejour_participant", "sejour_envelope_line", "sejour_expense"}
    assert set(after) == set(before) | added
    for table in added:
        assert after[table] == []
    for table, rows in before.items():
        assert after[table] == rows, table
    conn = sqlite3.connect(copy)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO object_photo(household_id, object_type, object_id, storage_key, mime_type, size_bytes,
               sha256, uploaded_by, created_at) VALUES(1,'inventory_item',1,?,'image/gif',10,?,1,'t')""",
            ("c" * 64, "d" * 64),
        )
    conn.close()
    assert _snapshot(original) == before

    init_db(copy)
    assert _snapshot(copy) == after

    conn = sqlite3.connect(copy)
    conn.executescript((MIGRATIONS / "rollback" / "009_sejour_down.sql").read_text(encoding="utf-8"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    conn.executescript((MIGRATIONS / "rollback" / "008_object_photo_down.sql").read_text(encoding="utf-8"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    conn.close()
    assert _snapshot(copy) == before
    init_db(copy)
    assert _snapshot(copy) == after


def test_one_active_photo_per_object_enforced(tmp_path):
    db_path = tmp_path / "metadata.sqlite"
    _v7_database(db_path)
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    insert = """INSERT INTO object_photo(household_id, object_type, object_id, storage_key, mime_type, size_bytes,
                sha256, uploaded_by, created_at) VALUES(1,'inventory_item',1,?,'image/png',10,?,1,'t')"""
    conn.execute(insert, ("a" * 64, "f" * 64))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("b" * 64, "f" * 64))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM object_photo")
    conn.close()
