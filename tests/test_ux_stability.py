"""UX V2.1 Sprint 0 : stabilité Calendrier / Organisation / Recherche, crawl des pages."""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect
from app.security import AttemptLimiter
from app.services.demo import DEMO_PASSWORD, DEMO_USERNAME, seed_demo
from tests.test_flows import Web

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"
SKIP = ("/static", "/deconnexion", "/ouvrir", "export")


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def empty(tmp_path, clock):
    app = create_app(home=tmp_path / "vide", clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    return web


@pytest.fixture
def demo(tmp_path, clock):
    home = tmp_path / "demo"
    app = create_app(home=home, clock=clock, testing=True)
    with app.app_context():
        conn = connect(home / "data" / "metadata.sqlite")
        seed_demo(Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"]), AttemptLimiter())
        conn.close()
    web = Web(app)
    web.login(DEMO_USERNAME, DEMO_PASSWORD)
    return web


def _crawl(web):
    seen, todo, failures = set(), ["/"], []
    while todo:
        url = todo.pop()
        # La navigation par période (Précédent / Suivant) est infinie : une seule visite par vue.
        shape = re.sub(r"([?&])date=[^&]*", r"\1", url)
        if shape in seen:
            continue
        seen.add(shape)
        response = web.get(url)
        if response.status_code >= 500 or "Opération impossible".encode() in response.data:
            failures.append(url)
        if response.status_code == 200 and response.mimetype == "text/html":
            for href in re.findall(rb'href="(/[^"#]*)"', response.data):
                href = href.decode().replace("&amp;", "&")
                if not any(part in href for part in SKIP):
                    todo.append(href)
    return seen, failures


def test_templates_never_read_dict_methods_as_keys():
    """`x.items` en Jinja renvoie dict.items (méthode) avant la clé "items"."""
    pattern = re.compile(r"\b\w+\.(items|keys|values)\b(?!\s*\()")
    offenders = []
    for path in TEMPLATES.glob("*.html"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == []


@pytest.mark.parametrize("household", ["empty", "demo"])
def test_every_linked_page_renders(household, request):
    web = request.getfixturevalue(household)
    seen, failures = _crawl(web)
    assert {"/calendrier", "/organisation"} <= seen
    assert failures == []


def test_calendar_lists_and_edits_events(empty):
    page = empty.get("/calendrier")
    assert page.status_code == 200
    assert "Rien de prévu sur cette période".encode() in page.data
    empty.get("/calendrier/nouveau")
    created = empty.submit("/calendrier", {
        "title": "Dentiste Léa", "start_date": "2027-03-02", "all_day": "1",
        "timezone": "Europe/Berlin", "recurrence": "none",
    })
    assert created.status_code == 200
    page = empty.get("/calendrier?vue=liste")
    assert "Dentiste Léa".encode() in page.data
    event_id = int(re.search(rb'href="/calendrier/(\d+)"', page.data).group(1))
    empty.get(f"/calendrier/{event_id}/modifier")
    empty.submit(f"/calendrier/{event_id}", {
        "title": "Dentiste Léa (déplacé)", "start_date": "2027-03-03", "all_day": "1",
        "timezone": "Europe/Berlin", "recurrence": "none",
    })
    page = empty.get("/calendrier?vue=mois&date=2027-03-01")
    assert "Dentiste Léa (déplacé)".encode() in page.data
    assert "03.03.2027".encode() in empty.get("/calendrier?vue=liste").data or "3 mars 2027".encode() in empty.get("/calendrier?vue=liste").data


def test_organisation_lists_and_completes_tasks(empty):
    assert "Aucune tâche".encode() in empty.get("/organisation").data
    empty.get("/organisation/nouvelle")
    empty.submit("/organisation", {"title": "Arroser les plantes", "priority": "high", "recurrence": "none"})
    page = empty.get("/organisation")
    assert "Arroser les plantes".encode() in page.data
    task_id = int(re.search(rb'href="/organisation/(\d+)"', page.data).group(1))
    empty.get(f"/organisation/{task_id}/modifier")
    empty.submit(f"/organisation/{task_id}", {
        "title": "Arroser les plantes", "priority": "high", "recurrence": "none", "status": "done",
    })
    assert "Arroser les plantes".encode() not in empty.get("/organisation").data
    assert "Arroser les plantes".encode() in empty.get("/organisation?status=done").data


def test_search_with_results_renders(demo):
    page = demo.get("/recherche?q=poubelles")
    assert page.status_code == 200
    assert "Sortir les poubelles".encode() in page.data
    none = demo.get("/recherche?q=zzzzzz")
    assert none.status_code == 200
    assert "Aucun résultat".encode() in none.data
