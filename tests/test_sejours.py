"""Séjours : page du foyer, enveloppe, dépenses privées, affichage agenda."""

import uuid
from datetime import datetime, timezone

import pytest

from app import Ctx, create_app
from app.clock import FrozenClock
from app.db import connect, init_db
from app.errors import AppError
from app.services import agenda, sejours
from tests.test_flows import PASSWORD, Web


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 7, 1, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def world(tmp_path, clock):
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    return web, app, home, clock


def _add_sam(web):
    web.get("/personnes/ajouter")
    created = web.submit("/personnes", {
        "display_name": "Sam",
        "relationship": "coloc",
        "with_account": "oui",
        "username": "sam",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    }, follow=False)
    assert created.status_code in {302, 303}
    people = web.api("GET", "/api/people").get_json()["items"]
    roger = next(person for person in people if person["display_name"] == "Roger")
    sam = next(person for person in people if person["display_name"] == "Sam")
    return roger, sam


def _create(web, **extra):
    payload = {
        "title": "Bretagne",
        "destination": "Saint-Malo",
        "start_date": "2027-07-10",
        "end_date": "2027-07-12",
        "currency": "CHF",
        "envelope_transport": "200,00",
        "participant_ids": extra.pop("participant_ids", []),
    }
    payload.update(extra)
    return web.submit("/sejours", payload, follow=False)


def _id_from(response):
    location = response.headers["Location"]
    return int(location.rstrip("/").split("/")[-1])


def _day_titles(cal):
    found = {}
    if cal["weeks"]:
        for week in cal["weeks"]:
            for day in week:
                found[day["iso"]] = [entry["title"] for entry in day["entries"]]
    else:
        for group in cal["groups"]:
            found[group["iso"]] = [entry["title"] for entry in group["entries"]]
    return found


def test_migration_sejour(tmp_path):
    db_path = tmp_path / "metadata.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sejour", "sejour_participant", "sejour_envelope_line", "sejour_expense"} <= tables
    conn.close()


def test_creation_membre_non_participant_et_autre_foyer(world):
    web, app, home, clock = world
    roger, sam = _add_sam(web)
    agenda_nav = web.get("/calendrier").data.decode()
    assert 'href="/sejours"' in agenda_nav
    assert "Séjours" in agenda_nav

    refused = _create(web, end_date="2027-07-01", participant_ids=[str(roger["id"])])
    assert refused.status_code == 400
    assert "fin précède" in refused.data.decode()

    created = _create(web, participant_ids=[str(roger["id"])])
    assert created.status_code == 302, created.data.decode()[:400]
    sejour_id = _id_from(created)

    conn = connect(home / "data" / "metadata.sqlite")
    minor = conn.execute(
        "SELECT amount_minor FROM sejour_envelope_line WHERE line_key='transport'"
    ).fetchone()[0]
    assert minor == 20000
    assert conn.execute("SELECT typeof(amount_minor) FROM sejour_envelope_line").fetchone()[0] == "integer"
    assert conn.execute("SELECT COUNT(*) FROM calendar_event").fetchone()[0] == 0

    web.login("sam")
    page = web.get(f"/sejours/{sejour_id}")
    assert page.status_code == 200
    body = page.data.decode()
    assert "Bretagne" in body and "200,00 CHF" in body
    participants = body.split("Participants", 1)[1].split("</dd>", 1)[0]
    assert "Roger" in participants and "Sam" not in participants
    assert "Saint-Malo" in body

    moment = "2027-07-01T08:00:00Z"
    conn.execute(
        "INSERT INTO household(name, timezone, created_at) VALUES('Chalet','Europe/Zurich',?)",
        (moment,),
    )
    other_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO person(household_id, display_name, is_principal, active, can_view_index, created_at)
           VALUES(?, 'Alex', 1, 1, 1, ?)""",
        (other_id, moment),
    )
    alex_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO sejour(
             household_id, public_id, title, destination, start_date, end_date, currency,
             created_by, archived, created_at, updated_at
           ) VALUES(?,?,?,?,?,?,?,?,0,?,?)""",
        (
            other_id, str(uuid.uuid4()), "Séjour du chalet", "Annecy",
            "2027-07-10", "2027-07-12", "EUR", alex_id, moment, moment,
        ),
    )
    foreign_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    listing = web.get("/sejours").data.decode()
    assert "Séjour du chalet" not in listing and "Annecy" not in listing
    assert web.get(f"/sejours/{foreign_id}").status_code == 404
    agenda_page = web.get("/calendrier?vue=mois&date=2027-07-01").data.decode()
    assert "Séjour du chalet" not in agenda_page

    other = Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"], household_id=other_id)
    alex = {"id": alex_id, "is_principal": True, "can_view_index": True, "active": True}
    with pytest.raises(AppError) as exc:
        sejours.get_sejour(other, alex, sejour_id)
    assert exc.value.status == 404
    seen = sejours.list_sejours(other, alex)["items"]
    assert [item["title"] for item in seen] == ["Séjour du chalet"]
    conn.close()


def test_enveloppe_reste_et_depense_privee_non_divulguee(world):
    web, _app, home, _clock = world
    roger, sam = _add_sam(web)
    created = _create(web, participant_ids=[str(roger["id"])])
    sejour_id = _id_from(created)
    web.get(f"/sejours/{sejour_id}")
    categories = web.api("GET", "/api/finance/categories?kind=expense").get_json()["items"]
    transport = next(item for item in categories if item["name"] == "Transport")

    shared = web.submit(f"/sejours/{sejour_id}/depense", {
        "label": "Péage",
        "amount": "30,00",
        "txn_date": "2027-07-10",
        "category_id": str(transport["id"]),
        "line_key": "transport",
        "payer_id": str(roger["id"]),
        "split_person_ids": [str(roger["id"]), str(sam["id"])],
        "visibility": "household",
    })
    assert shared.status_code == 200, shared.data.decode()[:500]
    assert "Péage" in shared.data.decode()
    assert "30,00 CHF" in shared.data.decode()
    assert "170,00 CHF" in shared.data.decode()

    private = web.submit(f"/sejours/{sejour_id}/depense", {
        "label": "Bracelet secret",
        "amount": "17,13",
        "txn_date": "2027-07-11",
        "category_id": str(transport["id"]),
        "line_key": "transport",
        "payer_id": str(roger["id"]),
        "split_person_ids": [str(roger["id"])],
        "visibility": "private",
    })
    roger_page = private.data.decode()
    assert private.status_code == 200, roger_page[:500]
    assert "Bracelet secret" in roger_page
    assert "17,13 CHF" in roger_page
    assert "47,13 CHF" in roger_page
    assert "152,87 CHF" in roger_page

    accounts = web.api("GET", "/api/finance/accounts").get_json()["items"]
    eur = next(account for account in accounts if account["currency"] == "EUR")
    foreign = web.api("POST", "/api/finance/transactions", {
        "kind": "expense",
        "amount": "88,88",
        "currency": "EUR",
        "txn_date": "2027-07-11",
        "label": "Musée euro",
        "category_id": transport["id"],
        "ledger_account_id": eur["id"],
        "payer_id": roger["id"],
        "split_method": "equal",
        "split_person_ids": [roger["id"]],
        "visibility": "household",
    })
    assert foreign.status_code == 201, foreign.get_json()
    mismatch = web.submit(f"/sejours/{sejour_id}/rattacher", {
        "transaction_id": str(foreign.get_json()["id"]),
        "line_key": "transport",
    })
    assert mismatch.status_code == 400
    mismatch_body = mismatch.data.decode()
    assert "pas de conversion" in mismatch_body
    assert "Musée euro" not in mismatch_body
    assert "88,88" not in mismatch_body
    assert "152,87 CHF" in mismatch_body

    web.login("sam")
    sam_page = web.get(f"/sejours/{sejour_id}")
    assert sam_page.status_code == 200
    body = sam_page.data.decode()
    assert "Bretagne" in body and "Saint-Malo" in body
    assert "Péage" in body
    assert "30,00 CHF" in body
    assert "170,00 CHF" in body
    assert "200,00 CHF" in body
    for secret in ("Bracelet secret", "17,13", "47,13", "152,87", "Musée euro", "88,88"):
        assert secret not in body
    conn = connect(home / "data" / "metadata.sqlite")
    assert conn.execute(
        "SELECT COUNT(*) FROM sejour_expense WHERE archived=0"
    ).fetchone()[0] == 2
    conn.close()


def test_agenda_montre_le_sejour_dans_les_dates_seulement(world):
    web, app, home, clock = world
    roger, sam = _add_sam(web)
    created = _create(web, participant_ids=[str(roger["id"])])
    sejour_id = _id_from(created)

    month = web.get("/calendrier?vue=mois&date=2027-07-01").data.decode()
    assert f'href="/sejours/{sejour_id}"' in month
    assert "Bretagne" in month
    assert "Bretagne" not in web.get("/calendrier?vue=mois&date=2027-06-01").data.decode()
    assert "Bretagne" in web.get("/calendrier?vue=semaine&date=2027-07-10").data.decode()
    assert "Bretagne" not in web.get("/calendrier?vue=semaine&date=2027-08-02").data.decode()
    listing = web.get("/calendrier?vue=liste&date=2027-07-10").data.decode()
    assert "Bretagne" in listing and "Séjour" in listing
    assert "Bretagne" not in web.get("/calendrier?vue=liste&date=2027-07-13").data.decode()

    conn = connect(home / "data" / "metadata.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM calendar_event").fetchone()[0] == 0
    ctx = Ctx(conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"], household_id=1)
    actor = {"id": roger["id"], "can_view_index": True, "is_principal": True, "active": True}

    def titles(view, anchor, member_id=None):
        cal = agenda.build(ctx, actor, view=view, anchor=anchor, member_id=member_id)
        return _day_titles(cal), cal["count"]

    month_days, count = titles("mois", "2027-07-01")
    assert count == 1
    for day in ("2027-07-10", "2027-07-11", "2027-07-12"):
        assert "Bretagne" in month_days[day]
    for day in ("2027-07-09", "2027-07-13"):
        assert "Bretagne" not in month_days[day]

    week_days, _count = titles("semaine", "2027-07-12")
    assert "Bretagne" in week_days["2027-07-12"]
    assert "Bretagne" not in week_days["2027-07-13"]

    list_days, _count = titles("liste", "2027-07-09")
    for day in ("2027-07-10", "2027-07-11", "2027-07-12"):
        assert "Bretagne" in list_days[day]
    assert "2027-07-09" not in list_days or "Bretagne" not in list_days["2027-07-09"]
    assert "2027-07-13" not in list_days or "Bretagne" not in list_days["2027-07-13"]

    hidden, _count = titles("mois", "2027-07-01", member_id=sam["id"])
    assert all("Bretagne" not in names for names in hidden.values())
    shown, _count = titles("mois", "2027-07-01", member_id=roger["id"])
    assert "Bretagne" in shown["2027-07-11"]
    conn.close()
