"""Foyer unique : migration 007 conservée, création et bascule retirées, sidebar sans script."""

from datetime import datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect, init_db
from tests.test_first_party_js import assert_first_party_scripts
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
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 7
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


def test_pas_de_creation_ni_de_bascule_de_foyer(world):
    web, _app, home, _clock = world
    page = web.get("/").data.decode()
    assert "Nouveau foyer" not in page
    assert "Créer et ouvrir" not in page
    assert "Changer de foyer" not in page
    assert 'class="foyer-name"><span class="sr-only">Foyer actif : </span>Foyer</p>' in page

    refused = web.submit("/foyers/creer", {
        "household_name": "Chalet",
        "timezone": "Europe/Zurich",
        "display_name": "Roger chalet",
    }, follow=False)
    assert refused.status_code == 404
    assert web.submit("/foyers/basculer", {"household_id": "1"}, follow=False).status_code == 404
    assert web.api("GET", "/api/households").status_code == 404
    assert web.api("POST", "/api/households", {
        "household_name": "Chalet", "timezone": "Europe/Zurich", "display_name": "Roger",
    }).status_code == 404
    assert web.api("POST", "/api/households/switch", {"household_id": 1}).status_code == 404

    conn = connect(home / "data" / "metadata.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM household").fetchone()[0] == 1
    conn.close()


def test_sidebar_css_has_drawer_without_script(world):
    web, _app, _home, _clock = world
    page = web.get("/")
    assert page.status_code == 200
    assert_first_party_scripts(page.data)
    assert b'href="#navigation"' in page.data
    assert b"drawer-backdrop" in page.data
    css = web.c.get("/static/app.css", headers={"Host": "127.0.0.1:8765"})
    body = css.data.decode("utf-8")
    assert ".sidebar:target" in body
    assert "--sidebar-w" in body
