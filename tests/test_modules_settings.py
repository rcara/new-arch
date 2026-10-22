"""D3 : activation / désactivation des modules par le compte principal (Paramètres)."""

import html
import re
from datetime import datetime, timezone

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect
from app.security import AttemptLimiter
from app.services.demo import DEMO_PASSWORD, DEMO_PASSWORD_SECONDARY, DEMO_USERNAME, seed_demo
from app.services.modules import LOCKED, NAV_ORDER, ROUTE_PREFIXES
from tests.test_flows import HOST, ORIGIN, Web

TOGGLEABLE = [key for key in NAV_ORDER if key not in LOCKED]

# Une page représentative et une route API par module basculable.
PAGES = {
    "finances": ["/finances", "/finances/depense", "/finances/export.csv"],
    "inventaire": ["/inventaire", "/inventaire/nouveau", "/maison"],
    "calendrier": ["/calendrier", "/calendrier/nouveau", "/agenda"],
    "organisation": ["/organisation", "/organisation/nouvelle", "/a-faire"],
    "coffre": ["/coffre"],
    "decisions": ["/decisions", "/decisions/nouvelle"],
    "mediatheque": ["/mediatheque", "/mediatheque/oeuvre/nouvelle"],
    "reperes": ["/reperes", "/reperes/nouveau"],
    "recherche": ["/recherche?q=demo"],
}
APIS = {
    "finances": "/api/finance/transactions",
    "inventaire": "/api/inventory/items",
    "calendrier": "/api/events",
    "organisation": "/api/tasks",
    "coffre": "/api/files",
    "decisions": "/api/decisions",
    "mediatheque": "/api/media/works",
    "reperes": "/api/milestones",
    "recherche": "/api/search?q=demo",
}
TABLES = (
    "task", "calendar_event", "finance_transaction", "finance_budget", "inventory_item", "inventory_place",
    "media_work", "media_list", "milestone", "decision", "stored_file", "object_link", "person",
)


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def demo(tmp_path, clock):
    home = tmp_path / "demo"
    app = create_app(home=home, clock=clock, testing=True)
    with app.app_context():
        conn = connect(home / "data" / "metadata.sqlite")
        seed_demo(Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"]), AttemptLimiter())
        conn.close()
    return app, home


def _web(app, username, password):
    web = Web(app)
    web.login(username, password)
    return web


@pytest.fixture
def alex(demo):
    return _web(demo[0], DEMO_USERNAME, DEMO_PASSWORD)


@pytest.fixture
def camille(demo):
    return _web(demo[0], "camille", DEMO_PASSWORD_SECONDARY)


def _set(web, *enabled, follow=True):
    web.get("/parametres")
    return web.submit("/parametres/modules", {"module": list(enabled)}, follow=follow)


def _without(*keys):
    return [key for key in TOGGLEABLE if key not in keys]


def _state(home, household_id=1):
    conn = connect(home / "data" / "metadata.sqlite")
    rows = conn.execute(
        "SELECT module_key, enabled FROM module_setting WHERE household_id=?", (household_id,),
    ).fetchall()
    conn.close()
    return {row["module_key"]: bool(row["enabled"]) for row in rows}


def _snapshot(home):
    conn = connect(home / "data" / "metadata.sqlite")
    data = {table: conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() for table in TABLES}
    conn.close()
    return {table: [tuple(row) for row in rows] for table, rows in data.items()}


def _hrefs(response):
    return [html.unescape(href) for href in re.findall(r'href="(/[^"]*)"', response.data.decode())]


def _module_of(href):
    path = href.split("?")[0].split("#")[0]
    for prefix, key in ROUTE_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return key
    return None


def test_settings_form_lists_toggles_and_locked_modules(alex):
    page = alex.get("/parametres")
    text = page.data.decode()
    assert 'action="/parametres/modules"' in text
    for key in TOGGLEABLE:
        assert f'name="module" value="{key}" checked' in text
    for key in LOCKED:
        assert f'name="module" value="{key}"' not in text
    assert "toujours actif" in html.unescape(text)


def test_principal_toggles_module_off_and_on(alex, demo):
    _app, home = demo
    response = _set(alex, *_without("finances"))
    assert response.status_code == 200
    assert "Modules mis à jour" in html.unescape(response.data.decode())
    assert _state(home)["finances"] is False
    assert all(_state(home)[key] for key in _without("finances"))
    assert alex.get("/finances").status_code == 404
    assert 'value="finances" checked' not in alex.get("/parametres").data.decode()

    _set(alex, *TOGGLEABLE)
    assert _state(home)["finances"] is True
    assert alex.get("/finances").status_code == 200


def test_locked_modules_cannot_be_disabled(alex, demo):
    _app, home = demo
    _set(alex)
    state = _state(home)
    assert all(state[key] for key in LOCKED)
    assert not any(state[key] for key in TOGGLEABLE)
    for url in ("/", "/parametres", "/foyer", "/acces", "/profil"):
        assert alex.get(url).status_code == 200, url
    # Forcer une clé verrouillée à 0 en base ne la désactive pas pour autant.
    conn = connect(home / "data" / "metadata.sqlite")
    conn.execute("UPDATE module_setting SET enabled=0 WHERE module_key='parametres'")
    conn.commit()
    conn.close()
    assert alex.get("/parametres").status_code == 200


def test_secondary_member_gets_403_and_nothing_changes(camille, demo):
    _app, home = demo
    before = _state(home)
    page = camille.get("/parametres")
    assert page.status_code == 200
    assert 'action="/parametres/modules"' not in page.data.decode()
    assert "Seul le compte principal" in page.data.decode()
    response = camille.submit("/parametres/modules", {"module": []}, follow=False)
    assert response.status_code == 403
    assert _state(home) == before


def test_post_requires_csrf_and_known_keys(alex, demo):
    _app, home = demo
    before = _state(home)
    alex.get("/parametres")
    response = alex.c.post(
        "/parametres/modules", data={"module": []}, headers={"Host": HOST, "Origin": ORIGIN},
    )
    assert response.status_code == 400
    assert _state(home) == before
    assert _set(alex, "finances", "inconnu", follow=False).status_code == 400
    assert _state(home) == before


@pytest.mark.parametrize("key", TOGGLEABLE)
def test_disabled_module_hidden_and_blocked_everywhere(alex, camille, key):
    _set(alex, *_without(key))
    for web in (alex, camille):
        for start in ("/", "/parametres", "/profil") + (("/foyer",) if web is alex else ()):
            page = web.get(start)
            assert page.status_code == 200
            leaked = [href for href in _hrefs(page) if _module_of(href) == key]
            assert not leaked, (key, start, leaked)
        for url in PAGES[key]:
            assert web.get(url).status_code == 404, (key, url)
        api = web.api("GET", APIS[key])
        assert api.status_code == 404, (key, APIS[key])
        assert api.get_json()["error"]["code"] == "not_found"
    if key != "recherche":
        results = alex.get("/recherche?q=de")
        assert results.status_code == 200
        assert not [href for href in _hrefs(results) if _module_of(href) == key]
    else:
        assert 'role="search"' not in alex.get("/").data.decode()


def test_today_cards_follow_modules(alex):
    today = html.unescape(alex.get("/").data.decode())
    assert "dash-todo" in today and "dash-agenda" in today
    _set(alex, *_without("organisation", "finances", "calendrier", "reperes", "inventaire", "mediatheque"))
    today = html.unescape(alex.get("/").data.decode())
    for card in ("dash-todo", "dash-agenda", "dash-warranties", "dash-media"):
        assert card not in today, card
    assert "Les repères ne vous sont pas accordés" not in today
    shortcuts = today[today.index('id="dash-shortcuts"'):]
    shortcuts = shortcuts[:shortcuts.index("</section>")]
    assert "Dépense" not in shortcuts and "Tâche" not in shortcuts and "Événement" not in shortcuts


def test_data_preserved_after_off_and_on(alex, demo):
    _app, home = demo
    alex.api("POST", "/api/events", {"title": "Dentiste", "start_date": "2027-02-25", "all_day": True})
    before = _snapshot(home)
    assert before["task"] and before["finance_transaction"] and before["inventory_item"] and before["media_work"]
    tasks_before = alex.api("GET", "/api/tasks").get_json()

    _set(alex)
    assert _snapshot(home) == before
    assert alex.api("GET", "/api/tasks").status_code == 404

    _set(alex, *TOGGLEABLE)
    assert _snapshot(home) == before
    assert alex.api("GET", "/api/tasks").get_json() == tasks_before
    assert "Dentiste" in alex.get("/calendrier").data.decode()
    assert "Sortir les poubelles" in html.unescape(alex.get("/organisation").data.decode())

