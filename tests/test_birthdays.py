"""Anniversaires familiaux : liste, idempotence, hors démo et hors tests."""

import sqlite3
from datetime import datetime, timezone

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect
from app.services.birthdays import FAMILY_BIRTHDAYS, ensure_family_birthdays, seed_if_household, title_for
from app.services.demo import DEMO_HOUSEHOLD
from tests.test_flows import PASSWORD, Web

OCTOBER = (
    "Dyahel Aquilon",
    "Syloé Ferrant",
    "Wilfried Aboa",
    "Nell Cairo",
    "Marien Aboh",
)


def _ctx(app, home, clock):
    conn = connect(home / "data" / "metadata.sqlite")
    return conn, Ctx(
        conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"], household_id=1,
    )


def test_liste_familiale_quarante_huit_noms():
    assert len(FAMILY_BIRTHDAYS) == 48
    titles = [title_for(name) for _month, _day, name in FAMILY_BIRTHDAYS]
    assert len(set(titles)) == 48
    assert (12, 2, "Roger Cairo") in FAMILY_BIRTHDAYS
    assert (4, 22, "Roger Moute") in FAMILY_BIRTHDAYS
    assert (10, 11, "Syloé Ferrant") in FAMILY_BIRTHDAYS
    assert (5, 24, "Laïna AQUILON") in FAMILY_BIRTHDAYS
    assert (12, 17, "Aélyah AQUILON") in FAMILY_BIRTHDAYS
    ordered = [(month, day) for month, day, _name in FAMILY_BIRTHDAYS]
    assert ordered == sorted(ordered)


def test_les_tests_ne_recoivent_pas_les_anniversaires(tmp_path):
    clock = FrozenClock(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc))
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap(name="Roger Cairo")
    page = web.get("/calendrier?vue=mois&date=2026-10-01")
    assert page.status_code == 200
    assert "Dyahel" not in page.data.decode()
    assert b"Rien de pr" in page.data


def test_alimentation_explicite_est_annuelle_et_idempotente(tmp_path):
    clock = FrozenClock(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc))
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap(name="Roger Cairo")
    conn, ctx = _ctx(app, home, clock)
    try:
        assert ensure_family_birthdays(ctx, {"id": 1}) == 48
        assert ensure_family_birthdays(ctx, {"id": 1}) == 0
        rows = conn.execute(
            "SELECT title, start_date, recurrence, all_day, notes, responsible_id FROM calendar_event"
        ).fetchall()
        assert len(rows) == 48
        assert {row["recurrence"] for row in rows} == {"yearly"}
        assert {row["all_day"] for row in rows} == {1}
        assert {row["notes"] for row in rows} == {"Anniversaire familial"}
        assert {row["responsible_id"] for row in rows} == {None}
        by_title = {row["title"]: row["start_date"] for row in rows}
        assert by_title["Anniversaire de Dyahel Aquilon"] == "2000-10-05"
        assert by_title["Anniversaire de Roger Cairo"] == "2000-12-02"
        assert by_title["Anniversaire de Haylé Claude"] == "2000-08-10"
        assert by_title["Anniversaire de Tatie Marie Claire"] == "2000-08-12"
    finally:
        conn.close()

    october = web.get("/calendrier?vue=mois&date=2026-10-01").data.decode()
    for name in OCTOBER:
        assert f"Anniversaire de {name}" in october
    today = web.get("/").data.decode()
    assert "Anniversaire de Nell Cairo" in today
    assert "Anniversaire de Marien Aboh" in today
    assert "Tatie Gertrude" not in today


def test_meme_si_le_calendrier_est_desactive(tmp_path):
    clock = FrozenClock(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc))
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    Web(app).bootstrap()
    conn, ctx = _ctx(app, home, clock)
    try:
        conn.execute("UPDATE module_setting SET enabled=0 WHERE module_key='calendrier'")
        conn.commit()
        assert ensure_family_birthdays(ctx, {"id": 1}) == 48
    finally:
        conn.close()


def test_la_demo_est_ignoree(tmp_path):
    clock = FrozenClock(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc))
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    Web(app).bootstrap()
    conn, ctx = _ctx(app, home, clock)
    try:
        conn.execute("UPDATE household SET name=? WHERE id=1", (DEMO_HOUSEHOLD,))
        conn.commit()
        assert ensure_family_birthdays(ctx, {"id": 1}) == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM calendar_event").fetchone()["n"] == 0
    finally:
        conn.close()
    live = create_app(home=home, clock=clock, testing=False)
    assert seed_if_household(live) == 0


def test_redemarrage_alimente_un_foyer_existant(tmp_path):
    clock = FrozenClock(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc))
    home = tmp_path / "inst"
    quiet = create_app(home=home, clock=clock, testing=True)
    Web(quiet).bootstrap(name="Roger Cairo")
    live = create_app(home=home, clock=clock, testing=False)
    assert seed_if_household(live) == 48
    assert seed_if_household(live) == 0
    empty = create_app(home=tmp_path / "vide", clock=clock, testing=False)
    assert seed_if_household(empty) == 0


def test_initialisation_reelle_alimente_tout_de_suite(tmp_path):
    clock = FrozenClock(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc))
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=False, port=8765)
    web = Web(app)
    done = web.bootstrap(name="Roger Cairo")
    assert done.status_code == 200
    page = web.get("/calendrier?vue=mois&date=2026-12-01")
    body = page.data.decode()
    assert "Anniversaire de Roger Cairo" in body
    assert "Anniversaire de Jessy Oloko" in body
    assert "Anniversaire de Aélyah AQUILON" in body
    conn = sqlite3.connect(home / "data" / "metadata.sqlite")
    try:
        count = conn.execute("SELECT COUNT(*) FROM calendar_event WHERE recurrence='yearly'").fetchone()[0]
    finally:
        conn.close()
    assert count == 48


def test_api_bootstrap_reel_alimente(tmp_path):
    clock = FrozenClock(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc))
    app = create_app(home=tmp_path / "inst", clock=clock, testing=False, port=8765)
    web = Web(app)
    web.get("/initialisation")
    created = web.api("POST", "/api/bootstrap", {
        "household_name": "Foyer",
        "timezone": "Europe/Paris",
        "display_name": "Roger Cairo",
        "username": "roger",
        "password": PASSWORD,
    })
    assert created.status_code == 201
    page = web.get("/calendrier?vue=mois&date=2026-05-01")
    body = page.data.decode()
    assert "Anniversaire de Laïna AQUILON" in body
    assert "Anniversaire de Stéphanie Moute" in body
    assert "Anniversaire de Carl Zobel" in body
