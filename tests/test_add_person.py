"""Régression : ajout de membre (GET formulaire + POST) — évite le 405 sur /personnes/ajouter."""

import re
from datetime import datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect
from tests.test_flows import PASSWORD, Web


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def world(tmp_path, clock):
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap(name="Roger", username="roger")
    return web, app, home


def _person_form_action(html: str) -> str:
    """Action du formulaire d'ajout, celui qui contient relationship."""
    rel = html.find('name="relationship"')
    assert rel != -1, "formulaire d'ajout de personne introuvable"
    start = html.rfind("<form", 0, rel)
    assert start != -1
    tag_end = html.find(">", start)
    attrs = html[start:tag_end]
    action = re.search(r'\baction="([^"]+)"', attrs, re.I)
    assert action, "le formulaire d'ajout doit déclarer action= (sinon POST → 405 sur /personnes/ajouter)"
    return action.group(1)


def test_get_add_form_is_200_with_csrf_and_action(world):
    web, _app, _home = world
    response = web.get("/personnes/ajouter")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Ajouter quelqu'un" in html
    assert "Créer un compte maintenant" in html
    assert 'name="csrf_token"' in html
    assert "Méthode refusée" not in html
    assert "Action non disponible" not in html
    action = _person_form_action(html)
    assert action in {"/personnes", "/personnes/ajouter"}


def test_post_without_account_via_form_url(world):
    """Le navigateur poste sur l'URL du formulaire si action absente ; avec action, sur celle-ci."""
    web, _app, _home = world
    form = web.get("/personnes/ajouter")
    assert form.status_code == 200
    action = _person_form_action(form.data.decode())

    created = web.submit(action, {
        "display_name": "Caroline",
        "relationship": "Epouse",
    }, follow=False)
    assert created.status_code in (302, 303), created.data.decode()[:500]
    assert created.status_code != 405

    people = web.api("GET", "/api/people").get_json()["items"]
    caroline = next(p for p in people if p["display_name"] == "Caroline")
    assert caroline["relationship"] == "Epouse"
    assert caroline["has_account"] is False
    assert caroline["is_principal"] is False


def test_post_with_account_now(world):
    web, app, _home = world
    form = web.get("/personnes/ajouter")
    action = _person_form_action(form.data.decode())

    created = web.submit(action, {
        "display_name": "Léa",
        "relationship": "conjoint",
        "with_account": "oui",
        "username": "lea",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    }, follow=False)
    assert created.status_code in (302, 303)
    assert created.status_code != 405

    people = web.api("GET", "/api/people").get_json()["items"]
    lea = next(p for p in people if p["display_name"] == "Léa")
    assert lea["has_account"] is True

    other = Web(app)
    assert other.login("lea").status_code == 200
    me = other.api("GET", "/api/me").get_json()
    assert me["display_name"] == "Léa"


def test_post_directly_to_ajouter_does_not_405(world):
    """Filet : POST /personnes/ajouter ne doit plus renvoyer 405 (bug prod)."""
    web, _app, _home = world
    web.get("/personnes/ajouter")
    response = web.submit("/personnes/ajouter", {
        "display_name": "Sam",
        "relationship": "ami",
    }, follow=False)
    assert response.status_code != 405
    assert response.status_code in (302, 303)
    names = {p["display_name"] for p in web.api("GET", "/api/people").get_json()["items"]}
    assert "Sam" in names


def test_secondary_cannot_add_person(world):
    web, app, _home = world
    web.get("/personnes/ajouter")
    web.submit("/personnes", {
        "display_name": "Sam",
        "relationship": "conjoint",
        "with_account": "oui",
        "username": "sam",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    })
    sam = Web(app)
    assert sam.login("sam").status_code == 200
    assert sam.get("/personnes/ajouter").status_code == 403
    sam.get("/")
    refused = sam.submit("/personnes", {"display_name": "Intrus", "relationship": ""}, follow=False)
    assert refused.status_code == 403
    names = {p["display_name"] for p in web.api("GET", "/api/people").get_json()["items"]}
    assert "Intrus" not in names


def test_ajout_membre_dans_le_foyer_unique(world):
    """Un membre ajouté reste dans l'unique foyer. Créer ou basculer un foyer n'est plus possible."""
    web, _app, home = world
    refused = web.submit("/foyers/creer", {
        "household_name": "Foyer Cairo",
        "timezone": "Europe/Zurich",
        "display_name": "Roger Cairo",
    }, follow=False)
    assert refused.status_code == 404
    assert web.api("GET", "/api/households").status_code == 404

    form = web.get("/personnes/ajouter")
    assert form.status_code == 200
    action = _person_form_action(form.data.decode())
    created = web.submit(action, {"display_name": "Caroline", "relationship": "Epouse"}, follow=False)
    assert created.status_code in (302, 303)

    names = {p["display_name"] for p in web.api("GET", "/api/people").get_json()["items"]}
    assert "Caroline" in names

    conn = connect(home / "data" / "metadata.sqlite")
    row = conn.execute(
        "SELECT household_id FROM person WHERE display_name=?",
        ("Caroline",),
    ).fetchone()
    households = conn.execute("SELECT COUNT(*) FROM household").fetchone()[0]
    conn.close()
    assert row["household_id"] == 1
    assert households == 1
