"""Étape C — finances : montants exacts, splits, remboursements, devises, confidentialité."""

from datetime import datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect, init_db
from app.money import format_minor, parse_amount_to_minor, split_equal, split_fixed, split_percent
from app.errors import AppError
from tests.test_flows import HOST, ORIGIN, PASSWORD, Web


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def world(tmp_path, clock):
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    return web, app, home, clock


def test_parse_amount_rejects_float():
    with pytest.raises(AppError):
        parse_amount_to_minor(12.5)
    assert parse_amount_to_minor("12,50") == 1250
    assert parse_amount_to_minor("12.50") == 1250
    assert parse_amount_to_minor(1250) == 1250
    assert format_minor(1250, "CHF") == "12,50 CHF"


def test_split_equal_and_percent_exact_sum():
    shares = split_equal(100, [1, 2, 3])
    assert sum(s["share_minor"] for s in shares) == 100
    assert sorted(s["share_minor"] for s in shares) == [33, 33, 34]

    shares = split_percent(100, [
        {"person_id": 1, "percent": "33.33"},
        {"person_id": 2, "percent": "33.33"},
        {"person_id": 3, "percent": "33.34"},
    ])
    assert sum(s["share_minor"] for s in shares) == 100

    shares = split_fixed(1000, [
        {"person_id": 1, "amount": "6,00"},
        {"person_id": 2, "amount": "4,00"},
    ])
    assert sum(s["share_minor"] for s in shares) == 1000

    with pytest.raises(AppError):
        split_fixed(1000, [{"person_id": 1, "amount": "6,00"}])


def test_migration_to_finances(tmp_path):
    db_path = tmp_path / "metadata.sqlite"
    # start empty via init_db full path
    init_db(db_path)
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 4
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "finance_transaction" in tables
    assert "finance_split" in tables
    conn.close()


def test_expense_split_reimbursement_no_double_count(world):
    web, app, home, clock = world
    # second person
    web.submit("/personnes", {
        "display_name": "Léa",
        "relationship": "conjoint",
        "with_account": "oui",
        "username": "lea",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    })
    people = web.api("GET", "/api/people").get_json()["items"]
    roger = next(p for p in people if p["display_name"] == "Roger")
    lea = next(p for p in people if p["display_name"] == "Léa")

    accounts = web.api("GET", "/api/finance/accounts").get_json()["items"]
    chf = next(a for a in accounts if a["currency"] == "CHF")
    cats = web.api("GET", "/api/finance/categories?kind=expense").get_json()["items"]
    food = next(c for c in cats if c["name"] == "Alimentation")

    # Roger paie 100.00 CHF, split 50/50
    created = web.api("POST", "/api/finance/transactions", {
        "kind": "expense",
        "amount": "100,00",
        "currency": "CHF",
        "txn_date": "2027-02-20",
        "label": "Courses",
        "category_id": food["id"],
        "ledger_account_id": chf["id"],
        "payer_id": roger["id"],
        "split_method": "equal",
        "split_person_ids": [roger["id"], lea["id"]],
        "visibility": "household",
    })
    assert created.status_code == 201, created.get_json()
    txn = created.get_json()
    assert txn["amount_minor"] == 10000
    assert sum(s["share_minor"] for s in txn["splits"]) == 10000
    assert {s["share_minor"] for s in txn["splits"]} == {5000}

    balances = web.api("GET", "/api/finance/balances?currency=CHF").get_json()
    by_id = {item["person_id"]: item["net_minor"] for item in balances["entries"]}
    assert by_id[roger["id"]] == 5000  # à recevoir
    assert by_id[lea["id"]] == -5000  # à verser

    # Budget + spent
    budget = web.api("POST", "/api/finance/budgets", {
        "category_id": food["id"],
        "period": "month",
        "year": 2027,
        "month": 2,
        "amount": "200,00",
        "currency": "CHF",
    })
    assert budget.status_code == 201
    budgets = web.api("GET", "/api/finance/budgets?year=2027&month=2&currency=CHF").get_json()["items"]
    food_budget = next(b for b in budgets if b["category_id"] == food["id"])
    assert food_budget["spent_minor"] == 10000

    # Léa rembourse 50.00 — ne doit PAS augmenter le spent budget
    reimb = web.api("POST", "/api/finance/transactions", {
        "kind": "reimbursement",
        "amount": "50,00",
        "currency": "CHF",
        "txn_date": "2027-02-21",
        "label": "Remboursement courses",
        "ledger_account_id": chf["id"],
        "payer_id": lea["id"],
        "beneficiary_id": roger["id"],
        "settles_transaction_id": txn["id"],
    })
    assert reimb.status_code == 201, reimb.get_json()

    balances2 = web.api("GET", "/api/finance/balances?currency=CHF").get_json()
    by_id2 = {item["person_id"]: item["net_minor"] for item in balances2["entries"]}
    assert by_id2[roger["id"]] == 0
    assert by_id2[lea["id"]] == 0

    budgets2 = web.api("GET", "/api/finance/budgets?year=2027&month=2&currency=CHF").get_json()["items"]
    food_budget2 = next(b for b in budgets2 if b["category_id"] == food["id"])
    assert food_budget2["spent_minor"] == 10000  # inchangé — pas de double comptage

    # Pas de conversion CHF→EUR implicite
    eur = next(a for a in accounts if a["currency"] == "EUR")
    refused = web.api("POST", "/api/finance/transactions", {
        "kind": "expense",
        "amount": "10,00",
        "currency": "CHF",
        "txn_date": "2027-02-20",
        "label": "Mismatch",
        "category_id": food["id"],
        "ledger_account_id": eur["id"],
        "payer_id": roger["id"],
        "split_method": "equal",
        "split_person_ids": [roger["id"]],
    })
    assert refused.status_code == 400


def test_finance_privacy_private_transaction(world):
    web, app, home, clock = world
    web.submit("/personnes", {
        "display_name": "Sam",
        "relationship": "coloc",
        "with_account": "oui",
        "username": "sam",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    })
    accounts = web.api("GET", "/api/finance/accounts").get_json()["items"]
    chf = next(a for a in accounts if a["currency"] == "CHF")
    cats = web.api("GET", "/api/finance/categories?kind=expense").get_json()["items"]
    people = web.api("GET", "/api/people").get_json()["items"]
    roger = next(p for p in people if p["is_principal"])

    private = web.api("POST", "/api/finance/transactions", {
        "kind": "expense",
        "amount": "20,00",
        "currency": "CHF",
        "txn_date": "2027-02-20",
        "label": "Cadeau secret",
        "category_id": cats[0]["id"],
        "ledger_account_id": chf["id"],
        "payer_id": roger["id"],
        "split_method": "equal",
        "split_person_ids": [roger["id"]],
        "visibility": "private",
    })
    assert private.status_code == 201
    txn_id = private.get_json()["id"]

    web.submit("/deconnexion", {}, follow=False)
    web.login("sam")
    listed = web.api("GET", "/api/finance/transactions").get_json()["items"]
    assert all(item["id"] != txn_id for item in listed)
    assert web.api("GET", f"/api/finance/transactions/{txn_id}").status_code == 404


def test_finance_csv_roundtrip(world):
    web, app, home, clock = world
    accounts = web.api("GET", "/api/finance/accounts").get_json()["items"]
    chf = next(a for a in accounts if a["currency"] == "CHF")
    cats = web.api("GET", "/api/finance/categories?kind=expense").get_json()["items"]
    people = web.api("GET", "/api/people").get_json()["items"]
    roger = people[0]

    web.api("POST", "/api/finance/transactions", {
        "kind": "expense",
        "amount_minor": 2550,
        "currency": "CHF",
        "txn_date": "2027-02-18",
        "label": "Pain",
        "category_id": cats[0]["id"],
        "ledger_account_id": chf["id"],
        "payer_id": roger["id"],
        "split_method": "equal",
        "split_person_ids": [roger["id"]],
    })
    exported = web.api("GET", "/api/finance/export.csv")
    assert exported.status_code == 200
    assert b"Pain" in exported.data
    assert b"reimbursement" not in exported.data or b"expense" in exported.data

    page = web.get("/finances")
    assert page.status_code == 200
    assert b"Finances" in page.data
    assert b"Pain" in page.data
