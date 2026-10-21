"""UX V2.1 Sprint 2 : Aujourd'hui branché sur les vraies données, onboarding, « Terminer »."""

import re
from datetime import datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from tests.test_flows import HOST, ORIGIN, PASSWORD, Web


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def world(tmp_path, clock):
    app = create_app(home=tmp_path / "inst", clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    return web, app


def _add_member(web):
    web.get("/personnes/ajouter")
    web.submit("/personnes", {
        "display_name": "Léa", "relationship": "conjoint", "with_account": "oui",
        "username": "lea", "password": PASSWORD, "password_confirm": PASSWORD,
    })
    people = web.api("GET", "/api/people").get_json()["items"]
    return next(p for p in people if p["is_principal"]), next(p for p in people if p["display_name"] == "Léa")


def _expense(web, payer, amount, currency, label, visibility="household", date="2027-02-18"):
    accounts = web.api("GET", "/api/finance/accounts").get_json()["items"]
    account = next(a for a in accounts if a["currency"] == currency)
    cats = web.api("GET", "/api/finance/categories?kind=expense").get_json()["items"]
    food = next(c for c in cats if c["name"] == "Alimentation")
    created = web.api("POST", "/api/finance/transactions", {
        "kind": "expense", "amount": amount, "currency": currency, "txn_date": date, "label": label,
        "category_id": food["id"], "ledger_account_id": account["id"], "payer_id": payer["id"],
        "split_method": "equal", "split_person_ids": [payer["id"]], "visibility": visibility,
    })
    assert created.status_code == 201, created.get_json()
    return food


def test_empty_household_gets_guidance(world):
    web, _app = world
    page = web.get("/").data.decode()
    assert "Bonjour Roger" in page
    assert "Bien démarrer" in page and "1 étape sur 5" in page
    for href in ("/personnes/ajouter", "/finances/depense", "/calendrier/nouveau", "/inventaire/nouveau"):
        assert f'href="{href}"' in page
    assert "Rien de prévu dans les 14 prochains jours." in page
    assert "Mes tâches : rien en attente." in page
    assert "Aucune dépense ce mois-ci." in page
    assert "Ajouté récemment" not in page


def test_filled_household_shows_real_data(world):
    web, _app = world
    roger, lea = _add_member(web)
    web.api("POST", "/api/events", {"title": "Dentiste Léa", "start_date": "2027-02-23", "all_day": True})
    web.api("POST", "/api/events", {"title": "Vacances lointaines", "start_date": "2027-04-01", "all_day": True})
    web.api("POST", "/api/tasks", {"title": "Payer la crèche", "due_date": "2027-02-19", "assignee_id": roger["id"], "priority": "high"})
    web.api("POST", "/api/tasks", {"title": "Sortir le verre", "due_date": "2027-02-21"})
    web.api("POST", "/api/tasks", {"title": "Tâche de Léa", "due_date": "2027-02-21", "assignee_id": lea["id"]})
    food = _expense(web, roger, "120,50", "CHF", "Courses marché")
    _expense(web, roger, "30,00", "EUR", "Péage France")
    _expense(web, roger, "999,00", "CHF", "Mois dernier", date="2027-01-15")
    web.api("POST", "/api/finance/budgets", {
        "category_id": food["id"], "period": "month", "year": 2027, "month": 2, "amount": "200,00", "currency": "CHF",
    })

    page = web.get("/").data.decode()
    agenda = page[page.index('id="dash-agenda"'):page.index('id="dash-todo"')]
    assert "Dentiste Léa" in agenda and "Vacances lointaines" not in agenda
    todo = page[page.index('id="dash-todo"'):page.index('id="dash-finance"')]
    assert "Payer la crèche" in todo and "en retard" in todo and "Prioritaire" in todo
    assert "Sortir le verre" in todo and "Pour tout le foyer" in todo
    assert "Tâche de Léa" not in todo
    finance = page[page.index('id="dash-finance"'):page.index('id="dash-shortcuts"')]
    assert "120,50" in finance and "30,00" in finance and "999" not in finance
    assert "Dépenses du mois · CHF" in finance and "Dépenses du mois · EUR" in finance
    assert "Reste 79,50" in finance
    assert "Ajouté récemment" in page
    assert "2 tâches à faire, dont 1 en retard" in page
    assert "Bien démarrer" not in page or "étapes sur 5" in page


def test_complete_task_in_one_click_from_today(world):
    web, _app = world
    web.api("POST", "/api/tasks", {"title": "Arroser", "due_date": "2027-02-20"})
    page = web.get("/").data.decode()
    task_id = int(re.search(r'action="/organisation/(\d+)/terminer"', page).group(1))
    done = web.c.post(
        f"/organisation/{task_id}/terminer",
        data={"csrf_token": web.token, "next": "/"},
        headers={"Host": HOST, "Origin": ORIGIN},
    )
    assert done.status_code == 302 and done.headers["Location"].endswith("/")
    page = web.get("/").data.decode()
    assert "La tâche est marquée faite." in page
    assert "Arroser" not in page[page.index('id="dash-todo"'):page.index('id="dash-shortcuts"')]
    assert web.api("GET", f"/api/tasks/{task_id}").get_json()["status"] == "done"


def test_complete_task_requires_csrf(world):
    web, _app = world
    created = web.api("POST", "/api/tasks", {"title": "Protégée"}).get_json()
    refused = web.c.post(f"/organisation/{created['id']}/terminer", data={"next": "/"}, headers={"Host": HOST, "Origin": ORIGIN})
    assert refused.status_code in (400, 403)
    assert web.api("GET", f"/api/tasks/{created['id']}").get_json()["status"] == "open"


def test_complete_task_ignores_offsite_next(world):
    web, _app = world
    created = web.api("POST", "/api/tasks", {"title": "Redirection"}).get_json()
    web.get("/")
    done = web.c.post(
        f"/organisation/{created['id']}/terminer",
        data={"csrf_token": web.token, "next": "//evil.example/"},
        headers={"Host": HOST, "Origin": ORIGIN},
    )
    assert done.headers["Location"] == "/"


def test_onboarding_can_be_hidden_and_resumed(world):
    web, _app = world
    assert "Bien démarrer" in web.get("/").data.decode()
    web.submit("/accueil/demarrage", {"action": "masquer"})
    assert "Bien démarrer" not in web.get("/").data.decode()
    settings = web.get("/parametres").data.decode()
    assert "Réafficher le guide" in settings
    web.submit("/accueil/demarrage", {"action": "afficher", "from": "parametres"})
    assert "Bien démarrer" in web.get("/").data.decode()


def test_secondary_never_sees_private_amounts(world):
    web, app = world
    roger, _lea = _add_member(web)
    _expense(web, roger, "77,70", "CHF", "Cadeau secret", visibility="private")
    _expense(web, roger, "10,00", "CHF", "Pain")
    lea_web = Web(app)
    lea_web.login("lea")
    page = lea_web.get("/").data.decode()
    assert "Bonjour Léa" in page
    assert "77,70" not in page and "Cadeau secret" not in page
    assert "10,00" in page
    assert "Administration avancée" not in page
    assert 'href="/personnes/ajouter"' not in page
