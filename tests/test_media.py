"""Étape E — médiathèque : catalogue ≠ fichiers ; décisions V1 préservées."""

import io
from datetime import datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect, init_db
from tests.test_flows import PASSWORD, Web

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


def test_migration_mediatheque(tmp_path):
    db_path = tmp_path / "metadata.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"media_work", "media_progress", "media_asset", "media_list"} <= tables
    conn.close()


def test_book_progress_and_wishlist(world):
    web, app, home, clock = world
    created = web.api("POST", "/api/media/works", {
        "kind": "book",
        "title": "Le Petit Prince",
        "creator": "Antoine de Saint-Exupéry",
        "year": 1943,
        "status": "wishlist",
        "visibility": "household",
    })
    assert created.status_code == 201, created.get_json()
    work = created.get_json()
    assert work["kind"] == "book"
    assert work["my_status"] == "wishlist"

    updated = web.api("PUT", f"/api/media/works/{work['id']}/progress", {
        "status": "in_progress",
        "progress_label": "page 42",
        "progress_percent": 20,
        "rating": 5,
    })
    assert updated.status_code == 200
    body = updated.get_json()
    assert body["my_status"] == "in_progress"
    assert body["my_progress"] == "page 42"
    assert body["my_percent"] == 20

    dash = web.api("GET", "/api/media/dashboard").get_json()
    assert any(item["title"] == "Le Petit Prince" for item in dash["in_progress"])

    page = web.get("/mediatheque")
    assert page.status_code == 200
    assert b"Le Petit Prince" in page.data
    assert b"Catalogue culturel" in page.data or b"catalogue" in page.data.lower()


def test_asset_not_confused_with_work_and_privacy(world):
    web, app, home, clock = world
    work = web.api("POST", "/api/media/works", {
        "kind": "music",
        "title": "Album démo",
        "status": "favorite",
    }).get_json()

    # upload photo linked optionally to work — still a separate asset
    response = web.c.open(
        "/api/media/assets",
        method="POST",
        data={
            "csrf_token": web.token,
            "title": "Pochette",
            "collection": "Covers",
            "visibility": "private",
            "work_id": str(work["id"]),
            "file": (io.BytesIO(JPEG), "pochette.jpg"),
        },
        headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "X-CSRF-Token": web.token},
        content_type="multipart/form-data",
    )
    web.token = response.headers.get("X-CSRF-Token") or web.token
    assert response.status_code == 201, response.get_json()
    asset = response.get_json()
    assert asset["asset_kind"] == "photo"
    assert asset["work_id"] == work["id"]
    assert "storage_key" not in asset

    content = web.api("GET", f"/api/media/assets/{asset['id']}/content")
    assert content.status_code == 200
    assert content.data.startswith(b"\xff\xd8\xff")

    # second account cannot see private asset
    web.submit("/personnes", {
        "display_name": "Sam",
        "relationship": "coloc",
        "with_account": "oui",
        "username": "sam",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    })
    web.submit("/deconnexion", {}, follow=False)
    web.login("sam")
    listed = web.api("GET", "/api/media/assets").get_json()["items"]
    assert all(item["id"] != asset["id"] for item in listed)
    assert web.api("GET", f"/api/media/assets/{asset['id']}/content").status_code == 404


def test_decision_seal_still_works_and_link_to_work(world):
    """Invariant V1 scellement préservé + lien œuvre ↔ décision."""
    web, app, home, clock = world
    people = web.api("GET", "/api/people").get_json()["items"]
    milestone = web.api("POST", "/api/milestones", {
        "name": "Choix de série",
        "category": "Loisirs" if False else "Identité",
        "holder_id": people[0]["id"],
    })
    # category must be valid V1
    if milestone.status_code != 201:
        milestone = web.api("POST", "/api/milestones", {
            "name": "Choix de série",
            "category": "Identité",
            "holder_id": people[0]["id"],
        })
    assert milestone.status_code == 201
    mid = milestone.get_json()["id"]

    draft = web.api("POST", "/api/decisions", {
        "milestone_id": mid,
        "choice": "Regarder Severance",
        "options": ["Regarder Severance", "Ne rien faire"],
        "expected": "Finir la saison",
        "reconsider_if": "Trop sombre",
    })
    assert draft.status_code == 201
    did = draft.get_json()["id"]
    sealed = web.api("POST", f"/api/decisions/{did}/seal", {
        "confirm": True,
        "draft_version": draft.get_json()["draft_version"],
    })
    assert sealed.status_code == 200
    assert sealed.get_json()["sealed_at"]
    refused = web.api("PATCH", f"/api/decisions/{did}", {
        "choice": "Autre",
        "draft_version": sealed.get_json()["draft_version"],
    })
    assert refused.status_code == 409

    work = web.api("POST", "/api/media/works", {
        "kind": "series",
        "title": "Severance",
        "status": "in_progress",
    }).get_json()
    link = web.api("POST", "/api/links", {
        "source_type": "media_work",
        "source_id": work["id"],
        "target_type": "decision",
        "target_id": did,
        "relation_type": "about_work",
    })
    assert link.status_code == 201
