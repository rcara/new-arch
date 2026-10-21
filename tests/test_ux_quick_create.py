"""UX V2.1 Sprint 3 : création rapide (+ Ajouter, panneaux :target, retour à l'origine, contexte)."""

import re
from datetime import datetime, timezone

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect
from app.security import AttemptLimiter
from app.services.demo import DEMO_PASSWORD, DEMO_PASSWORD_SECONDARY, DEMO_USERNAME, seed_demo
from tests.test_flows import Web


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def demo_app(tmp_path, clock):
    home = tmp_path / "demo"
    app = create_app(home=home, clock=clock, testing=True)
    with app.app_context():
        conn = connect(home / "data" / "metadata.sqlite")
        seed_demo(Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"]), AttemptLimiter())
        conn.close()
    return app


def _web(app, username, password):
    web = Web(app)
    web.login(username, password)
    return web


@pytest.fixture
def principal(demo_app):
    return _web(demo_app, DEMO_USERNAME, DEMO_PASSWORD)


@pytest.fixture
def secondary(demo_app):
    return _web(demo_app, "camille", DEMO_PASSWORD_SECONDARY)


def _panel(page, panel_id):
    text = page.data.decode()
    start = text.index(f'id="{panel_id}"')
    return text[start:text.index("</aside>", start)]


def _tasks(web):
    return web.api("GET", "/api/tasks?status=open").get_json()["items"]


def _me(web):
    return next(p for p in web.api("GET", "/api/people").get_json()["items"] if p["is_principal"])


def test_create_menu_opens_quick_panels(principal):
    page = principal.get("/finances")
    text = page.data.decode()
    menu = text[text.index('class="menu create-menu"'):text.index("</details>", text.index('class="menu create-menu"'))]
    assert 'href="#ajout-tache"' in menu and 'href="#ajout-evenement"' in menu
    assert 'href="/finances/depense?next=/finances"' in menu
    task = _panel(page, "ajout-tache")
    assert 'action="/organisation"' in task and 'name="next" value="/finances"' in task
    assert 'name="csrf_token"' in task and "required" in task
    event = _panel(page, "ajout-evenement")
    assert 'action="/calendrier"' in event and 'value="2027-02-20"' in event
    assert "<script" not in text


def test_quick_task_returns_to_origin_and_assigns_me(principal):
    principal.get("/inventaire")
    response = principal.submit("/organisation", {
        "title": "Rappeler le plombier", "due_date": "2027-02-25", "for_me": "1",
        "priority": "normal", "recurrence": "none", "next": "/inventaire",
    }, follow=False)
    assert response.status_code == 303 or response.status_code == 302
    assert response.headers["Location"].endswith("/inventaire")
    task = next(t for t in _tasks(principal) if t["title"] == "Rappeler le plombier")
    assert task["assignee_id"] == _me(principal)["id"]


def test_quick_task_without_for_me_stays_shared(principal):
    principal.get("/")
    principal.submit("/organisation", {"title": "Tri du grenier", "priority": "normal", "recurrence": "none", "next": "/"})
    task = next(t for t in _tasks(principal) if t["title"] == "Tri du grenier")
    assert task["assignee_id"] is None


def test_quick_event_is_all_day_full_form_respects_checkbox(principal):
    principal.get("/")
    response = principal.submit("/calendrier", {"title": "Fête d'école", "start_date": "2027-03-04", "next": "/"}, follow=False)
    assert response.headers["Location"].endswith("/")
    principal.get("/calendrier/nouveau")
    principal.submit("/calendrier", {
        "title": "Réunion syndic", "start_date": "2027-03-05", "all_day_present": "1",
        "recurrence": "none", "timezone": "Europe/Zurich",
    })
    events = principal.api("GET", "/api/events").get_json()["items"]
    by_title = {e["title"]: e for e in events}
    assert by_title["Fête d'école"]["all_day"] in (1, True)
    assert by_title["Réunion syndic"]["all_day"] in (0, False)


def test_expense_without_account_uses_currency_account(principal):
    page = principal.get("/finances/depense").data.decode()
    assert 'value="2027-02-20"' in page
    assert "Plus d'options" in page
    me = _me(principal)
    data = {
        "label": "Péage A40", "amount": "12,40", "currency": "EUR", "txn_date": "2027-02-20",
        "payer_id": str(me["id"]), "split_method": "equal", "split_person_ids": str(me["id"]),
        "visibility": "household", "ledger_account_id": "",
    }
    refused = principal.submit("/finances/depense", data)
    assert refused.status_code == 400
    assert "Catégorie requise." in refused.data.decode() and "vérifiez les champs signalés" in refused.data.decode()
    cats = principal.api("GET", "/api/finance/categories?kind=expense").get_json()["items"]
    data["category_id"] = str(cats[0]["id"])
    response = principal.submit("/finances/depense", data, follow=False)
    assert response.status_code in (302, 303), response.data[:400]
    txns = principal.api("GET", "/api/finance/transactions").get_json()["items"]
    txn = next(t for t in txns if t["label"] == "Péage A40")
    accounts = {a["id"]: a for a in principal.api("GET", "/api/finance/accounts").get_json()["items"]}
    assert txn["currency"] == "EUR" and txn["amount_minor"] == 1240
    assert accounts[txn["ledger_account_id"]]["currency"] == "EUR"


def test_next_cannot_leave_the_site(principal):
    principal.get("/")
    for evil in ("//evil.example", "https://evil.example/x", "javascript:alert(1)"):
        response = principal.submit("/organisation", {
            "title": f"Test {evil}", "priority": "normal", "recurrence": "none", "next": evil,
        }, follow=False)
        location = response.headers["Location"]
        assert "evil" not in location and "javascript" not in location, location


def test_contextual_task_from_event_is_linked(principal):
    created = principal.api("POST", "/api/events", {"title": "Anniversaire Lou", "start_date": "2027-03-10", "all_day": True})
    event_id = created.get_json()["id"]
    page = principal.get(f"/calendrier/{event_id}").data.decode()
    assert "Tâches liées" in page and "Aucune tâche liée." in page
    link = re.search(r'href="(/organisation/nouvelle\?[^"]+)"', page).group(1).replace("&amp;", "&")
    assert "link_type=calendar_event" in link and f"link_id={event_id}" in link
    form = principal.get(link).data.decode()
    assert "Liée à" in form and "Anniversaire Lou" in form and 'value="2027-03-10"' in form
    response = principal.submit("/organisation", {
        "title": "Acheter le gâteau", "due_date": "2027-03-09", "priority": "normal", "recurrence": "none",
        "link_type": "calendar_event", "link_id": str(event_id), "next": f"/calendrier/{event_id}",
    }, follow=False)
    assert response.headers["Location"].endswith(f"/calendrier/{event_id}")
    page = principal.get(f"/calendrier/{event_id}").data.decode()
    assert "Acheter le gâteau" in page and "Aucune tâche liée." not in page


def test_contextual_task_from_inventory_item(principal):
    item = principal.api("POST", "/api/inventory/items", {"name": "Chaudière", "visibility": "household"}).get_json()
    page = principal.get(f"/inventaire/{item['id']}").data.decode()
    assert "Tâches liées" in page and "link_type=inventory_item" in page
    principal.submit("/organisation", {
        "title": "Révision chaudière", "priority": "normal", "recurrence": "none",
        "link_type": "inventory_item", "link_id": str(item["id"]),
    })
    assert "Révision chaudière" in principal.get(f"/inventaire/{item['id']}").data.decode()


def test_context_link_to_invisible_item_is_refused(principal, secondary):
    hidden = principal.api("POST", "/api/inventory/items", {"name": "Bijou privé", "visibility": "private"}).get_json()
    assert secondary.get(f"/organisation/nouvelle?link_type=inventory_item&link_id={hidden['id']}").status_code == 404
    secondary.get("/")
    response = secondary.submit("/organisation", {
        "title": "Espionner", "priority": "normal", "recurrence": "none",
        "link_type": "inventory_item", "link_id": str(hidden["id"]),
    }, follow=False)
    assert response.status_code == 404
    assert not any(t["title"] == "Espionner" for t in _tasks(principal))


def test_validation_error_keeps_input_and_next(principal):
    principal.get("/organisation/nouvelle?next=/finances")
    response = principal.submit("/organisation", {
        "title": "", "notes": "garde-moi", "priority": "normal", "recurrence": "none", "next": "/finances",
    })
    page = response.data.decode()
    assert response.status_code == 400
    assert 'aria-invalid="true"' in page and "garde-moi" in page
    assert 'name="next" value="/finances"' in page
