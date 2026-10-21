"""UX V2.1 Sprint 4 : vues métier (Agenda, À faire, Finances, Inventaire, Coffre, Médiathèque, Décisions)."""

import html
import re
from datetime import datetime, timezone

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect
from app.security import AttemptLimiter
from app.services.demo import DEMO_PASSWORD, DEMO_PASSWORD_SECONDARY, DEMO_USERNAME, seed_demo
from tests.test_flows import PDF, Web


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
def alex(demo_app):
    return _web(demo_app, DEMO_USERNAME, DEMO_PASSWORD)


@pytest.fixture
def camille(demo_app):
    return _web(demo_app, "camille", DEMO_PASSWORD_SECONDARY)


@pytest.fixture
def empty(tmp_path, clock):
    web = Web(create_app(home=tmp_path / "empty", clock=clock, testing=True))
    web.bootstrap()
    return web


def _people(web):
    return {p["display_name"]: p for p in web.api("GET", "/api/people").get_json()["items"]}


def _cell(page, iso):
    """Contenu de la case du jour `iso` dans la grille mois / semaine."""
    text = page.data.decode()
    marker = f"start_date={iso}"
    start = text.rindex("<td", 0, text.index(marker))
    return text[start:text.index("</td>", start)]


# Agenda

def test_agenda_month_week_list(alex):
    alex.api("POST", "/api/events", {"title": "Vacances ski", "start_date": "2027-02-22", "end_date": "2027-02-24", "all_day": True})
    alex.api("POST", "/api/events", {"title": "Mars lointain", "start_date": "2027-03-25", "all_day": True})

    month = alex.get("/calendrier")
    assert month.status_code == 200
    assert "Février 2027" in month.data.decode()
    for iso in ("2027-02-22", "2027-02-23", "2027-02-24"):
        assert "Vacances ski" in _cell(month, iso)
    assert "Vacances ski" not in _cell(month, "2027-02-25")
    assert "Mars lointain" not in month.data.decode()
    assert "is-today" in _cell(month, "2027-02-20")

    week = alex.get("/calendrier?vue=semaine&date=2027-02-23").data.decode()
    assert "Semaine du 22 février au 28 février 2027" in week and "Vacances ski" in week

    listing = alex.get("/calendrier?vue=liste&date=2027-02-20").data.decode()
    assert listing.count(">Vacances ski<") == 1 and "Mars lointain" in listing
    assert "jusqu'au" in listing

    march = alex.get("/calendrier?vue=mois&date=2027-03-01").data.decode()
    assert "Mars 2027" in march and "Mars lointain" in march
    nav = re.findall(r'href="(/calendrier\?[^"]+)" rel="(prev|next)"', alex.get("/calendrier").data.decode())
    assert {rel for _href, rel in nav} == {"prev", "next"}
    assert any("date=2027-01-01" in href for href, _ in nav) and any("date=2027-03-01" in href for href, _ in nav)


def test_agenda_member_filter_and_milestones(alex, camille):
    people = _people(alex)
    camille_id = people["Camille Dubois"]["id"]
    alex.api("POST", "/api/events", {"title": "Pédiatre Lou", "start_date": "2027-02-23", "all_day": True, "responsible_id": camille_id})
    alex.api("POST", "/api/events", {"title": "Garage", "start_date": "2027-02-24", "all_day": True, "responsible_id": people["Alex Martin"]["id"]})
    holder = people["Alex Martin"]["id"]
    alex.api("POST", "/api/milestones", {"name": "Permis Alex", "category": "Identité", "holder_id": holder, "due_date": "2027-02-26"})

    full = alex.get("/calendrier").data.decode()
    assert "Pédiatre Lou" in full and "Garage" in full and "Permis Alex" in full
    assert "agenda-entry--milestone" in full
    filtered = alex.get(f"/calendrier?membre={camille_id}").data.decode()
    assert "Pédiatre Lou" in filtered and "Garage" not in filtered and "Permis Alex" not in filtered
    assert "(filtré)" in filtered
    nobody = alex.get("/calendrier?q=introuvable").data.decode()
    assert "Aucun résultat" in nobody and "Retirer le filtre" in nobody


def test_agenda_hides_milestones_without_index(demo_app, alex, tmp_path):
    alex.api("POST", "/api/milestones", {
        "name": "Passeport secret", "category": "Identité", "holder_id": _people(alex)["Alex Martin"]["id"], "due_date": "2027-02-26",
    })
    conn = connect(tmp_path / "demo" / "data" / "metadata.sqlite")
    conn.execute("UPDATE person SET can_view_index=0 WHERE display_name='Camille Dubois'")
    conn.commit()
    conn.close()
    web = _web(demo_app, "camille", DEMO_PASSWORD_SECONDARY)
    page = web.get("/calendrier").data.decode()
    assert "Passeport secret" not in page
    assert "non accordées à votre compte" in page


# À faire

def test_tasks_grouped_quick_add_reopen(alex):
    me = _people(alex)["Alex Martin"]["id"]
    alex.api("POST", "/api/tasks", {"title": "Impôts en retard", "due_date": "2027-02-10"})
    alex.api("POST", "/api/tasks", {"title": "Appeler la crèche", "due_date": "2027-02-20", "assignee_id": me})
    alex.api("POST", "/api/tasks", {"title": "Vider la cave", "recurrence": "monthly", "due_date": "2027-03-01"})
    page = html.unescape(alex.get("/organisation").data.decode())
    late = page[page.index(">En retard"):]
    assert late.index("Impôts en retard") < late.index("Aujourd'hui") < late.index("Appeler la crèche") < late.index("À venir")
    assert "Mensuelle" in page

    mine = alex.get("/organisation?pour=moi").data.decode()
    assert "Appeler la crèche" in mine and "Impôts en retard" not in mine

    alex.submit("/organisation", {"title": "Rapide", "priority": "normal", "recurrence": "none", "next": "/organisation"})
    assert "Rapide" in alex.get("/organisation").data.decode()

    task = next(t for t in alex.api("GET", "/api/tasks?status=open").get_json()["items"] if t["title"] == "Rapide")
    alex.submit(f"/organisation/{task['id']}/terminer", {"next": "/organisation"})
    done = alex.get("/organisation?status=done").data.decode()
    assert "Rapide" in done and "Rouvrir « Rapide »" in done
    response = alex.submit(f"/organisation/{task['id']}/rouvrir", {"next": "/organisation?status=done"}, follow=False)
    assert response.status_code in (302, 303)
    assert "Rapide" in alex.get("/organisation").data.decode()


def test_tasks_reopen_requires_csrf(alex):
    task = alex.api("POST", "/api/tasks", {"title": "Protégée"}).get_json()
    alex.api("PATCH", f"/api/tasks/{task['id']}", {"status": "done"})
    response = alex.c.post(f"/organisation/{task['id']}/rouvrir", data={}, headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"})
    assert response.status_code in (400, 403)


# Finances

def _expense(web, label, amount, currency, payer, visibility="household", date="2027-02-15", split=None):
    account = next(a for a in web.api("GET", "/api/finance/accounts").get_json()["items"] if a["currency"] == currency)
    category = web.api("GET", "/api/finance/categories?kind=expense").get_json()["items"][0]
    created = web.api("POST", "/api/finance/transactions", {
        "kind": "expense", "amount": amount, "currency": currency, "txn_date": date, "label": label,
        "category_id": category["id"], "ledger_account_id": account["id"], "payer_id": payer,
        "split_method": "equal", "split_person_ids": split or [payer], "visibility": visibility,
    })
    assert created.status_code == 201, created.get_json()


def test_finance_sections_and_currencies(alex, camille):
    me = _people(alex)["Alex Martin"]["id"]
    _expense(alex, "Courses CHF", "50,00", "CHF", me)
    _expense(alex, "Péage EUR", "20,00", "EUR", me)
    _expense(alex, "Cadeau secret", "99,00", "CHF", me, visibility="private")

    for vue in ("", "transactions", "budgets", "comptes", "repartition", "nimporte"):
        assert alex.get(f"/finances?vue={vue}").status_code == 200, vue

    overview = alex.get("/finances").data.decode()
    assert 'aria-current="page">Vue d&#39;ensemble' in overview or "aria-current=\"page\">Vue d'ensemble" in overview
    assert "Courses CHF" in overview and "Péage EUR" not in overview
    assert "month-bars" in overview and overview.count("<li") >= 6
    assert 'style="' not in overview

    chf = alex.get("/finances?vue=transactions").data.decode()
    eur = alex.get("/finances?vue=transactions&currency=EUR").data.decode()
    assert "Courses CHF" in chf and "Péage EUR" not in chf
    assert "Péage EUR" in eur and "Courses CHF" not in eur
    assert "Cadeau secret" in chf

    seen_by_camille = camille.get("/finances?vue=transactions").data.decode()
    assert "Courses CHF" in seen_by_camille and "Cadeau secret" not in seen_by_camille
    assert "Cadeau secret" not in camille.get("/finances").data.decode()

    expenses = alex.get("/finances?vue=transactions&type=income").data.decode()
    assert "Aucune transaction de ce type" in expenses


def test_finance_month_total_respects_visibility(alex, camille):
    me = _people(alex)["Alex Martin"]["id"]
    _expense(alex, "Visible", "10,00", "CHF", me, date="2027-02-05")
    _expense(alex, "Privée", "1000,00", "CHF", me, visibility="private", date="2027-02-06")
    alex_page = alex.get("/finances").data.decode()
    camille_page = camille.get("/finances").data.decode()
    def total(page):
        raw = re.search(r'class="stat-big">([^<]+) CHF<', page).group(1)
        return int(raw.replace(",", "").replace("'", "").replace(" ", ""))

    camille_before = total(camille_page)
    assert total(alex_page) - camille_before == 100000
    assert camille_before >= 1000


# Inventaire

def test_inventory_gallery_list_filters_and_privacy(alex, camille):
    place = alex.api("POST", "/api/inventory/places", {"name": "Garage"}).get_json()
    alex.api("POST", "/api/inventory/items", {"name": "Perceuse", "category": "Outillage", "place_id": place["id"]})
    alex.api("POST", "/api/inventory/items", {"name": "Bague", "category": "Bijoux secrets", "visibility": "private"})

    gallery = alex.get("/inventaire").data.decode()
    assert "item-gallery" in gallery and "Perceuse" in gallery and "Mixeur plongeant" in gallery
    listing = alex.get("/inventaire?vue=liste").data.decode()
    assert "data-table" in listing and "Perceuse" in listing
    by_cat = alex.get("/inventaire?categorie=Outillage").data.decode()
    assert "Perceuse" in by_cat and "Mixeur plongeant" not in by_cat
    by_place = alex.get(f"/inventaire?place_id={place['id']}&vue=liste").data.decode()
    assert "Perceuse" in by_place and "Mixeur plongeant" not in by_place
    assert "Aucun bien trouvé" in alex.get("/inventaire?q=zzz").data.decode()

    theirs = camille.get("/inventaire").data.decode()
    assert "Bague" not in theirs and "Bijoux secrets" not in theirs
    assert "Bijoux secrets" in gallery


# Coffre

def test_vault_explorer_filters_and_access(alex, camille):
    holder = _people(alex)["Alex Martin"]["id"]
    mid = alex.api("POST", "/api/milestones", {"name": "Bail appartement", "category": "Logement", "holder_id": holder}).get_json()["id"]
    alex.get("/coffre")
    assert alex.upload("/coffre", "bail-2026.pdf", PDF, milestone_id=str(mid), confirm="oui").status_code == 200
    page = alex.get("/coffre").data.decode()
    assert "bail-2026.pdf" in page and "Bail appartement" in page and 'id="depot"' in page
    assert "drop-zone" in page
    assert "bail-2026.pdf" in alex.get("/coffre?type=PDF").data.decode()
    assert "Aucun document trouvé" in alex.get("/coffre?type=Image").data.decode()
    assert "bail-2026.pdf" in alex.get("/coffre?q=appartement").data.decode()

    theirs = camille.get("/coffre").data.decode()
    assert "bail-2026.pdf" not in theirs and "Bail appartement" not in theirs
    assert 'id="depot"' not in theirs and "Aucun document partagé avec vous" in theirs
    assert "bail-2026.pdf" not in camille.get("/coffre?q=bail").data.decode()


# Médiathèque

def test_media_tabs(alex):
    alex.get("/mediatheque/oeuvre/nouvelle")
    for tab in ("", "en-cours", "envies", "listes", "fichiers", "inconnu"):
        assert alex.get(f"/mediatheque?onglet={tab}").status_code == 200, tab
    page = alex.get("/mediatheque").data.decode()
    assert "Catalogue" in page and "Mes fichiers" in page


# Décisions

def test_decisions_presentation_and_creation_path(alex, camille):
    page = alex.get("/decisions").data.decode()
    assert "Rédiger" in page and "Sceller" in page and "Compléter" in page
    assert 'id="nouvelle-decision"' in page and 'action="/decisions/nouvelle"' in page
    repere = re.search(r'<option value="(\d+)">', page[page.index('id="nouvelle-decision"'):]).group(1)
    assert alex.get(f"/decisions/nouvelle?repere={repere}").status_code == 200

    theirs = camille.get("/decisions").data.decode()
    assert 'id="nouvelle-decision"' not in theirs and "Aucune décision partagée avec vous" in theirs


def test_decision_create_menu_points_to_form(alex):
    menu = alex.get("/").data.decode()
    assert 'href="/decisions#nouvelle-decision"' in menu


# États vides

@pytest.mark.parametrize("url, title, action", [
    ("/calendrier", "Rien de prévu sur cette période", "/calendrier/nouveau"),
    ("/organisation", "Aucune tâche à faire", "/organisation/nouvelle"),
    ("/finances?vue=transactions", "Aucune transaction en CHF", "/finances/depense"),
    ("/finances?vue=budgets", "Aucun budget en CHF", "/finances/budget"),
    ("/inventaire", "Votre inventaire est vide", "/inventaire/nouveau"),
    ("/coffre", "Le coffre est vide", "#depot"),
    ("/mediatheque", "Le catalogue est vide", "/mediatheque/oeuvre/nouvelle"),
    ("/mediatheque?onglet=fichiers", "Aucun fichier personnel", "/mediatheque/bibliotheque/depot"),
    ("/decisions", "Aucune décision pour l&#39;instant", "/reperes/nouveau"),
])
def test_empty_states_have_a_primary_action(empty, url, title, action):
    page = empty.get(url).data.decode()
    assert "empty-state" in page, url
    assert title in page, (url, title)
    section = page[page.index("empty-state"):]
    assert re.search(r'class="btn btn--primary" href="' + re.escape(action), section), (url, action)
