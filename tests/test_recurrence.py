"""D6 : événements récurrents développés en occurrences dans l'Agenda et sur Aujourd'hui."""

import re
from datetime import date, datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect
from app.services.events import occurrence_dates
from tests.test_flows import Web


def _days(start, end, rule, window_start, window_end):
    return [b.isoformat() for b, _ in occurrence_dates(start, end, rule, window_start, window_end)]


def test_daily_and_weekly_rules():
    assert _days("2027-02-01", None, "daily", "2027-02-10", "2027-02-12") == ["2027-02-10", "2027-02-11", "2027-02-12"]
    assert _days("2027-01-06", None, "weekly", "2027-02-01", "2027-02-28") == [
        "2027-02-03", "2027-02-10", "2027-02-17", "2027-02-24",
    ]


def test_monthly_keeps_anchor_day_and_clamps_month_end():
    assert _days("2027-01-31", None, "monthly", "2027-01-01", "2027-05-31") == [
        "2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30", "2027-05-31",
    ]
    assert _days("2028-01-30", None, "monthly", "2028-02-01", "2028-03-31") == ["2028-02-29", "2028-03-30"]


def test_yearly_feb_29_falls_back_to_feb_28():
    assert _days("2024-02-29", None, "yearly", "2024-01-01", "2028-12-31") == [
        "2024-02-29", "2025-02-28", "2026-02-28", "2027-02-28", "2028-02-29",
    ]


def test_window_boundaries_are_inclusive_and_series_never_precedes_its_start():
    assert _days("2027-03-01", None, "weekly", "2027-03-01", "2027-03-08") == ["2027-03-01", "2027-03-08"]
    assert _days("2027-03-01", None, "daily", "2027-02-01", "2027-02-28") == []
    assert _days("2027-03-01", None, "weekly", "2027-03-02", "2027-03-07") == []
    assert _days("2027-01-01", None, "none", "2027-01-01", "2027-01-01") == ["2027-01-01"]
    assert _days("2027-01-01", None, "none", "2027-01-02", "2027-12-31") == []


def test_multi_day_occurrence_overlapping_window_start_is_kept_with_its_length():
    pairs = occurrence_dates("2027-01-30", "2027-02-01", "weekly", "2027-02-07", "2027-02-07")
    assert pairs == [(date(2027, 2, 6), date(2027, 2, 8))]


def test_far_future_window_is_cheap_and_correct():
    assert _days("2000-01-03", None, "daily", "2099-12-31", "2099-12-31") == ["2099-12-31"]
    assert _days("2000-01-31", None, "monthly", "2099-02-01", "2099-02-28") == ["2099-02-28"]


@pytest.fixture
def world(tmp_path):
    clock = FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    return web, home


def _event(web, title, start, recurrence, **extra):
    created = web.api("POST", "/api/events", {"title": title, "start_date": start, "recurrence": recurrence,
                                              "all_day": True, **extra})
    assert created.status_code == 201, created.get_json()
    return created.get_json()["id"]


def test_month_week_list_views_show_occurrences_linking_to_series(world):
    web, _home = world
    series = _event(web, "Piscine Zoé", "2027-01-06", "weekly")
    once = _event(web, "Dentiste", "2027-02-10", "none")

    month = web.get("/calendrier?vue=mois&date=2027-02-01").data.decode()
    links = re.findall(rf'href="/calendrier/{series}\?occurrence=([0-9-]+)"', month)
    assert links == ["2027-02-03", "2027-02-10", "2027-02-17", "2027-02-24"]
    assert f'href="/calendrier/{once}"' in month
    assert "↻" in month and "(chaque semaine)" in month

    week = web.get("/calendrier?vue=semaine&date=2027-02-17").data.decode()
    assert re.findall(rf'/calendrier/{series}\?occurrence=([0-9-]+)', week) == ["2027-02-17"]

    listing = web.get("/calendrier?vue=liste&date=2027-02-20").data.decode()
    dates = re.findall(rf'/calendrier/{series}\?occurrence=([0-9-]+)', listing)
    assert dates == ["2027-02-24", "2027-03-03", "2027-03-10", "2027-03-17", "2027-03-24", "2027-03-31", "2027-04-07", "2027-04-14"]
    assert "Chaque semaine" in listing


def test_clicking_occurrence_opens_series_and_edit_is_series_wide(world):
    web, _home = world
    series = _event(web, "Yoga", "2027-02-01", "daily")
    page = web.get(f"/calendrier/{series}?occurrence=2027-02-15").data.decode()
    assert "Occurrence du 15 février 2027" in page
    assert "Les modifications s'appliquent à toute la série." in page
    assert "Modifier la série" in page

    bogus = web.get(f"/calendrier/{series}?occurrence=2027-01-15").data.decode()
    assert "Occurrence du" not in bogus and "Événement récurrent." in bogus

    form = web.get(f"/calendrier/{series}/modifier").data.decode()
    assert '<option value="daily" selected>' in form
    assert "Modifier cet événement modifie toute la série." in form

    web.submit(f"/calendrier/{series}", {
        "title": "Yoga du matin", "start_date": "2027-02-01", "end_date": "", "recurrence": "daily",
        "timezone": "Europe/Berlin", "notes": "", "responsible_id": "",
    })
    item = web.api("GET", f"/api/events/{series}").get_json()
    assert item["title"] == "Yoga du matin" and item["recurrence"] == "daily" and item["start_date"] == "2027-02-01"
    month = web.get("/calendrier?vue=mois&date=2027-02-01").data.decode()
    assert month.count("Yoga du matin") == 28


def test_today_card_lists_upcoming_occurrences(world):
    web, _home = world
    series = _event(web, "Cours de piano", "2026-11-03", "weekly")
    page = web.get("/").data.decode()
    links = re.findall(rf'/calendrier/{series}\?occurrence=([0-9-]+)', page)
    assert links == ["2027-02-23", "2027-03-02"]
    assert "Chaque semaine" in page


def test_member_and_title_filters_apply_to_occurrences(world):
    web, _home = world
    me = web.api("GET", "/api/people").get_json()["items"][0]
    _event(web, "Sport Roger", "2027-02-01", "weekly", responsible_id=me["id"])
    _event(web, "Sport partagé", "2027-02-02", "weekly")
    mine = web.get(f"/calendrier?vue=mois&date=2027-02-01&membre={me['id']}").data.decode()
    assert "Sport Roger" in mine and "Sport partagé" not in mine
    found = web.get("/calendrier?vue=liste&date=2027-02-01&q=partag").data.decode()
    assert "Sport partagé" in found and "Sport Roger" not in found


def test_occurrences_stay_in_their_household(world):
    web, _home = world
    series = _event(web, "Secret hebdo foyer 1", "2027-01-04", "weekly")
    web.submit("/foyers/creer", {"household_name": "Chalet", "timezone": "Europe/Zurich", "display_name": "Roger chalet"})
    for path in ("/", "/calendrier?vue=mois&date=2027-02-01", "/calendrier?vue=liste&date=2027-02-01"):
        assert "Secret hebdo foyer 1" not in web.get(path).data.decode()
    assert web.get(f"/calendrier/{series}?occurrence=2027-02-15").status_code == 404
    other = _event(web, "Chalet mensuel", "2027-01-31", "monthly")
    month = web.get("/calendrier?vue=mois&date=2027-02-01").data.decode()
    assert re.findall(rf'/calendrier/{other}\?occurrence=([0-9-]+)', month) == ["2027-02-28"]


def test_disabled_module_and_archived_series_show_nothing(world):
    web, home = world
    series = _event(web, "Réunion mensuelle", "2027-01-15", "monthly")
    conn = connect(home / "data" / "metadata.sqlite")
    conn.execute("UPDATE calendar_event SET archived=1 WHERE id=?", (series,))
    conn.commit()
    assert "Réunion mensuelle" not in web.get("/calendrier?vue=mois&date=2027-02-01").data.decode()
    assert "Réunion mensuelle" not in web.get("/").data.decode()
    conn.execute("UPDATE calendar_event SET archived=0 WHERE id=?", (series,))
    conn.execute("UPDATE module_setting SET enabled=0 WHERE module_key='calendrier'")
    conn.commit()
    conn.close()
    assert "Réunion mensuelle" not in web.get("/").data.decode()
    assert web.get("/calendrier").status_code in (403, 404)
