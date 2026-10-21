"""Multi-foyer : migration 007, isolation, bascule et sidebar CSS-only."""

from datetime import datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect, init_db
from tests.test_flows import PASSWORD, Web


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


def test_migration_reaches_version_7(tmp_path):
    db_path = tmp_path / "data" / "metadata.sqlite"
    db_path.parent.mkdir(parents=True)
    init_db(db_path)
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "household_membership" in tables
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(session)")}
    assert {"login_person_id", "person_id", "csrf_token"} <= cols
    # Plus de contrainte mono-foyer
    t = "2027-02-20T09:00:00Z"
    conn.execute("INSERT INTO household(id, name, timezone, created_at) VALUES(1,'A','Europe/Zurich',?)", (t,))
    conn.execute("INSERT INTO household(id, name, timezone, created_at) VALUES(2,'B','Europe/Zurich',?)", (t,))
    assert conn.execute("SELECT COUNT(*) FROM household").fetchone()[0] == 2
    conn.close()


def test_create_switch_and_isolate_tasks(world):
    web, app, home, _clock = world
    # Tâche dans foyer 1
    web.get("/organisation/nouvelle")
    created = web.submit("/organisation", {
        "title": "Secret foyer 1",
        "due_date": "2027-02-25",
        "priority": "normal",
        "notes": "",
    })
    assert created.status_code == 200

    # Créer foyer 2
    resp = web.submit("/foyers/creer", {
        "household_name": "Chalet",
        "timezone": "Europe/Zurich",
        "display_name": "Roger chalet",
    })
    assert resp.status_code == 200
    assert b"Chalet" in resp.data or b"Nouveau foyer" in resp.data or b"foyer" in resp.data.lower()

    # Accueil du foyer 2 : pas la tâche du foyer 1
    today = web.get("/")
    assert today.status_code == 200
    assert b"Secret foyer 1" not in today.data
    assert b"sidebar" in today.data or b'class="sidebar"' in today.data
    assert b'id="navigation"' in today.data
    assert b"Nouveau foyer" in today.data
    assert b'class="foyer-item foyer-item--active" aria-current="true">Chalet<' in today.data

    # Liste API memberships
    listed = web.api("GET", "/api/households")
    assert listed.status_code == 200
    items = listed.get_json()["items"]
    assert len(items) == 2
    names = {item["household_name"] for item in items}
    assert names == {"Foyer", "Chalet"}
    active = [item for item in items if item["active"]]
    assert len(active) == 1
    assert active[0]["household_name"] == "Chalet"

    # Tâche dans foyer 2
    web.get("/organisation/nouvelle")
    web.submit("/organisation", {
        "title": "Secret foyer 2",
        "due_date": "2027-02-26",
        "priority": "normal",
        "notes": "",
    })

    # Revenir au foyer 1
    foyer_id = next(item["household_id"] for item in items if item["household_name"] == "Foyer")
    switched = web.submit("/foyers/basculer", {"household_id": str(foyer_id), "next": "/organisation"})
    assert switched.status_code == 200
    tasks = web.get("/organisation")
    assert b"Secret foyer 1" in tasks.data
    assert b"Secret foyer 2" not in tasks.data

    # Isolation SQL directe
    conn = connect(home / "data" / "metadata.sqlite")
    counts = dict(conn.execute(
        "SELECT household_id, COUNT(*) FROM task WHERE archived=0 GROUP BY household_id"
    ).fetchall())
    assert counts.get(1) == 1
    assert counts.get(2) == 1
    conn.close()


def test_sidebar_css_has_drawer_without_script(world):
    web, _app, _home, _clock = world
    page = web.get("/")
    assert page.status_code == 200
    assert b"<script" not in page.data.lower()
    assert b'href="#navigation"' in page.data
    assert b"drawer-backdrop" in page.data
    css = web.c.get("/static/app.css", headers={"Host": "127.0.0.1:8765"})
    body = css.data.decode("utf-8")
    assert ".sidebar:target" in body
    assert "--sidebar-w" in body
