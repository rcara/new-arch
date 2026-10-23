"""UX V2.1 Sprint 5 : qualité (erreurs distinctes, recherche filtrée, CSP : scripts locaux seulement, aucun inline)."""

import html
import re
from datetime import datetime, timezone

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect
from app.security import AttemptLimiter
from app.services.demo import DEMO_PASSWORD, DEMO_PASSWORD_SECONDARY, DEMO_USERNAME, seed_demo
from tests.test_first_party_js import assert_first_party_scripts
from tests.test_flows import Web


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def demo(tmp_path, clock):
    home = tmp_path / "demo"
    app = create_app(home=home, clock=clock, testing=True)

    def boom():
        raise RuntimeError("panne simulée")

    app.add_url_rule("/test-panne", "test_panne", boom)
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


def _text(response):
    return html.unescape(response.data.decode())


def _disable(home, *keys):
    conn = connect(home / "data" / "metadata.sqlite")
    for key in keys:
        conn.execute("UPDATE module_setting SET enabled=0 WHERE module_key=?", (key,))
    conn.commit()
    conn.close()


def _results(page):
    body = page[page.index('id="contenu"'):]
    return re.findall(r'<a href="(/[^"]+)">([^<]+)</a>', body)


# Pages d'erreur

def test_error_pages_are_distinct(alex, camille):
    denied = camille.get("/parametres/avance")
    assert denied.status_code == 403
    text = _text(denied)
    assert "Accès non accordé" in text and "Erreur 403" in text and "Revenir à Aujourd'hui" in text

    missing = alex.get("/page-qui-n-existe-pas")
    assert missing.status_code == 404
    text = _text(missing)
    assert "Page introuvable" in text and "Accès non accordé" not in text
    assert 'role="alert"' in text

    broken = alex.get("/test-panne")
    assert broken.status_code == 500
    text = _text(broken)
    assert "Une erreur est survenue" in text and "Opération impossible." in text
    assert "panne simulée" not in text
    assert 'href="/test-panne">Réessayer' in text


def test_guest_error_page_offers_login(demo):
    guest = Web(demo[0])
    response = guest.get("/page-qui-n-existe-pas")
    assert response.status_code == 404
    text = _text(response)
    assert "Aller à la connexion" in text and "Revenir à Aujourd'hui" not in text


# Recherche

def test_search_states(alex):
    prompt = _text(alex.get("/recherche"))
    assert "Que cherchez-vous ?" in prompt

    short = alex.get("/recherche?q=a")
    text = _text(short)
    assert "Saisissez au moins 2 caractères." in text and 'aria-invalid="true"' in text

    none = _text(alex.get("/recherche?q=zzzzqq"))
    assert "Aucun résultat pour « zzzzqq »" in none


def test_search_groups_by_type(alex):
    alex.api("POST", "/api/tasks", {"title": "Réparer le volet"})
    alex.api("POST", "/api/events", {"title": "Volet : passage artisan", "start_date": "2027-02-25", "all_day": True})
    page = _text(alex.get("/recherche?q=volet"))
    assert "Tâches" in page and "Événements" in page
    assert page.index("Tâches") < page.index("Réparer le volet")
    assert page.index("Événements") < page.index("Volet : passage artisan")


def test_search_hides_private_items_from_secondary(alex, camille):
    alex.api("POST", "/api/inventory/items", {"name": "Bague cachette", "visibility": "private"})
    alex.api("POST", "/api/inventory/items", {"name": "Bague commune"})
    mine = _text(alex.get("/recherche?q=bague"))
    assert "Bague cachette" in mine and "Bague commune" in mine
    theirs = _text(camille.get("/recherche?q=bague"))
    assert "Bague commune" in theirs and "Bague cachette" not in theirs
    assert "Personnes" not in _text(camille.get("/recherche?q=alex"))


def test_search_skips_disabled_modules(demo):
    app, home = demo
    web = _web(app, DEMO_USERNAME, DEMO_PASSWORD)
    web.api("POST", "/api/events", {"title": "Ostéopathe Zoé", "start_date": "2027-02-25", "all_day": True})
    web.api("POST", "/api/tasks", {"title": "Ostéopathe : rappeler"})
    assert "Ostéopathe Zoé" in _text(web.get("/recherche?q=Ostéo"))
    _disable(home, "calendrier")
    page = _text(web.get("/recherche?q=Ostéo"))
    assert "Ostéopathe : rappeler" in page
    assert "Ostéopathe Zoé" not in page and "Événements" not in page
    for href, _ in _results(page):
        assert not href.startswith("/calendrier")


# CSP : uniquement des scripts locaux /static/js, aucun script ni style inline

PAGES = [
    "/", "/calendrier", "/calendrier?vue=semaine", "/calendrier?vue=liste", "/sejours", "/sejours/nouveau", "/organisation",
    "/finances", "/finances?vue=transactions", "/finances?vue=budgets", "/finances?vue=comptes",
    "/finances?vue=repartition", "/inventaire", "/inventaire?vue=liste", "/coffre", "/mediatheque",
    "/decisions", "/reperes", "/recherche?q=fa", "/parametres", "/organisation/nouvelle",
    "/finances/depense", "/page-qui-n-existe-pas",
]


def test_pages_load_only_local_scripts_and_no_inline_style(alex):
    for path in PAGES:
        response = alex.get(path)
        body = response.data.decode()
        assert_first_party_scripts(body)
        assert not re.search(r"\sstyle=", body), path
        assert not re.search(r"\son[a-z]+=", body), path
        csp = response.headers.get("Content-Security-Policy", "")
        assert "script-src 'self';" in csp, path
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp, path


def test_every_page_has_landmarks_and_single_h1(alex):
    for path in PAGES:
        body = alex.get(path).data.decode()
        assert body.count("<h1") == 1, path
        assert '<main' in body and 'id="contenu"' in body, path
        assert 'lang="fr"' in body, path

