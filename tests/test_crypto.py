"""Chiffrement au repos des blobs — AES-GCM, pas de cosmétique SQLite."""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.crypto import MAGIC, enable, is_ciphertext, load_state, migrate_tree, open_blob, status, unlock
from app.db import connect
from app.errors import AppError
from app.services.backup import create_backup, restore_archive
from tests.test_flows import PASSWORD, PDF, Web

PASSPHRASE = "coffre-secret-12"


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


def test_crypto_enable_seal_and_unlock(tmp_path, clock):
    home = tmp_path / "enc"
    create_app(home=home, clock=clock, testing=True)
    assert status(home)["enabled"] is False
    state = enable(home, PASSPHRASE)
    assert state.enabled and state.dek
    assert status(home)["enabled"] is True
    assert status(home)["sqlite_encrypted"] is False

    locked = load_state(home)  # sans env
    assert locked.enabled and locked.dek is None
    with pytest.raises(AppError) as err:
        open_blob(locked, MAGIC + b"\x00" * 40)
    assert err.value.status == 503

    opened = unlock(home, PASSPHRASE)
    sealed = __import__("app.crypto", fromlist=["seal"]).seal(opened, b"document-secret")
    assert is_ciphertext(sealed)
    assert open_blob(opened, sealed) == b"document-secret"

    with pytest.raises(AppError):
        unlock(home, "mauvaise-phrase-99")


def test_vault_writes_ciphertext_when_unlocked(tmp_path, clock, monkeypatch):
    home = tmp_path / "vault-enc"
    monkeypatch.setenv("FOYER_PASSPHRASE", PASSPHRASE)
    app = create_app(home=home, clock=clock, testing=True)
    enable(home, PASSPHRASE)
    # reload app with passphrase
    app = create_app(home=home, clock=clock, testing=True)
    assert app.config["CRYPTO"].unlocked

    web = Web(app)
    web.bootstrap()
    holder = web.api("GET", "/api/people").get_json()["items"][0]["id"]
    mid = web.api("POST", "/api/milestones", {
        "name": "Titre", "category": "Logement", "holder_id": holder,
    }).get_json()["id"]
    assert web.upload("/coffre", "titre.pdf", PDF, milestone_id=str(mid), confirm="oui").status_code == 200

    blob = next((home / "vault" / "objects").iterdir())
    raw = blob.read_bytes()
    assert is_ciphertext(raw)
    assert PDF not in raw  # pas de clair sur disque
    assert MAGIC == raw[:4]

    # Lecture applicative OK
    files = web.api("GET", "/api/files").get_json()["items"]
    opened = web.api("GET", f"/api/files/{files[0]['id']}/content")
    assert opened.status_code == 200
    assert opened.data == PDF


def test_migrate_existing_plaintext(tmp_path, clock, monkeypatch):
    home = tmp_path / "migrate"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    holder = web.api("GET", "/api/people").get_json()["items"][0]["id"]
    mid = web.api("POST", "/api/milestones", {
        "name": "Doc", "category": "Logement", "holder_id": holder,
    }).get_json()["id"]
    web.upload("/coffre", "a.pdf", PDF, milestone_id=str(mid), confirm="oui")
    plain_path = next((home / "vault" / "objects").iterdir())
    assert plain_path.read_bytes() == PDF

    state = enable(home, PASSPHRASE)
    result = migrate_tree(state, home)
    assert result["encrypted"] == 1
    assert is_ciphertext(plain_path.read_bytes())

    monkeypatch.setenv("FOYER_PASSPHRASE", PASSPHRASE)
    again = create_app(home=home, clock=clock, testing=True)
    client = Web(again)
    assert client.login("roger").status_code == 200
    fid = client.api("GET", "/api/files").get_json()["items"][0]["id"]
    assert client.api("GET", f"/api/files/{fid}/content").data == PDF


def test_backup_restore_preserves_sealed_blobs(tmp_path, clock, monkeypatch):
    home = tmp_path / "bak"
    monkeypatch.setenv("FOYER_PASSPHRASE", PASSPHRASE)
    app = create_app(home=home, clock=clock, testing=True)
    enable(home, PASSPHRASE)
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    holder = web.api("GET", "/api/people").get_json()["items"][0]["id"]
    mid = web.api("POST", "/api/milestones", {
        "name": "Doc", "category": "Logement", "holder_id": holder,
    }).get_json()["id"]
    web.upload("/coffre", "a.pdf", PDF, milestone_id=str(mid), confirm="oui")

    conn = connect(home / "data" / "metadata.sqlite")
    ctx = Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"], crypto=app.config["CRYPTO"])
    archive = create_backup(ctx)
    conn.close()
    assert (archive / "crypto.json").is_file()
    manifest = __import__("json").loads((archive / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["at_rest_encryption"] is True
    sealed = next((archive / "objects").iterdir()).read_bytes()
    assert is_ciphertext(sealed)

    dest = tmp_path / "restored"
    restore_archive(archive, dest, clock)
    assert (dest / "data" / "crypto.json").is_file()
    monkeypatch.setenv("FOYER_PASSPHRASE", PASSPHRASE)
    restored_app = create_app(home=dest, clock=clock, testing=True)
    client = Web(restored_app)
    assert client.login("roger").status_code == 200
    fid = client.api("GET", "/api/files").get_json()["items"][0]["id"]
    assert client.api("GET", f"/api/files/{fid}/content").data == PDF
