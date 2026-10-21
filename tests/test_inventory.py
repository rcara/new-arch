"""Étape D — inventaire : biens, lieux, garanties, liens, confidentialité."""

from datetime import datetime, timezone

import pytest

from app import create_app
from app.clock import FrozenClock
from app.db import connect, init_db
from tests.test_flows import PASSWORD, Web


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


def test_migration_includes_inventory(tmp_path):
    db_path = tmp_path / "metadata.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 5
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"inventory_item", "inventory_place", "inventory_warranty", "inventory_maintenance"} <= tables
    conn.close()


def test_item_warranty_deadline_and_links(world):
    web, app, home, clock = world
    place = web.api("POST", "/api/inventory/places", {"name": "Cuisine", "notes": ""})
    assert place.status_code == 201
    place_id = place.get_json()["id"]

    # dépense d'achat
    accounts = web.api("GET", "/api/finance/accounts").get_json()["items"]
    chf = next(a for a in accounts if a["currency"] == "CHF")
    cats = web.api("GET", "/api/finance/categories?kind=expense").get_json()["items"]
    people = web.api("GET", "/api/people").get_json()["items"]
    roger = people[0]
    expense = web.api("POST", "/api/finance/transactions", {
        "kind": "expense",
        "amount": "499,00",
        "currency": "CHF",
        "txn_date": "2027-01-10",
        "label": "Achat lave-vaisselle",
        "category_id": cats[0]["id"],
        "ledger_account_id": chf["id"],
        "payer_id": roger["id"],
        "split_method": "equal",
        "split_person_ids": [roger["id"]],
    })
    assert expense.status_code == 201
    txn_id = expense.get_json()["id"]

    created = web.api("POST", "/api/inventory/items", {
        "name": "Lave-vaisselle",
        "category": "Électroménager",
        "place_id": place_id,
        "condition": "new",
        "purchase_date": "2027-01-10",
        "purchase_price": "499,00",
        "purchase_currency": "CHF",
        "owner_ids": [roger["id"]],
        "purchase_transaction_id": txn_id,
        "visibility": "household",
    })
    assert created.status_code == 201, created.get_json()
    item = created.get_json()
    assert item["purchase_price_minor"] == 49900
    assert item["place_name"] == "Cuisine"
    assert any(h["event_type"] == "created" for h in item["history"])

    linked = web.api("GET", f"/api/links?source_type=inventory_item&source_id={item['id']}").get_json()
    assert any(row["target_type"] == "finance_transaction" and row["target_id"] == txn_id for row in linked["items"])

    with_warranty = web.api("POST", f"/api/inventory/items/{item['id']}/warranties", {
        "label": "Garantie 2 ans",
        "starts_on": "2027-01-10",
        "ends_on": "2027-04-01",
        "provider": "Fabricant",
        "create_deadline": True,
    })
    assert with_warranty.status_code == 201
    item2 = with_warranty.get_json()
    assert len(item2["warranties"]) == 1
    assert item2["warranties"][0]["calendar_event_id"] is not None

    upcoming = web.api("GET", "/api/inventory/warranties/upcoming").get_json()["items"]
    assert any(w["item_name"] == "Lave-vaisselle" for w in upcoming)

    events = web.api("GET", "/api/events?from=2027-02-20&to=2027-04-30").get_json()["items"]
    assert any("Garantie" in e["title"] and "Lave-vaisselle" in e["title"] for e in events)

    maint = web.api("POST", f"/api/inventory/items/{item['id']}/maintenances", {
        "label": "Détartrage",
        "performed_on": "2027-02-15",
        "cost": "40,00",
        "currency": "CHF",
    })
    assert maint.status_code == 201
    assert len(maint.get_json()["maintenances"]) == 1

    home_payload = web.api("GET", "/api/home").get_json()
    assert any(w["item_name"] == "Lave-vaisselle" for w in home_payload.get("warranties", []))

    page = web.get("/inventaire")
    assert page.status_code == 200
    assert b"Lave-vaisselle" in page.data


def test_inventory_privacy(world):
    web, app, home, clock = world
    web.submit("/personnes", {
        "display_name": "Sam",
        "relationship": "coloc",
        "with_account": "oui",
        "username": "sam",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    })
    people = web.api("GET", "/api/people").get_json()["items"]
    roger = next(p for p in people if p["is_principal"])

    private = web.api("POST", "/api/inventory/items", {
        "name": "Bijou familial",
        "visibility": "private",
        "owner_ids": [roger["id"]],
        "condition": "good",
    })
    assert private.status_code == 201
    item_id = private.get_json()["id"]

    web.submit("/deconnexion", {}, follow=False)
    web.login("sam")
    listed = web.api("GET", "/api/inventory/items").get_json()["items"]
    assert all(item["id"] != item_id for item in listed)
    assert web.api("GET", f"/api/inventory/items/{item_id}").status_code == 404
    search = web.api("GET", "/api/search?q=Bijou").get_json()
    assert all(item.get("id") != item_id for item in search["items"])


def test_transfer_and_dispose(world):
    web, app, home, clock = world
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

    created = web.api("POST", "/api/inventory/items", {
        "name": "Vélo",
        "owner_ids": [roger["id"]],
        "condition": "good",
    }).get_json()

    updated = web.api("PATCH", f"/api/inventory/items/{created['id']}", {
        "owner_ids": [lea["id"]],
        "condition": "fair",
        "name": "Vélo",
    })
    assert updated.status_code == 200
    body = updated.get_json()
    assert body["owners"][0]["id"] == lea["id"]
    assert any(h["event_type"] == "transferred" for h in body["history"])

    disposed = web.api("PATCH", f"/api/inventory/items/{created['id']}", {
        "condition": "disposed",
        "owner_ids": [lea["id"]],
        "name": "Vélo",
    }).get_json()
    assert disposed["condition"] == "disposed"
    assert any(h["event_type"] == "disposed" for h in disposed["history"])
