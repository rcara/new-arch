"""Socle New Arch V2 : migration 003, tâches, événements, liens, recherche."""

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect, init_db
from app.services.tasks import next_due_date
from tests.test_flows import HOST, ORIGIN, PASSWORD, Web

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "migrations" / "001_schema.sql"
M002 = ROOT / "migrations" / "002_concurrency.sql"
M003 = ROOT / "migrations" / "003_v2_foundation.sql"


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


def test_migration_002_to_003_on_copied_v1(tmp_path):
    """DB V1 (user_version=2) migre en place vers 3 sans perte."""
    db_path = tmp_path / "metadata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(M002.read_text(encoding="utf-8"))
    t = "2027-02-20T09:00:00Z"
    conn.execute("INSERT INTO household VALUES(1,'Démo','Europe/Berlin',?)", (t,))
    conn.execute(
        "INSERT INTO person(id,display_name,is_principal,created_at) VALUES(1,'Roger',1,?)", (t,)
    )
    conn.execute(
        "INSERT INTO account(person_id,username,password_hash,created_at) VALUES(1,'roger','x',?)", (t,)
    )
    conn.execute(
        "INSERT INTO milestone(id,name,category,holder_id,created_at,updated_at) VALUES(1,'Passeport','Identité',1,?,?)",
        (t, t),
    )
    conn.commit()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    conn.close()

    init_db(db_path)
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "task", "calendar_event", "object_link", "module_setting",
        "finance_transaction", "inventory_item", "media_work",
    } <= tables
    assert conn.execute("SELECT name FROM household WHERE id=1").fetchone()[0] == "Démo"
    assert conn.execute("SELECT COUNT(*) FROM milestone").fetchone()[0] == 1
    enabled = {
        row["module_key"]: row["enabled"]
        for row in conn.execute("SELECT module_key, enabled FROM module_setting")
    }
    assert enabled["organisation"] == 1
    assert enabled["finances"] == 1
    assert enabled["inventaire"] == 1
    assert enabled["mediatheque"] == 1
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_schema_001_hash_inchange():
    data = SCHEMA.read_bytes()
    assert hashlib.sha256(data).hexdigest() == "ab22368db6158bd48fd6a424495a5cd6f590cc2a5ee83fd7a8b5e5fb58d5e219"


def test_next_due_date_recurrence():
    assert next_due_date("2027-02-20", "weekly") == "2027-02-27"
    assert next_due_date("2027-01-31", "monthly") == "2027-02-28"
    assert next_due_date("2024-02-29", "yearly") == "2025-02-28"
    assert next_due_date("2027-02-20", "none") is None


def test_task_recurrence_and_home(world):
    web, app, home, clock = world
    created = web.api("POST", "/api/tasks", {
        "title": "Courses hebdo",
        "priority": "high",
        "due_date": "2027-02-22",
        "recurrence": "weekly",
    })
    assert created.status_code == 201
    task = created.get_json()
    assert task["title"] == "Courses hebdo"
    assert task["public_id"]

    done = web.api("PATCH", f"/api/tasks/{task['id']}", {"status": "done"})
    assert done.status_code == 200
    assert done.get_json()["status"] == "done"

    listed = web.api("GET", "/api/tasks?status=open").get_json()
    assert any(item["title"] == "Courses hebdo" and item["due_date"] == "2027-03-01" for item in listed["items"])

    home_payload = web.api("GET", "/api/home").get_json()
    assert home_payload["household_name"] == "Foyer"
    assert "tasks" in home_payload
    assert "events" in home_payload
    page = web.get("/")
    assert page.status_code == 200
    assert b"Aujourd" in page.data
    assert b"passeport.pdf" not in page.data


def test_event_and_search(world):
    web, app, home, clock = world
    created = web.api("POST", "/api/events", {
        "title": "Réunion école",
        "start_date": "2027-03-01",
        "all_day": True,
        "timezone": "Europe/Zurich",
    })
    assert created.status_code == 201
    event = created.get_json()
    assert event["start_date"] == "2027-03-01"

    home_payload = web.api("GET", "/api/home").get_json()
    assert any(item["title"] == "Réunion école" for item in home_payload["events"])

    found = web.api("GET", "/api/search?q=Réunion").get_json()
    assert any(item["type"] == "calendar_event" and item["title"] == "Réunion école" for item in found["items"])


def test_links_acl_and_search_privacy(world):
    web, app, home, clock = world
    web.submit("/personnes", {
        "display_name": "Léa",
        "relationship": "conjoint",
        "with_account": "oui",
        "username": "lea",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    })
    web.submit("/reperes", {
        "name": "Assurance",
        "category": "Argent et assurances",
        "holder_id": "1",
        "responsible_id": "",
        "location": "",
        "amount": "",
        "due_date": "2027-03-15",
        "notice_days": "0",
        "note": "",
    })
    decision = web.api("POST", "/api/decisions", {
        "milestone_id": 1,
        "choice": "Changer de contrat secret",
        "options": ["Changer de contrat secret", "Ne rien faire"],
        "expected": "Économiser",
        "reconsider_if": "Hausse",
    })
    assert decision.status_code == 201
    decision_id = decision.get_json()["id"]

    task = web.api("POST", "/api/tasks", {"title": "Relancer assureur", "due_date": "2027-02-25"}).get_json()
    link = web.api("POST", "/api/links", {
        "source_type": "task",
        "source_id": task["id"],
        "target_type": "milestone",
        "target_id": 1,
        "relation_type": "relates_to",
    })
    assert link.status_code == 201

    # Second compte : voit les tâches, pas la décision sans droit
    web.submit("/deconnexion", {}, follow=False)
    web.login("lea")

    search = web.api("GET", "/api/search?q=contrat").get_json()
    assert all(item["type"] != "decision" for item in search["items"])

    denied = web.api("POST", "/api/links", {
        "source_type": "task",
        "source_id": task["id"],
        "target_type": "decision",
        "target_id": decision_id,
        "relation_type": "concerns",
    })
    assert denied.status_code == 404

    modules = web.api("GET", "/api/modules").get_json()
    keys = {item["key"]: item["enabled"] for item in modules["items"]}
    assert keys["finances"] is True
    assert keys["organisation"] is True
