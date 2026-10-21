"""Étape F — solidification : backup média, seed démo, thème, exports, parcours e2e."""

import io
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect, household_row
from app.errors import AppError
from app.security import AttemptLimiter
from app.services.backup import create_backup, restore_archive
from app.services.demo import DEMO_PASSWORD, DEMO_USERNAME, seed_demo
from tests.test_flows import PASSWORD, PDF, Web

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


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


def test_backup_includes_media_and_restore(world, tmp_path):
    web, app, home, clock = world
    work = web.api("POST", "/api/media/works", {
        "kind": "film", "title": "Film démo", "status": "wishlist",
    }).get_json()
    assert work["id"]
    response = web.c.open(
        "/api/media/assets",
        method="POST",
        data={
            "csrf_token": web.token,
            "title": "Capture",
            "visibility": "household",
            "file": (io.BytesIO(JPEG), "capture.jpg"),
        },
        headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "X-CSRF-Token": web.token},
        content_type="multipart/form-data",
    )
    web.token = response.headers.get("X-CSRF-Token") or web.token
    assert response.status_code == 201, response.get_json()

    holder = web.api("GET", "/api/people").get_json()["items"][0]["id"]
    milestone_id = web.api("POST", "/api/milestones", {
        "name": "Titre", "category": "Logement", "holder_id": holder,
    }).get_json()["id"]
    assert web.upload("/coffre", "titre.pdf", PDF, milestone_id=str(milestone_id), confirm="oui").status_code == 200

    conn = connect(home / "data" / "metadata.sqlite")
    ctx = Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"])
    archive = create_backup(ctx)
    conn.close()

    manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 2
    assert len(manifest["files"]) >= 1
    assert len(manifest["media_files"]) == 1
    assert (archive / "media" / manifest["media_files"][0]["storage_key"]).is_file()

    dest = tmp_path / "restaure-media"
    restore_archive(archive, dest, clock)
    media_key = manifest["media_files"][0]["storage_key"]
    assert (dest / "media" / "objects" / media_key).read_bytes() == JPEG
    vault_key = manifest["files"][0]["storage_key"]
    assert (dest / "vault" / "objects" / vault_key).read_bytes() == PDF

    again = create_app(home=dest, clock=clock, testing=True)
    client = Web(again)
    assert client.login("roger").status_code == 200
    assets = client.api("GET", "/api/media/assets").get_json()["items"]
    assert any(item["title"] == "Capture" for item in assets)


def test_seed_demo_refuses_existing_and_fills_empty(tmp_path, clock):
    empty = tmp_path / "demo-home"
    app = create_app(home=empty, clock=clock, testing=True)
    with app.app_context():
        conn = connect(empty / "data" / "metadata.sqlite")
        ctx = Ctx(conn, clock, empty, app.config["LOCK"], app.config["DUMMY_HASH"])
        info = seed_demo(ctx, AttemptLimiter())
        assert household_row(conn, 1)["name"] == "Maison Démo"
        assert info["username"] == DEMO_USERNAME
        assert info["password"] == DEMO_PASSWORD
        assert conn.execute("SELECT COUNT(*) FROM task").fetchone()[0] >= 2
        assert conn.execute("SELECT COUNT(*) FROM finance_transaction").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM inventory_item").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM media_work").fetchone()[0] >= 2
        assert conn.execute("SELECT COUNT(*) FROM media_asset").fetchone()[0] >= 1
        with pytest.raises(AppError) as raised:
            seed_demo(ctx, AttemptLimiter())
        assert raised.value.status == 409
        conn.close()

    client = Web(app)
    assert client.login(DEMO_USERNAME, DEMO_PASSWORD).status_code == 200
    home_page = client.get("/")
    assert home_page.status_code == 200
    assert b"Maison" in home_page.data or b"d\xc3\xa9mo" in home_page.data.lower() or b"demo" in home_page.data.lower()


def test_theme_cookie_and_settings(world):
    web, _app, _home, _clock = world
    page = web.get("/parametres")
    assert page.status_code == 200
    assert b'data-theme="light"' in page.data
    assert b"Apparence" in page.data
    posted = web.submit("/parametres/theme", {"theme": "dark"}, follow=True)
    assert posted.status_code == 200
    assert b'data-theme="dark"' in posted.data
    assert b"Th\xc3\xa8me enregistr" in posted.data or b"enregistr" in posted.data


def test_inventory_csv_export(world):
    web, _app, _home, _clock = world
    place = web.api("POST", "/api/inventory/places", {"name": "Cave"}).get_json()
    created = web.api("POST", "/api/inventory/items", {
        "name": "Velo ville",
        "category": "Sport",
        "place_id": place["id"],
        "purchase_price": "250,00",
        "purchase_currency": "CHF",
    })
    assert created.status_code == 201, created.get_json()
    csv_resp = web.api("GET", "/api/inventory/export.csv")
    assert csv_resp.status_code == 200
    body = csv_resp.data.decode("utf-8")
    assert "Velo ville" in body
    assert "25000" in body
    page = web.get("/inventaire/export.csv")
    assert page.status_code == 200
    assert b"name;category" in page.data


def test_e2e_parcours_transversal(world, tmp_path):
    """Parcours Accueil → organisation → finances → inventaire → média → backup."""
    web, app, home, clock = world
    people = web.api("GET", "/api/people").get_json()["items"]
    me = people[0]["id"]

    task = web.api("POST", "/api/tasks", {
        "title": "Preparer courses", "due_date": "2027-02-21", "assignee_id": me,
    })
    assert task.status_code == 201, task.get_json()

    event = web.api("POST", "/api/events", {
        "title": "Marche", "start_date": "2027-02-21", "all_day": True,
    })
    assert event.status_code == 201, event.get_json()

    accounts = web.api("GET", "/api/finance/accounts").get_json()["items"]
    chf = next(a for a in accounts if a["currency"] == "CHF")
    cats = web.api("GET", "/api/finance/categories?kind=expense").get_json()["items"]
    food = cats[0]
    expense = web.api("POST", "/api/finance/transactions", {
        "kind": "expense",
        "amount": "12,30",
        "currency": "CHF",
        "txn_date": "2027-02-20",
        "label": "Pain",
        "category_id": food["id"],
        "ledger_account_id": chf["id"],
        "payer_id": me,
        "split_method": "equal",
        "split_person_ids": [me],
    })
    assert expense.status_code == 201
    assert expense.get_json()["amount_minor"] == 1230

    place = web.api("POST", "/api/inventory/places", {"name": "Entree"}).get_json()
    item = web.api("POST", "/api/inventory/items", {
        "name": "Parapluie", "place_id": place["id"], "purchase_price": "19,90", "purchase_currency": "CHF",
    })
    assert item.status_code == 201, item.get_json()

    work = web.api("POST", "/api/media/works", {
        "kind": "book", "title": "Roman", "status": "in_progress",
    })
    assert work.status_code == 201

    today = web.api("GET", "/api/home")
    assert today.status_code == 200
    payload = today.get_json()
    assert isinstance(payload.get("tasks"), list)
    assert len(payload["tasks"]) >= 1

    search = web.api("GET", "/api/search?q=Parapluie")
    assert search.status_code == 200

    fin_csv = web.api("GET", "/api/finance/export.csv")
    assert fin_csv.status_code == 200
    assert b"Pain" in fin_csv.data

    inv_csv = web.api("GET", "/api/inventory/export.csv")
    assert inv_csv.status_code == 200
    assert b"Parapluie" in inv_csv.data

    conn = connect(home / "data" / "metadata.sqlite")
    ctx = Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"])
    archive = create_backup(ctx)
    conn.close()
    dest = tmp_path / "e2e-restore"
    restore_archive(archive, dest, clock)
    restored = sqlite3.connect(dest / "data" / "metadata.sqlite")
    assert restored.execute("SELECT COUNT(*) FROM task WHERE archived=0").fetchone()[0] >= 1
    assert restored.execute("SELECT amount_minor FROM finance_transaction WHERE label='Pain'").fetchone()[0] == 1230
    restored.close()
