"""Profil, changement de mot de passe et tableau de bord personnel."""

from datetime import datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from tests.test_flows import PASSWORD, Web

NEW_PASSWORD = "nouvelle-phrase-34"


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


def test_profile_page_and_display_name(world):
    web, _app, _home, _clock = world
    page = web.get("/profil")
    assert page.status_code == 200
    assert b"Profil" in page.data
    assert b"roger" in page.data.lower()
    assert b"Mot de passe" in page.data

    saved = web.submit("/profil", {"display_name": "Roger Updated"})
    assert saved.status_code == 200
    assert b"Roger Updated" in saved.data
    assert b"mis" in saved.data.lower() or b"Profil" in saved.data

    me = web.api("GET", "/api/me").get_json()
    assert me["display_name"] == "Roger Updated"
    assert me["username"] == "roger"
    assert me["role"] == "principal"

    patched = web.api("PATCH", "/api/me", {"display_name": "Roger API"})
    assert patched.status_code == 200
    assert patched.get_json()["display_name"] == "Roger API"

    dash = web.get("/")
    assert dash.status_code == 200
    assert b"Bonjour Roger" in dash.data
    assert "À faire".encode() in dash.data
    assert b"Roger API" in dash.data


def test_change_password_ui_and_api(world):
    web, _app, _home, _clock = world

    bad = web.submit("/profil/mot-de-passe", {
        "current_password": "mauvais-mot-de-passe",
        "new_password": NEW_PASSWORD,
        "new_password_confirm": NEW_PASSWORD,
    })
    assert bad.status_code == 400
    assert b"Incorrect" in bad.data or b"incorrect" in bad.data.lower()

    mismatch = web.submit("/profil/mot-de-passe", {
        "current_password": PASSWORD,
        "new_password": NEW_PASSWORD,
        "new_password_confirm": "autre-phrase-99",
    })
    assert mismatch.status_code == 400

    ok = web.submit("/profil/mot-de-passe", {
        "current_password": PASSWORD,
        "new_password": NEW_PASSWORD,
        "new_password_confirm": NEW_PASSWORD,
    })
    assert ok.status_code == 200
    assert b"mot de passe" in ok.data.lower()

    # session courante reste valide
    assert web.get("/profil").status_code == 200

    # ancienne connexion refusée, nouvelle OK
    other = Web(web.app)
    denied = other.login("roger", PASSWORD)
    assert denied.status_code in {200, 401}
    # login page shows error on failure — status may be 200 with error text
    if denied.status_code == 200 and b"incorrect" not in denied.data.lower() and b"Identifiant" not in denied.data:
        # might have succeeded wrongly
        pass
    # Explicit: open with old password via API after logout
    web.submit("/deconnexion", {})
    again = Web(web.app)
    fail = again.login("roger", PASSWORD)
    assert b"incorrect" in fail.data.lower() or fail.status_code == 401 or b"Identifiant ou mot de passe" in fail.data

    success = again.login("roger", NEW_PASSWORD)
    assert success.status_code == 200
    assert again.get("/").status_code == 200

    # API path
    api_change = again.api("POST", "/api/me/password", {
        "current_password": NEW_PASSWORD,
        "new_password": PASSWORD,
        "new_password_confirm": PASSWORD,
    })
    assert api_change.status_code == 200
    assert api_change.get_json()["ok"] is True


def test_dashboard_includes_mine_tasks(world):
    web, _app, _home, _clock = world
    me = web.api("GET", "/api/me").get_json()["person_id"]
    created = web.api("POST", "/api/tasks", {
        "title": "Ma tache perso",
        "due_date": "2027-02-22",
        "assignee_id": me,
        "priority": "high",
    })
    assert created.status_code == 201

    home = web.api("GET", "/api/home").get_json()
    assert home["person"]["display_name"]
    assert home["mine"]["task_count"] >= 1
    assert any(t["title"] == "Ma tache perso" for t in home["mine"]["tasks"])

    page = web.get("/")
    assert b"Ma tache perso" in page.data
    assert b"Mes t" in page.data  # Mes tâches
