"""D1 : CSP `script-src 'self'` et script local d'amélioration progressive (app/static/js/app.js)."""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect
from tests.test_flows import PDF, Web

SCRIPT_TAG = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
JS_FILE = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js"


def assert_first_party_scripts(body):
    """Seuls des scripts locaux /static/js/ sont chargés : aucun script inline, externe ni gestionnaire on*."""
    if isinstance(body, bytes):
        body = body.decode()
    assert body.lower().count("<script") == len(SCRIPT_TAG.findall(body))
    for attrs, inline in SCRIPT_TAG.findall(body):
        src = re.search(r'\ssrc="([^"]+)"', attrs)
        assert src, attrs
        assert src.group(1).startswith("/static/js/"), src.group(1)
        assert not inline.strip(), inline
    assert not re.search(r"\son[a-z]+=", body)
    assert "javascript:" not in body.lower()


def csp_directives(response):
    policy = response.headers.get("Content-Security-Policy", "")
    return {part.split()[0]: part.split()[1:] for part in (p.strip() for p in policy.split(";")) if part}


@pytest.fixture
def world(tmp_path):
    clock = FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    return web, app, home


def test_csp_allows_only_same_origin_scripts(world):
    web, _app, _home = world
    for path in ("/", "/coffre", "/organisation", "/page-qui-n-existe-pas", "/static/js/app.js"):
        directives = csp_directives(web.get(path))
        assert directives["script-src"] == ["'self'"], path
        assert directives["default-src"] == ["'self'"], path
        assert directives["style-src"] == ["'self'"], path
        assert directives["object-src"] == ["'none'"], path
        assert directives["base-uri"] == ["'none'"], path
        assert directives["frame-ancestors"] == ["'none'"], path
        assert "script-src-elem" not in directives and "script-src-attr" not in directives, path
        policy = " ".join(" ".join(v) for v in directives.values())
        for forbidden in ("unsafe-inline", "unsafe-eval", "unsafe-hashes", "nonce-", "sha256-", "http:", "https:", "data:", "*"):
            assert forbidden not in policy, (path, forbidden)


def test_guest_pages_keep_strict_csp(tmp_path):
    app = create_app(home=tmp_path / "guest", testing=True)
    web = Web(app)
    page = web.get("/initialisation")
    assert csp_directives(page)["script-src"] == ["'self'"]
    assert_first_party_scripts(page.data)


def test_shell_loads_single_deferred_local_script(world):
    web, _app, _home = world
    body = web.get("/").data.decode()
    tags = SCRIPT_TAG.findall(body)
    assert len(tags) == 1
    attrs = tags[0][0]
    assert 'src="/static/js/app.js"' in attrs and " defer" in attrs
    assert "type=" not in attrs and "integrity" not in attrs
    assert_first_party_scripts(body)


def test_script_is_served_same_origin_with_nosniff(world):
    web, _app, _home = world
    response = web.get("/static/js/app.js")
    assert response.status_code == 200
    assert response.mimetype in ("text/javascript", "application/javascript")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_script_is_small_dependency_free_and_stateless():
    source = JS_FILE.read_text(encoding="utf-8")
    assert len(source.encode()) < 16 * 1024
    for forbidden in (
        "eval(", "new Function", "setTimeout(\"", "innerHTML", "outerHTML", "insertAdjacentHTML",
        "document.write", "fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "document.cookie",
        "import ", "require(", "http://", "https://",
    ):
        assert forbidden not in source, forbidden
    assert list(JS_FILE.parent.iterdir()) == [JS_FILE]


def test_enhanced_widgets_keep_no_js_fallbacks(world):
    web, _app, _home = world
    home = web.get("/").data.decode()
    assert '<details class="menu create-menu">' in home and '<details class="menu user-menu">' in home
    assert '<details class="foyer-switcher">' in home
    assert 'href="#ajout-tache"' in home and 'href="#ajout-evenement"' in home
    assert home.count('class="quick-close" href="#contenu"') == 2
    assert 'class="quick-backdrop" href="#contenu"' in home
    css = web.c.get("/static/app.css", headers={"Host": "127.0.0.1:8765"}).data.decode()
    assert ".quick-panel:target" in css and ".drop-zone.is-dragover" in css


def test_drop_zone_posts_native_form_to_active_household(world):
    web, _app, home = world
    web.api("POST", "/api/milestones", {"name": "Bail foyer 1", "category": "Logement"})
    web.submit("/foyers/creer", {"household_name": "Chalet", "timezone": "Europe/Zurich", "display_name": "Roger chalet"})
    holder = next(p for p in web.api("GET", "/api/people").get_json()["items"] if p["is_principal"])["id"]
    mid = web.api("POST", "/api/milestones", {"name": "Bail chalet", "category": "Logement", "holder_id": holder}).get_json()["id"]

    page = web.get("/coffre").data.decode()
    form = page[page.index('id="depot"'):page.index("</form>", page.index('id="depot"'))]
    assert 'method="post"' in form and 'enctype="multipart/form-data"' in form and 'action="/coffre"' in form
    assert 'name="csrf_token"' in form and 'class="drop-zone"' in form
    assert re.search(r'<input type="file" name="file"[^>]*required', form)
    assert 'name="confirm" value="oui"' in form
    assert "Bail chalet" in form and "Bail foyer 1" not in form

    assert web.upload("/coffre", "chalet.pdf", PDF, milestone_id=str(mid), confirm="oui").status_code == 200
    conn = connect(home / "data" / "metadata.sqlite")
    rows = conn.execute(
        "SELECT h.name FROM stored_file f JOIN milestone m ON m.id=f.milestone_id "
        "JOIN household h ON h.id=m.household_id WHERE f.original_name='chalet.pdf'"
    ).fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["Chalet"]

    foyer = next(i["household_id"] for i in web.api("GET", "/api/households").get_json()["items"] if i["household_name"] == "Foyer")
    web.submit("/foyers/basculer", {"household_id": str(foyer), "next": "/coffre"})
    assert "chalet.pdf" not in web.get("/coffre").data.decode()


def test_drop_upload_still_requires_csrf(world):
    web, _app, _home = world
    holder = next(p for p in web.api("GET", "/api/people").get_json()["items"] if p["is_principal"])["id"]
    mid = web.api("POST", "/api/milestones", {"name": "Bail", "category": "Logement", "holder_id": holder}).get_json()["id"]
    web.get("/coffre")
    web.token = "jeton-invalide"
    response = web.upload("/coffre", "x.pdf", PDF, milestone_id=str(mid), confirm="oui")
    assert response.status_code == 400
    assert "Jeton de sécurité invalide" in response.data.decode()
    web.get("/coffre")
    assert "x.pdf" not in web.get("/coffre").data.decode()


def test_vault_files_are_scoped_to_active_household(world):
    web, _app, _home = world
    me = next(p for p in web.api("GET", "/api/people").get_json()["items"] if p["is_principal"])["id"]
    mine = web.api("POST", "/api/milestones", {"name": "Bail foyer 1", "category": "Logement", "holder_id": me}).get_json()["id"]
    web.get("/coffre")
    web.upload("/coffre", "foyer1.pdf", PDF, milestone_id=str(mine), confirm="oui")
    file_id = next(i["id"] for i in web.api("GET", "/api/files").get_json()["items"] if i["original_name"] == "foyer1.pdf")

    web.submit("/foyers/creer", {"household_name": "Chalet", "timezone": "Europe/Zurich", "display_name": "Roger chalet"})
    web.get("/coffre")
    assert "foyer1.pdf" not in web.get("/coffre").data.decode()
    assert all(i["id"] != file_id for i in web.api("GET", "/api/files").get_json()["items"])
    assert web.get(f"/coffre/{file_id}/ouvrir").status_code == 404
    assert web.api("GET", f"/api/files/{file_id}/content").status_code == 404
    assert web.api("DELETE", f"/api/files/{file_id}", {"confirm": True}).status_code == 404
    assert web.get(f"/coffre/{file_id}/remplacer").status_code == 404
    assert web.upload("/coffre", "intrus.pdf", PDF, milestone_id=str(mine), confirm="oui").status_code == 404
