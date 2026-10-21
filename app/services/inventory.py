"""Inventaire : lieux, biens, garanties, maintenance, historique et liens."""

import csv
import io
import uuid
from ..tenancy import hh

from ..audit import audit
from ..clock import iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..money import format_minor, parse_amount_to_minor, require_currency
from ..validate import date_value, text_value
from . import events as events_svc
from . import links as links_svc
from .modules import require_module
from .people import list_active_members

CONDITIONS = frozenset({"new", "good", "fair", "poor", "broken", "disposed"})
CONDITION_LABEL = {
    "new": "Neuf",
    "good": "Bon",
    "fair": "Correct",
    "poor": "Usé",
    "broken": "En panne",
    "disposed": "Cédé / sorti",
}


def _require(ctx):
    require_module(ctx, "inventaire")
    return require_household(ctx.conn, hh(ctx))


def _active_person(ctx, person_id):
    row = ctx.conn.execute(
        f'SELECT id, display_name, active FROM person WHERE id=? AND household_id={hh(ctx)}',
        (person_id,),
    ).fetchone()
    if row is None or not row["active"]:
        raise AppError(400, "validation", "Personne inconnue ou inactive.")
    return row


def _owners_of(conn, item_id):
    return conn.execute(
        """SELECT p.id, p.display_name FROM inventory_item_owner o
           JOIN person p ON p.id=o.person_id
           WHERE o.item_id=? ORDER BY p.id""",
        (item_id,),
    ).fetchall()


def _can_see_item(ctx, person, row):
    if person.get("is_principal"):
        return True
    if row["visibility"] == "household":
        return True
    if row["created_by"] == person["id"]:
        return True
    owners = _owners_of(ctx.conn, row["id"])
    return any(owner["id"] == person["id"] for owner in owners)


def _money_fields(data, price_key, currency_key, label):
    raw = data.get(price_key)
    cur = data.get(currency_key)
    if raw in (None, "") and cur in (None, ""):
        return None, None
    if raw in (None, ""):
        raise AppError(400, "validation", f"{label} incomplet.", {price_key: f"{label} requis."})
    if isinstance(raw, int) and raw == 0:
        minor = 0
    elif str(raw).strip() in {"0", "0.00", "0,00"}:
        minor = 0
    else:
        minor = parse_amount_to_minor(raw, field=price_key, label=label)
    currency = require_currency(cur or "CHF")
    return minor, currency


def list_places(ctx, person):
    _require(ctx)
    rows = ctx.conn.execute(
        f"""SELECT id, public_id, name, notes FROM inventory_place
           WHERE household_id={hh(ctx)} AND archived=0 ORDER BY name, id"""
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


def create_place(ctx, person, data):
    _require(ctx)
    name = text_value(data.get("name"), "name", 120, required=True, label="Le lieu")
    notes = text_value(data.get("notes", ""), "notes", 2000, required=False, label="La note")
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO inventory_place(household_id, public_id, name, notes, archived, created_at, updated_at)
               VALUES({hh(ctx)},?,?,?,0,?,?)""",
            (str(uuid.uuid4()), name, notes, moment, moment),
        )
        place_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(ctx.home, ctx.clock, "inventory_place_create", "ok", person["id"], "inventory_place", place_id)
    return place_id


def _item_public(ctx, row):
    owners = _owners_of(ctx.conn, row["id"])
    warranties = ctx.conn.execute(
        """SELECT id, label, starts_on, ends_on, provider, notes, calendar_event_id, created_at
           FROM inventory_warranty WHERE item_id=? ORDER BY ends_on IS NULL, ends_on, id""",
        (row["id"],),
    ).fetchall()
    maintenances = ctx.conn.execute(
        """SELECT id, performed_on, label, cost_minor, currency, notes, created_by, created_at
           FROM inventory_maintenance WHERE item_id=? ORDER BY performed_on DESC, id DESC""",
        (row["id"],),
    ).fetchall()
    history = ctx.conn.execute(
        """SELECT h.id, h.event_type, h.body, h.actor_id, p.display_name AS actor_name, h.created_at
           FROM inventory_history h JOIN person p ON p.id=h.actor_id
           WHERE h.item_id=? ORDER BY h.id DESC LIMIT 50""",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "public_id": row["public_id"],
        "name": row["name"],
        "category": row["category"],
        "place_id": row["place_id"],
        "place_name": row["place_name"] if "place_name" in row.keys() else None,
        "condition": row["condition"],
        "condition_label": CONDITION_LABEL.get(row["condition"], row["condition"]),
        "serial_number": row["serial_number"],
        "purchase_date": row["purchase_date"],
        "purchase_price_minor": row["purchase_price_minor"],
        "purchase_currency": row["purchase_currency"],
        "purchase_price_label": (
            format_minor(row["purchase_price_minor"], row["purchase_currency"])
            if row["purchase_price_minor"] is not None else None
        ),
        "estimated_value_minor": row["estimated_value_minor"],
        "estimated_currency": row["estimated_currency"],
        "estimated_value_label": (
            format_minor(row["estimated_value_minor"], row["estimated_currency"])
            if row["estimated_value_minor"] is not None else None
        ),
        "notes": row["notes"],
        "visibility": row["visibility"],
        "purchase_transaction_id": row["purchase_transaction_id"],
        "invoice_file_id": row["invoice_file_id"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "owners": [{"id": o["id"], "display_name": o["display_name"]} for o in owners],
        "warranties": [dict(w) for w in warranties],
        "maintenances": [
            {
                **dict(m),
                "cost_label": format_minor(m["cost_minor"], m["currency"]) if m["cost_minor"] is not None else None,
            }
            for m in maintenances
        ],
        "history": [dict(h) for h in history],
    }


ITEM_SELECT = """
SELECT i.id, i.public_id, i.name, i.category, i.place_id, p.name AS place_name,
       i.condition, i.serial_number, i.purchase_date, i.purchase_price_minor, i.purchase_currency,
       i.estimated_value_minor, i.estimated_currency, i.notes, i.visibility,
       i.purchase_transaction_id, i.invoice_file_id, i.created_by, i.created_at, i.updated_at, i.archived
FROM inventory_item i
LEFT JOIN inventory_place p ON p.id=i.place_id
"""


def list_items(ctx, person, *, q="", place_id=None, category="", page=1):
    _require(ctx)
    where = [f'i.household_id={hh(ctx)}', "i.archived=0"]
    params = {}
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(i.name LIKE :q ESCAPE '\\' OR i.category LIKE :q ESCAPE '\\' OR i.serial_number LIKE :q ESCAPE '\\')")
        params["q"] = f"%{escaped}%"
    if place_id not in (None, "", 0, "0"):
        where.append("i.place_id=:place_id")
        params["place_id"] = int(place_id)
    if category:
        where.append("i.category=:category")
        params["category"] = category.strip()
    rows = ctx.conn.execute(
        f"{ITEM_SELECT} WHERE {' AND '.join(where)} ORDER BY i.name, i.id LIMIT 300",
        params,
    ).fetchall()
    items = [_item_public(ctx, row) for row in rows if _can_see_item(ctx, person, row)]
    page = max(1, int(page or 1))
    start = (page - 1) * 50
    return {"items": items[start:start + 50], "page": page, "page_size": 50, "total": len(items)}


def get_item(ctx, person, item_id):
    _require(ctx)
    row = ctx.conn.execute(f"{ITEM_SELECT} WHERE i.id=? AND i.household_id={hh(ctx)}", (item_id,)).fetchone()
    if row is None or row["archived"]:
        raise AppError(404, "not_found", "Bien introuvable.")
    if not _can_see_item(ctx, person, row):
        raise AppError(404, "not_found", "Bien introuvable.")
    return _item_public(ctx, row)


def _parse_owner_ids(data):
    raw = data.get("owner_ids") or data.get("owners") or []
    if isinstance(raw, str):
        raw = [part for part in raw.replace(";", ",").split(",") if part.strip()]
    return [int(value) for value in raw]


def _history(ctx, item_id, actor_id, event_type, body, moment):
    ctx.conn.execute(
        """INSERT INTO inventory_history(item_id, event_type, body, actor_id, created_at)
           VALUES(?,?,?,?,?)""",
        (item_id, event_type, body, actor_id, moment),
    )


def create_item(ctx, person, data):
    _require(ctx)
    name = text_value(data.get("name"), "name", 200, required=True, label="Le nom")
    category = text_value(data.get("category", ""), "category", 120, required=False, label="La catégorie")
    notes = text_value(data.get("notes", ""), "notes", 4000, required=False, label="La note")
    serial = text_value(data.get("serial_number", ""), "serial_number", 120, required=False, label="Le numéro de série")
    condition = (data.get("condition") or "good").strip()
    if condition not in CONDITIONS:
        raise AppError(400, "validation", "État inconnu.", {"condition": "État inconnu."})
    visibility = (data.get("visibility") or "household").strip()
    if visibility not in {"household", "private"}:
        raise AppError(400, "validation", "Visibilité inconnue.", {"visibility": "Visibilité inconnue."})
    purchase_date = date_value(data.get("purchase_date"), key="purchase_date", label="La date d'achat")
    price_minor, price_currency = _money_fields(data, "purchase_price", "purchase_currency", "Le prix d'achat")
    # also accept purchase_price_minor
    if data.get("purchase_price_minor") not in (None, "") and price_minor is None:
        price_minor = int(data["purchase_price_minor"])
        price_currency = require_currency(data.get("purchase_currency") or "CHF")
    value_minor, value_currency = _money_fields(data, "estimated_value", "estimated_currency", "La valeur")
    if data.get("estimated_value_minor") not in (None, "") and value_minor is None:
        value_minor = int(data["estimated_value_minor"])
        value_currency = require_currency(data.get("estimated_currency") or "CHF")

    place_id = data.get("place_id")
    if place_id in (None, "", 0, "0"):
        place_id = None
    else:
        place_id = int(place_id)
        place = ctx.conn.execute(
            f'SELECT id FROM inventory_place WHERE id=? AND household_id={hh(ctx)} AND archived=0',
            (place_id,),
        ).fetchone()
        if place is None:
            raise AppError(400, "validation", "Lieu inconnu.", {"place_id": "Lieu inconnu."})

    owner_ids = _parse_owner_ids(data)
    if not owner_ids:
        owner_ids = [person["id"]]
    for owner_id in owner_ids:
        _active_person(ctx, owner_id)

    purchase_transaction_id = data.get("purchase_transaction_id")
    if purchase_transaction_id in (None, ""):
        purchase_transaction_id = None
    else:
        purchase_transaction_id = int(purchase_transaction_id)
        txn = ctx.conn.execute(
            f'SELECT id, kind, archived FROM finance_transaction WHERE id=? AND household_id={hh(ctx)}',
            (purchase_transaction_id,),
        ).fetchone()
        if txn is None or txn["archived"] or txn["kind"] not in {"expense", "transfer"}:
            raise AppError(400, "validation", "Transaction d'achat invalide.")

    invoice_file_id = data.get("invoice_file_id")
    if invoice_file_id in (None, ""):
        invoice_file_id = None
    else:
        invoice_file_id = int(invoice_file_id)
        if not links_svc.can_see_object(ctx, person, "stored_file", invoice_file_id):
            raise AppError(404, "not_found", "Facture introuvable.")

    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO inventory_item(
                 household_id, public_id, name, category, place_id, condition, serial_number,
                 purchase_date, purchase_price_minor, purchase_currency,
                 estimated_value_minor, estimated_currency, notes, visibility,
                 purchase_transaction_id, invoice_file_id, created_by, archived, created_at, updated_at
               ) VALUES({hh(ctx)},?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (
                str(uuid.uuid4()), name, category, place_id, condition, serial,
                purchase_date, price_minor, price_currency, value_minor, value_currency,
                notes, visibility, purchase_transaction_id, invoice_file_id,
                person["id"], moment, moment,
            ),
        )
        item_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for owner_id in owner_ids:
            ctx.conn.execute(
                "INSERT INTO inventory_item_owner(item_id, person_id) VALUES(?,?)",
                (item_id, owner_id),
            )
        _history(ctx, item_id, person["id"], "created", f"Bien créé : {name}", moment)
        if purchase_transaction_id:
            _history(ctx, item_id, person["id"], "linked", f"Lié à la transaction #{purchase_transaction_id}", moment)
        if invoice_file_id:
            _history(ctx, item_id, person["id"], "linked", f"Facture #{invoice_file_id} associée", moment)
    # liens typés hors write_tx imbriqué — après commit
    if purchase_transaction_id:
        try:
            links_svc.create_link(ctx, person, {
                "source_type": "inventory_item",
                "source_id": item_id,
                "target_type": "finance_transaction",
                "target_id": purchase_transaction_id,
                "relation_type": "purchased_via",
            })
        except AppError:
            pass
    if invoice_file_id:
        try:
            links_svc.create_link(ctx, person, {
                "source_type": "inventory_item",
                "source_id": item_id,
                "target_type": "stored_file",
                "target_id": invoice_file_id,
                "relation_type": "documents",
            })
        except AppError:
            pass
    audit(ctx.home, ctx.clock, "inventory_item_create", "ok", person["id"], "inventory_item", item_id)
    return item_id


def update_item(ctx, person, item_id, data):
    existing = get_item(ctx, person, item_id)
    name = text_value(data.get("name", existing["name"]), "name", 200, required=True, label="Le nom")
    category = text_value(data.get("category", existing["category"]), "category", 120, required=False, label="La catégorie")
    notes = text_value(data.get("notes", existing["notes"]), "notes", 4000, required=False, label="La note")
    serial = text_value(data.get("serial_number", existing["serial_number"]), "serial_number", 120, required=False, label="Le numéro")
    condition = (data.get("condition") or existing["condition"]).strip()
    if condition not in CONDITIONS:
        raise AppError(400, "validation", "État inconnu.", {"condition": "État inconnu."})
    visibility = (data.get("visibility") or existing["visibility"]).strip()
    if visibility not in {"household", "private"}:
        raise AppError(400, "validation", "Visibilité inconnue.")

    place_id = data.get("place_id", existing["place_id"])
    if place_id in (None, "", 0, "0"):
        place_id = None
    else:
        place_id = int(place_id)

    purchase_date = existing["purchase_date"]
    if "purchase_date" in data:
        purchase_date = date_value(data.get("purchase_date"), key="purchase_date", label="La date d'achat")

    price_minor = existing["purchase_price_minor"]
    price_currency = existing["purchase_currency"]
    if "purchase_price" in data or "purchase_price_minor" in data or "purchase_currency" in data:
        merged = {
            "purchase_price": data.get("purchase_price", data.get("purchase_price_minor")),
            "purchase_currency": data.get("purchase_currency", price_currency or "CHF"),
        }
        if merged["purchase_price"] in (None, ""):
            price_minor, price_currency = None, None
        else:
            price_minor, price_currency = _money_fields(merged, "purchase_price", "purchase_currency", "Le prix d'achat")

    value_minor = existing["estimated_value_minor"]
    value_currency = existing["estimated_currency"]
    if "estimated_value" in data or "estimated_value_minor" in data or "estimated_currency" in data:
        merged = {
            "estimated_value": data.get("estimated_value", data.get("estimated_value_minor")),
            "estimated_currency": data.get("estimated_currency", value_currency or "CHF"),
        }
        if merged["estimated_value"] in (None, ""):
            value_minor, value_currency = None, None
        else:
            value_minor, value_currency = _money_fields(merged, "estimated_value", "estimated_currency", "La valeur")

    owner_ids = _parse_owner_ids(data) if ("owner_ids" in data or "owners" in data) else [o["id"] for o in existing["owners"]]
    if not owner_ids:
        owner_ids = [person["id"]]
    for owner_id in owner_ids:
        _active_person(ctx, owner_id)

    moment = iso_utc(ctx.clock.now())
    event_type = "updated"
    body = "Bien mis à jour"
    if condition != existing["condition"]:
        event_type = "condition_changed"
        body = f"État : {CONDITION_LABEL.get(existing['condition'])} → {CONDITION_LABEL.get(condition)}"
        if condition == "disposed":
            event_type = "disposed"
            body = "Bien marqué comme cédé / sorti"
    if set(owner_ids) != {o["id"] for o in existing["owners"]}:
        event_type = "transferred"
        body = "Propriétaires mis à jour"

    with write_tx(ctx):
        ctx.conn.execute(
            """UPDATE inventory_item SET
                 name=?, category=?, place_id=?, condition=?, serial_number=?,
                 purchase_date=?, purchase_price_minor=?, purchase_currency=?,
                 estimated_value_minor=?, estimated_currency=?, notes=?, visibility=?,
                 updated_at=?
               WHERE id=?""",
            (
                name, category, place_id, condition, serial,
                purchase_date, price_minor, price_currency,
                value_minor, value_currency, notes, visibility,
                moment, item_id,
            ),
        )
        ctx.conn.execute("DELETE FROM inventory_item_owner WHERE item_id=?", (item_id,))
        for owner_id in owner_ids:
            ctx.conn.execute(
                "INSERT INTO inventory_item_owner(item_id, person_id) VALUES(?,?)",
                (item_id, owner_id),
            )
        _history(ctx, item_id, person["id"], event_type, body, moment)
    audit(ctx.home, ctx.clock, "inventory_item_update", event_type, person["id"], "inventory_item", item_id)
    return get_item(ctx, person, item_id)


def link_invoice(ctx, person, item_id, file_id):
    get_item(ctx, person, item_id)
    file_id = int(file_id)
    if not links_svc.can_see_object(ctx, person, "stored_file", file_id):
        raise AppError(404, "not_found", "Facture introuvable.")
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            "UPDATE inventory_item SET invoice_file_id=?, updated_at=? WHERE id=?",
            (file_id, moment, item_id),
        )
        _history(ctx, item_id, person["id"], "linked", f"Facture #{file_id} associée", moment)
    links_svc.create_link(ctx, person, {
        "source_type": "inventory_item",
        "source_id": item_id,
        "target_type": "stored_file",
        "target_id": file_id,
        "relation_type": "documents",
    })
    return get_item(ctx, person, item_id)


def link_purchase(ctx, person, item_id, transaction_id):
    get_item(ctx, person, item_id)
    transaction_id = int(transaction_id)
    txn = ctx.conn.execute(
        f'SELECT id, kind, archived FROM finance_transaction WHERE id=? AND household_id={hh(ctx)}',
        (transaction_id,),
    ).fetchone()
    if txn is None or txn["archived"]:
        raise AppError(404, "not_found", "Transaction introuvable.")
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            "UPDATE inventory_item SET purchase_transaction_id=?, updated_at=? WHERE id=?",
            (transaction_id, moment, item_id),
        )
        _history(ctx, item_id, person["id"], "linked", f"Achat transaction #{transaction_id}", moment)
    links_svc.create_link(ctx, person, {
        "source_type": "inventory_item",
        "source_id": item_id,
        "target_type": "finance_transaction",
        "target_id": transaction_id,
        "relation_type": "purchased_via",
    })
    return get_item(ctx, person, item_id)


def add_warranty(ctx, person, item_id, data):
    item = get_item(ctx, person, item_id)
    label = text_value(data.get("label"), "label", 200, required=True, label="Le libellé")
    provider = text_value(data.get("provider", ""), "provider", 200, required=False, label="Le prestataire")
    notes = text_value(data.get("notes", ""), "notes", 2000, required=False, label="La note")
    starts_on = date_value(data.get("starts_on"), key="starts_on", label="Le début")
    ends_on = date_value(data.get("ends_on"), key="ends_on", label="La fin")
    if ends_on and starts_on and ends_on < starts_on:
        raise AppError(400, "validation", "La fin précède le début.", {"ends_on": "La fin précède le début."})

    create_deadline = data.get("create_deadline") in (True, 1, "1", "true", "on", "oui")
    calendar_event_id = None
    moment = iso_utc(ctx.clock.now())

    if create_deadline and ends_on:
        household = require_household(ctx.conn, hh(ctx))
        calendar_event_id = events_svc.create_event(ctx, person, {
            "title": f"Garantie : {item['name']} — {label}",
            "notes": f"Échéance de garantie du bien « {item['name']} ».",
            "start_date": ends_on,
            "all_day": True,
            "timezone": household["timezone"],
            "recurrence": "none",
            "responsible_id": person["id"],
        })

    with write_tx(ctx):
        ctx.conn.execute(
            """INSERT INTO inventory_warranty(
                 item_id, label, starts_on, ends_on, provider, notes, calendar_event_id, created_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (item_id, label, starts_on, ends_on, provider, notes, calendar_event_id, moment),
        )
        warranty_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _history(ctx, item_id, person["id"], "warranty", f"Garantie ajoutée : {label}", moment)
    if calendar_event_id:
        try:
            links_svc.create_link(ctx, person, {
                "source_type": "inventory_item",
                "source_id": item_id,
                "target_type": "calendar_event",
                "target_id": calendar_event_id,
                "relation_type": "warranty_deadline",
            })
        except AppError:
            pass
    audit(ctx.home, ctx.clock, "inventory_warranty", "ok", person["id"], "inventory_warranty", warranty_id)
    return get_item(ctx, person, item_id)


def add_maintenance(ctx, person, item_id, data):
    get_item(ctx, person, item_id)
    label = text_value(data.get("label"), "label", 200, required=True, label="Le libellé")
    notes = text_value(data.get("notes", ""), "notes", 2000, required=False, label="La note")
    performed_on = date_value(data.get("performed_on"), key="performed_on", label="La date")
    if not performed_on:
        raise AppError(400, "validation", "Date requise.", {"performed_on": "Date requise."})
    cost_minor, currency = None, None
    if data.get("cost") not in (None, "") or data.get("cost_minor") not in (None, ""):
        cost_minor, currency = _money_fields(
            {"estimated_value": data.get("cost", data.get("cost_minor")), "estimated_currency": data.get("currency") or "CHF"},
            "estimated_value",
            "estimated_currency",
            "Le coût",
        )
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            """INSERT INTO inventory_maintenance(
                 item_id, performed_on, label, cost_minor, currency, notes, created_by, created_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (item_id, performed_on, label, cost_minor, currency, notes, person["id"], moment),
        )
        maint_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _history(ctx, item_id, person["id"], "maintenance", f"Maintenance : {label}", moment)
    audit(ctx.home, ctx.clock, "inventory_maintenance", "ok", person["id"], "inventory_maintenance", maint_id)
    return get_item(ctx, person, item_id)


def upcoming_warranties(ctx, person, *, within_days=90, limit=20):
    _require(ctx)
    household = require_household(ctx.conn, hh(ctx))
    from ..clock import civil_today
    today = civil_today(ctx.clock, household["timezone"]).isoformat()
    rows = ctx.conn.execute(
        f"""SELECT i.id AS item_id, i.name AS item_name, i.visibility, i.created_by,
                  w.id AS warranty_id, w.label, w.ends_on, w.provider
           FROM inventory_warranty w
           JOIN inventory_item i ON i.id=w.item_id
           WHERE i.household_id={hh(ctx)} AND i.archived=0
             AND w.ends_on IS NOT NULL
             AND w.ends_on >= ?
             AND w.ends_on <= date(?, '+' || ? || ' days')
           ORDER BY w.ends_on, i.name
           LIMIT ?""",
        (today, today, int(within_days), int(limit)),
    ).fetchall()
    items = []
    for row in rows:
        if not _can_see_item(ctx, person, {
            "id": row["item_id"],
            "visibility": row["visibility"],
            "created_by": row["created_by"],
        }):
            continue
        items.append({
            "item_id": row["item_id"],
            "item_name": row["item_name"],
            "warranty_id": row["warranty_id"],
            "label": row["label"],
            "ends_on": row["ends_on"],
            "provider": row["provider"],
        })
    return items


def export_csv(ctx, person):
    """Export inventaire visible (séparateur ;, montants en unités mineures)."""
    _require(ctx)
    rows = ctx.conn.execute(
        f"{ITEM_SELECT} WHERE i.household_id={hh(ctx)} AND i.archived=0 ORDER BY i.name, i.id"
    ).fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([
        "name", "category", "place", "condition", "visibility",
        "purchase_date", "purchase_price_minor", "purchase_currency",
        "estimated_value_minor", "estimated_currency", "serial_number", "owners",
    ])
    for row in rows:
        if not _can_see_item(ctx, person, row):
            continue
        public = _item_public(ctx, row)
        owners = ",".join(o["display_name"] for o in public.get("owners") or [])
        writer.writerow([
            public["name"],
            public.get("category") or "",
            public.get("place_name") or "",
            public.get("condition") or "",
            public.get("visibility") or "",
            public.get("purchase_date") or "",
            public.get("purchase_price_minor") if public.get("purchase_price_minor") is not None else "",
            public.get("purchase_currency") or "",
            public.get("estimated_value_minor") if public.get("estimated_value_minor") is not None else "",
            public.get("estimated_currency") or "",
            public.get("serial_number") or "",
            owners,
        ])
    return buffer.getvalue()
