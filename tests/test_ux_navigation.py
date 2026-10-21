"""UX V2.1 Sprint 1 : App Shell, navigation groupée, droits et modules."""

import html
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
    return app, home


def _web(app, username, password):
    web = Web(app)
    web.login(username, password)
    return web


@pytest.fixture
def principal(demo_app):
    return _web(demo_app[0], DEMO_USERNAME, DEMO_PASSWORD)


@pytest.fixture
def secondary(demo_app):
    return _web(demo_app[0], "camille", DEMO_PASSWORD_SECONDARY)


def _section(html, start, end):
    text = html.decode()
    return text[text.index(start):text.index(end, text.index(start))]


def _sidebar(page):
    return _section(page.data, '<aside class="sidebar"', "</aside>")


def _create_menu(page):
    return _section(page.data, '<details class="menu create-menu">', "</details>")


def _hrefs(fragment):
    return [href.replace("&amp;", "&") for href in re.findall(r'href="(/[^"]*)"', fragment)]


def _disable(home, *keys):
    conn = connect(home / "data" / "metadata.sqlite")
    for key in keys:
        conn.execute("UPDATE module_setting SET enabled=0 WHERE module_key=?", (key,))
    conn.commit()
    conn.close()


def test_sidebar_groups_replace_flat_bar(principal):
    page = principal.get("/")
    sidebar = _sidebar(page)
    groups = [html.unescape(g) for g in re.findall(r'class="nav-link"[^>]*>([^<]+)<', sidebar)]
    assert groups == ["Aujourd'hui", "Agenda", "À faire", "Finances", "Maison", "Bibliothèque", "Paramètres"]
    assert "Principal" in sidebar and "Administration" in sidebar
    assert 'href="/recherche"' not in sidebar
    assert 'role="search"' in page.data.decode()


@pytest.mark.parametrize("start", ["/", "/calendrier", "/organisation", "/finances", "/inventaire", "/coffre", "/parametres"])
def test_every_nav_and_create_link_opens(principal, start):
    page = principal.get(start)
    for href in _hrefs(_sidebar(page)) + _hrefs(_create_menu(page)):
        target = href.split("#")[0]
        response = principal.get(target)
        assert response.status_code == 200, (start, href, response.status_code)


def test_active_state_marks_group_and_child(principal):
    page = principal.get("/calendrier").data.decode()
    assert re.search(r'nav-group is-active">\s*<a class="nav-link" href="/calendrier"', page)
    assert 'href="/calendrier" aria-current="page">Calendrier' in page
    assert 'href="/reperes" >Repères' in page or 'href="/reperes">Repères' in page
    assert 'href="/organisation/nouvelle' in principal.get("/organisation").data.decode()


def test_secondary_account_sees_no_admin_entries(secondary):
    page = secondary.get("/")
    sidebar = _sidebar(page)
    create = _create_menu(page)
    for forbidden in ("/acces", "/foyer", "/parametres/avance"):
        assert f'href="{forbidden}"' not in sidebar
    for forbidden in ("Document", "Décision", "Repère"):
        assert f">{forbidden}<" not in create
    assert ">Dépense<" in create and ">Tâche<" in create
    assert secondary.get("/parametres/avance").status_code == 403
    for href in _hrefs(sidebar) + _hrefs(create):
        assert secondary.get(href.split("#")[0]).status_code == 200, href


def test_disabled_modules_disappear(demo_app):
    app, home = demo_app
    _disable(home, "calendrier", "coffre", "mediatheque", "decisions", "finances")
    web = _web(app, DEMO_USERNAME, DEMO_PASSWORD)
    page = web.get("/reperes")
    sidebar = _sidebar(page)
    create = _create_menu(page)
    assert 'href="/calendrier"' not in sidebar
    assert re.search(r'class="nav-link" href="/reperes"', sidebar)
    assert "Bibliothèque" not in sidebar and "Finances" not in sidebar
    assert ">Événement<" not in create and ">Dépense<" not in create and ">Document<" not in create
    assert web.get("/calendrier").status_code == 404


def test_legacy_and_alias_routes(principal):
    for alias, target in {"/agenda": "/calendrier", "/a-faire": "/organisation", "/maison": "/inventaire", "/bibliotheque": "/coffre"}.items():
        response = principal.get(alias)
        assert response.status_code == 302
        assert response.headers["Location"].endswith(target)
    for legacy in ("/foyer", "/personnes", "/acces", "/recherche", "/profil", "/reperes", "/decisions", "/mediatheque"):
        assert principal.get(legacy).status_code == 200


def test_cli_commands_moved_to_advanced_admin(principal):
    settings = principal.get("/parametres").data.decode()
    assert "python cli.py" not in settings
    assert 'href="/parametres/avance"' in settings
    advanced = principal.get("/parametres/avance")
    assert advanced.status_code == 200
    assert "Sauvegarde" in advanced.data.decode() and "python cli.py backup" in advanced.data.decode()


def test_user_menu_logout_still_posts_with_csrf(principal):
    page = principal.get("/").data.decode()
    menu = _section(page.encode(), '<details class="menu user-menu">', "</details>")
    assert 'action="/deconnexion"' in menu and 'name="csrf_token"' in menu
    principal.submit("/deconnexion", {})
    assert principal.get("/").status_code in (302, 303)


def test_shell_markup_stays_script_free(principal):
    page = principal.get("/")
    assert b"<script" not in page.data
    assert "script-src 'none'" in page.headers["Content-Security-Policy"]
