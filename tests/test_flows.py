"""Parcours HTTP du foyer : droits, scellement, coffre, sauvegarde."""

import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect
from app.errors import AppError
from app.services.auth import bootstrap
from app.services.backup import create_backup, restore_archive
from app.services.vault import reconcile, store_file
from app.validate import validate_file

HOST = "127.0.0.1:8765"
ORIGIN = f"http://{HOST}"
PASSWORD = "phrase-locale-12"
PDF = b"%PDF-1.4\nsecret-piece\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8


class Web:
    def __init__(self, app):
        self.app = app
        self.c = app.test_client()
        self.token = ""

    def _take(self, response):
        header = response.headers.get("X-CSRF-Token")
        if header:
            self.token = header
            return
        import re
        for pattern in (br'name="csrf-token" content="([^"]+)"', br'name="csrf_token" value="([^"]+)"'):
            found = re.search(pattern, response.data)
            if found and found.group(1):
                self.token = found.group(1).decode()
                return

    def get(self, url):
        response = self.c.get(url, headers={"Host": HOST})
        self._take(response)
        return response

    def submit(self, url, data, follow=True):
        payload = {"csrf_token": self.token, **data}
        response = self.c.post(url, data=payload, headers={"Host": HOST, "Origin": ORIGIN}, follow_redirects=follow)
        self._take(response)
        return response

    def upload(self, url, filename, content, **fields):
        payload = {"csrf_token": self.token, "file": (io.BytesIO(content), filename), **fields}
        response = self.c.post(url, data=payload, headers={"Host": HOST, "Origin": ORIGIN}, follow_redirects=True)
        self._take(response)
        return response

    def api(self, method, url, payload=None):
        kwargs = {"headers": {"Host": HOST, "Origin": ORIGIN, "X-CSRF-Token": self.token}}
        if payload is not None:
            kwargs["json"] = payload
        response = self.c.open(url, method=method, **kwargs)
        self._take(response)
        return response

    def bootstrap(self, name="Roger", username="roger"):
        self.get("/initialisation")
        return self.submit("/initialisation", {
            "household_name": "Foyer",
            "timezone": "Europe/Berlin",
            "display_name": name,
            "username": username,
            "password": PASSWORD,
            "password_confirm": PASSWORD,
        })

    def login(self, username, password=PASSWORD):
        self.get("/connexion")
        return self.submit("/connexion", {"username": username, "password": password, "next": "/"})


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


def _json(response):
    return response.get_json()


def test_un_seul_foyer_et_session(world):
    web, app, home, _clock = world
    again = web.submit("/initialisation", {
        "household_name": "Autre", "timezone": "Europe/Berlin", "display_name": "X",
        "username": "x", "password": PASSWORD, "password_confirm": PASSWORD,
    }, follow=False)
    assert again.status_code == 409
    me = _json(web.api("GET", "/api/me"))
    assert me["role"] == "principal"
    assert "password" not in me
    assert (home / "logs" / "audit.log").read_text(encoding="utf-8").find(PASSWORD) == -1


def test_bootstrap_concurrent_et_atomique(tmp_path, clock):
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    errors = []

    def attempt():
        conn = connect(home / "data" / "metadata.sqlite")
        ctx = Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"])
        try:
            bootstrap(ctx, app.config["LIMITER"], "Foyer", "Europe/Berlin", "Roger", "roger", PASSWORD)
        except AppError as exc:
            errors.append(exc.status)
        finally:
            conn.close()

    import threading
    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    conn = connect(home / "data" / "metadata.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM household").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM person WHERE is_principal=1").fetchone()[0] == 1
    conn.close()
    assert errors == [409]
    fresh = tmp_path / "vide"
    fresh_app = create_app(home=fresh, clock=clock, testing=True)
    conn = connect(fresh / "data" / "metadata.sqlite")
    ctx = Ctx(conn, clock, fresh, fresh_app.config["LOCK"], fresh_app.config["DUMMY_HASH"])
    with pytest.raises(RuntimeError):
        bootstrap(ctx, fresh_app.config["LIMITER"], "Foyer", "Europe/Berlin", "Nora", "nora", PASSWORD, failpoint="after_household")
    assert conn.execute("SELECT COUNT(*) FROM household").fetchone()[0] == 0
    conn.close()


def test_statuts_archives_et_couches(world):
    web, _app, _home, _clock = world
    people = _json(web.api("GET", "/api/people"))["items"]
    holder = people[0]["id"]
    created = web.api("POST", "/api/milestones", {
        "name": "Passeport", "category": "Identité", "holder_id": holder,
        "due_date": "2027-03-15", "notice_days": 30, "note": "rien de secret",
    })
    assert created.status_code == 201
    body = _json(created)
    assert body["status"] == "sous_30"
    assert body["has_file"] is False
    assert body["notice_date"] == "2027-02-13"
    assert "storage_key" not in body
    milestone_id = body["id"]
    updated = body["updated_at"]
    expected = {
        "2027-02-19": "expire",
        "2027-02-20": "sous_30",
        "2027-03-22": "sous_30",
        "2027-03-23": "sous_90",
        "2027-05-21": "sous_90",
        "2027-05-22": "a_jour",
        None: "sans_date",
    }
    for due, status in expected.items():
        patched = web.api("PATCH", f"/api/milestones/{milestone_id}", {"due_date": due, "updated_at": updated})
        assert patched.status_code == 200
        updated = _json(patched)["updated_at"]
        assert _json(patched)["status"] == status
    archived = web.api("PATCH", f"/api/milestones/{milestone_id}", {"archived": True, "updated_at": updated})
    assert _json(web.api("GET", "/api/today"))["counters"]["sans_date"] == 0
    assert _json(archived)["archived"] is True
    page = web.get("/").data.decode()
    assert "Passeport" not in page
    web.api("PATCH", f"/api/milestones/{milestone_id}", {"archived": False, "updated_at": _json(archived)["updated_at"]})
    choice = "CODE-SECRET-CHOIX"
    decision = web.api("POST", "/api/decisions", {
        "milestone_id": milestone_id,
        "choice": choice,
        "options": ["Renouveler"],
        "expected": "Recevoir le document",
        "reconsider_if": "Un délai trop long",
    })
    decision_id = _json(decision)["id"]
    sealed = web.api("POST", f"/api/decisions/{decision_id}/seal", {"confirm": True, "draft_version": _json(decision)["draft_version"]})
    assert sealed.status_code == 200
    refused = web.api("PATCH", f"/api/decisions/{decision_id}", {
        "choice": "Autre", "draft_version": _json(sealed)["draft_version"],
    })
    assert refused.status_code == 409
    assert _json(web.api("GET", f"/api/decisions/{decision_id}"))["choice"] == choice
    moved = web.api("POST", "/api/decisions", {"milestone_id": 999, "choice": "x"})
    assert moved.status_code == 404
    extra = web.api("PATCH", f"/api/decisions/{decision_id}", {"milestone_id": milestone_id, "draft_version": 1})
    assert extra.status_code == 400
    today = web.get("/").data.decode()
    fiche = web.get(f"/reperes/{milestone_id}").data.decode()
    assert choice not in today and choice not in fiche
    assert "Rien d'urgent" not in today or "Expir" in today


def test_scellement_resultat_et_nouvelle_page(world):
    web, _app, home, _clock = world
    holder = _json(web.api("GET", "/api/people"))["items"][0]["id"]
    milestone_id = _json(web.api("POST", "/api/milestones", {
        "name": "Assurance", "category": "Argent et assurances", "holder_id": holder,
    }))["id"]
    draft = web.api("POST", "/api/decisions", {"milestone_id": milestone_id, "choice": ""})
    decision_id = _json(draft)["id"]
    assert web.api("POST", f"/api/decisions/{decision_id}/seal", {"confirm": True, "draft_version": 1}).status_code == 400
    assert web.api("POST", f"/api/decisions/{decision_id}/result", {"confirm": True, "body": "trop tôt"}).status_code == 409
    web.api("PATCH", f"/api/decisions/{decision_id}", {
        "choice": "Laisser courir", "options": ["Attendre"], "expected": "Aucun frais",
        "reconsider_if": "Une hausse", "rule": {"name": "Seuil", "lines": [{"label": "Hausse", "value": "10 %"}]},
        "draft_version": 1,
    })
    sealed = web.api("POST", f"/api/decisions/{decision_id}/seal", {"confirm": False, "draft_version": 2})
    assert sealed.status_code == 400
    sealed = web.api("POST", f"/api/decisions/{decision_id}/seal", {"confirm": True, "draft_version": 2})
    assert sealed.status_code == 200
    assert _json(sealed)["options"].count("Ne rien faire") == 1
    first = web.api("POST", f"/api/decisions/{decision_id}/result", {"confirm": True, "body": "Contrat reconduit"})
    assert first.status_code == 201
    assert web.api("POST", f"/api/decisions/{decision_id}/result", {"confirm": True, "body": "Autre"}).status_code == 409
    second = web.api("POST", "/api/decisions", {
        "milestone_id": milestone_id, "choice": "Renégocier", "options": ["Changer"],
        "expected": "Un meilleur tarif", "reconsider_if": "Aucun devis",
    })
    assert _json(second)["id"] != decision_id
    conn = sqlite3.connect(home / "data" / "metadata.sqlite")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM decision WHERE id=?", (decision_id,))
        conn.commit()
    conn.close()


def test_droits_separes_revocation_et_retrait(world):
    web, app, _home, _clock = world
    roger = _json(web.api("GET", "/api/me"))["person_id"]
    alex = _json(web.api("POST", "/api/people", {"display_name": "Alex", "relationship": "enfant"}))["id"]
    sam = _json(web.api("POST", "/api/people", {
        "display_name": "Sam", "relationship": "conjoint", "username": "sam", "password": PASSWORD,
    }))["id"]
    milestone_id = _json(web.api("POST", "/api/milestones", {
        "name": "Passeport", "category": "Identité", "holder_id": alex, "due_date": "2027-03-15",
    }))["id"]
    decision_id = _json(web.api("POST", "/api/decisions", {
        "milestone_id": milestone_id, "choice": "CODE-SECRET-CHOIX", "options": ["Renouveler"],
        "expected": "Le document", "reconsider_if": "Un long délai",
    }))["id"]
    web.api("POST", f"/api/decisions/{decision_id}/seal", {"confirm": True, "draft_version": 1})
    stored = web.upload("/coffre", "piece-secrete.pdf", PDF, milestone_id=str(milestone_id), confirm="oui")
    assert stored.status_code == 200
    file_id = _json(web.api("GET", "/api/files"))["items"][0]["id"]
    sam_web = Web(app)
    assert sam_web.login("sam").status_code == 200
    assert "Personne" not in sam_web.get("/").data.decode() or "Personnes" not in sam_web.get("/personnes").data.decode()
    assert sam_web.get("/personnes").status_code == 403
    assert _json(sam_web.api("GET", "/api/decisions"))["items"] == []
    assert _json(sam_web.api("GET", "/api/files"))["items"] == []
    hidden = sam_web.api("GET", f"/api/decisions/{decision_id}")
    assert hidden.status_code == 404
    assert b"CODE-SECRET-CHOIX" not in hidden.data
    missing = sam_web.api("GET", f"/api/files/{file_id}/content")
    assert missing.status_code == 404
    assert b"piece-secrete" not in missing.data
    assert web.api("PUT", f"/api/people/{sam}/decisions/{decision_id}").status_code == 204
    granted = _json(sam_web.api("GET", f"/api/decisions/{decision_id}"))
    assert granted["choice"] == "CODE-SECRET-CHOIX"
    assert sam_web.api("GET", f"/api/files/{file_id}/content").status_code == 404
    web.api("PUT", f"/api/people/{sam}/index-access", {"allowed": False})
    assert sam_web.api("GET", "/api/today").status_code == 403
    without_index = _json(sam_web.api("GET", f"/api/decisions/{decision_id}"))
    assert "milestone_name" not in without_index and "milestone_id" not in without_index
    assert without_index["choice"] == "CODE-SECRET-CHOIX"
    web.api("PUT", f"/api/people/{sam}/files/{file_id}")
    opened = sam_web.api("GET", f"/api/files/{file_id}/content")
    assert opened.status_code == 200 and opened.data == PDF
    assert "attachment" in opened.headers["Content-Disposition"]
    web.api("DELETE", f"/api/people/{sam}/files/{file_id}")
    assert sam_web.api("GET", f"/api/files/{file_id}/content").status_code == 404
    replaced = web.upload(f"/coffre/{file_id}/remplacer", "nouveau.pdf", PDF + b"2", version="1", confirm="oui")
    assert replaced.status_code == 200
    new_id = _json(web.api("GET", "/api/files"))["items"][0]["id"]
    assert new_id != file_id
    assert sam_web.api("GET", f"/api/files/{new_id}/content").status_code == 404
    assert "nouveau.pdf" not in sam_web.get("/coffre").data.decode()
    web.api("PATCH", f"/api/people/{sam}", {"display_name": "Sam", "relationship": "autre"})
    assert sam_web.api("GET", f"/api/files/{new_id}/content").status_code == 404
    web.api("PUT", f"/api/people/{sam}/files/{new_id}")
    assert sam_web.api("GET", f"/api/files/{new_id}/content").status_code == 200
    assert web.api("POST", f"/api/people/{roger}/deactivate", {"confirm": True}).status_code == 409
    assert web.api("POST", f"/api/people/{sam}/deactivate", {"confirm": True}).status_code == 204
    assert sam_web.api("GET", "/api/me").status_code == 401
    assert _json(web.api("GET", f"/api/decisions/{decision_id}"))["choice"] == "CODE-SECRET-CHOIX"
    assert web.api("PUT", f"/api/people/{alex}/decisions/{decision_id}").status_code == 409


def test_depot_invalide_et_panne(world):
    web, app, home, clock = world
    holder = _json(web.api("GET", "/api/people"))["items"][0]["id"]
    milestone_id = _json(web.api("POST", "/api/milestones", {
        "name": "Scan", "category": "Santé", "holder_id": holder,
    }))["id"]
    bad = web.upload("/coffre", "note.pdf.exe", PDF, milestone_id=str(milestone_id), confirm="oui")
    assert bad.status_code == 400
    mismatched = web.upload("/coffre", "photo.jpg", PDF, milestone_id=str(milestone_id), confirm="oui")
    assert mismatched.status_code == 415
    good = web.upload("/coffre", "scan.jpg", JPEG, milestone_id=str(milestone_id), confirm="oui")
    assert good.status_code == 200
    assert "scan.jpg" not in web.get("/").data.decode()
    assert "scan.jpg" not in web.get(f"/reperes/{milestone_id}").data.decode()
    second = web.upload("/coffre", "autre.jpg", JPEG, milestone_id=str(milestone_id), confirm="oui")
    assert second.status_code == 409
    person = {"id": holder, "is_principal": True}
    conn = connect(home / "data" / "metadata.sqlite")
    ctx = Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"], holder)
    from werkzeug.datastructures import FileStorage
    other = _json(web.api("POST", "/api/milestones", {"name": "Autre", "category": "Impôts", "holder_id": holder}))["id"]
    with pytest.raises(RuntimeError):
        store_file(ctx, person, other, FileStorage(stream=io.BytesIO(PDF), filename="a.pdf"), True, failpoint="before_commit")
    assert conn.execute("SELECT COUNT(*) FROM stored_file WHERE milestone_id=?", (other,)).fetchone()[0] == 0
    conn.close()
    with pytest.raises(AppError) as raised:
        validate_file(b"%PDF-" + b"0" * (20 * 1024 * 1024), "gros.pdf")
    assert raised.value.status == 413


def test_securite_des_requetes(world):
    web, app, home, _clock = world
    evil = web.c.get("/connexion", headers={"Host": "evil.example"})
    assert evil.status_code == 400
    remote = web.c.get("/", headers={"Host": HOST}, environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert remote.status_code == 403
    web.get("/connexion")
    origin = web.c.post("/connexion", data={"csrf_token": web.token, "username": "roger", "password": "mauvais-mot-de-passe"}, headers={"Host": HOST, "Origin": "http://evil.example"})
    assert origin.status_code == 400
    unknown = web.login("personne-inconnue", "mauvais-mot-de-passe")
    wrong = web.login("roger", "mauvais-mot-de-passe")
    assert "Identifiant ou mot de passe incorrect." in unknown.data.decode()
    assert "Identifiant ou mot de passe incorrect." in wrong.data.decode()
    web.login("roger")
    missing = web.c.post("/api/milestones", json={"name": "x"}, headers={"Host": HOST, "Origin": ORIGIN})
    assert missing.status_code == 400
    app.config["LIMITER"].per_user = 2
    app.config["LIMITER"].events.clear()
    other = Web(app)
    other.login("roger", "mauvais-mot-de-passe")
    other.login("roger", "mauvais-mot-de-passe")
    limited = other.login("roger", "mauvais-mot-de-passe")
    assert "Trop de tentatives" in limited.data.decode()
    app.config["LIMITER"].events.clear()
    assert other.login("roger").status_code == 200
    text = (home / "logs" / "audit.log").read_text(encoding="utf-8")
    assert PASSWORD not in text
    launcher = Path(__file__).resolve().parents[1].joinpath("launcher.py").read_text(encoding="utf-8")
    assert "127.0.0.1" in launcher
    assert "0.0.0.0" not in launcher


def test_sauvegarde_et_restauration(world, tmp_path):
    web, app, home, clock = world
    holder = _json(web.api("GET", "/api/people"))["items"][0]["id"]
    milestone_id = _json(web.api("POST", "/api/milestones", {
        "name": "Titre", "category": "Logement", "holder_id": holder, "amount_cents": 1250,
    }))["id"]
    decision_id = _json(web.api("POST", "/api/decisions", {
        "milestone_id": milestone_id, "choice": "Garder", "options": ["Partir"],
        "expected": "Rester", "reconsider_if": "Un déménagement",
    }))["id"]
    web.api("POST", f"/api/decisions/{decision_id}/seal", {"confirm": True, "draft_version": 1})
    assert web.upload("/coffre", "titre.pdf", PDF, milestone_id=str(milestone_id), confirm="oui").status_code == 200
    conn = connect(home / "data" / "metadata.sqlite")
    ctx = Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"])
    archive = create_backup(ctx)
    blob = next((home / "vault" / "objects").iterdir())
    blob.unlink()
    with pytest.raises(AppError):
        create_backup(ctx)
    conn.close()
    dest = tmp_path / "restaure"
    restore_archive(archive, dest, clock)
    restored = sqlite3.connect(dest / "data" / "metadata.sqlite")
    assert all(row[0] for row in restored.execute("SELECT revoked_at FROM session"))
    assert restored.execute("SELECT choice FROM decision").fetchone()[0] == "Garder"
    restored.close()
    copy = (dest / "vault" / "objects").read_bytes() if False else next((dest / "vault" / "objects").iterdir()).read_bytes()
    assert copy == PDF
    again = create_app(home=dest, clock=clock, testing=True)
    client = Web(again)
    assert client.login("roger").status_code == 200
    assert _json(client.api("GET", "/api/files"))["items"][0]["original_name"] == "titre.pdf"
    assert "amount_cents" in _json(client.api("GET", f"/api/milestones/{milestone_id}"))
    occupied = tmp_path / "plein"
    occupied.mkdir()
    (occupied / "deja").write_text("x", encoding="utf-8")
    with pytest.raises(AppError):
        restore_archive(archive, occupied, clock)
    linked = tmp_path / "lien"
    import shutil
    shutil.copytree(archive, linked)
    outside = tmp_path / "dehors"
    outside.write_text("secret", encoding="utf-8")
    (linked / "objects" / "lien").symlink_to(outside)
    with pytest.raises(AppError):
        restore_archive(linked, tmp_path / "refuse", clock)


def test_performance_de_mille_reperes(world):
    web, _app, home, _clock = world
    holder = _json(web.api("GET", "/api/people"))["items"][0]["id"]
    conn = sqlite3.connect(home / "data" / "metadata.sqlite")
    conn.execute("PRAGMA foreign_keys=ON")
    rows = [
        (f"Repère {index}", "Identité", holder, "2027-06-01", "2027-02-20T08:00:00Z", "2027-02-20T08:00:00Z")
        for index in range(1000)
    ]
    conn.executemany(
        """INSERT INTO milestone(name, category, holder_id, due_date, created_at, updated_at)
           VALUES(?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    conn.close()
    import time
    started = time.perf_counter()
    response = web.api("GET", "/api/today")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert _json(response)["counters"]["a_jour"] == 1000
    assert elapsed < 1
    web.app.config["PERF_SECONDS"] = elapsed


def test_reconcile_orphelin(world):
    web, _app, home, _clock = world
    orphan = home / "vault" / "objects" / ("ab" * 32)
    orphan.write_bytes(b"orphelin")
    import os
    os.utime(orphan, (1, 1))
    reconcile(home, connect(home / "data" / "metadata.sqlite"), object_grace=0, staging_grace=0)
    assert not orphan.exists()
