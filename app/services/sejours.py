"""Séjours du foyer : visibles par tous les membres, enveloppe par poste.

Les participants disent qui part. Ils ne sont pas une frontière d'accès.
Les dépenses rattachées restent des transactions financières : une dépense
qu'une personne ne peut pas voir est omise de sa liste et de ses totaux.
"""

import sqlite3
import uuid

from ..audit import audit
from ..clock import iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..money import format_minor, parse_amount_to_minor, require_currency
from ..tenancy import hh
from ..validate import date_value, text_value
from .links import can_see_object
from .modules import enabled_keys, require_module

LINES = (
    ("transport", "Transport"),
    ("logement", "Logement"),
    ("repas", "Repas"),
    ("activites", "Activités"),
    ("divers", "Divers"),
)
LINE_LABEL = dict(LINES)
LINE_KEYS = frozenset(LINE_LABEL)


def _active_member(ctx, person_id):
    row = ctx.conn.execute(
        f"SELECT id, active FROM person WHERE id=? AND household_id={hh(ctx)}",
        (person_id,),
    ).fetchone()
    if row is None or not row["active"]:
        raise AppError(
            400, "validation", "Participant inconnu ou inactif.",
            {"participant_ids": "Choisissez un membre actif du foyer."},
        )
    return row


def _optional_minor(value, field, label):
    """Montant d'enveloppe : vide ou zéro acceptés, jamais un flottant."""
    if value is None or value is False:
        return 0
    if isinstance(value, str):
        text = value.strip().replace(" ", "").replace("'", "").replace(",", ".")
        if text in {"", "0", "0.0", "0.00"}:
            return 0
    if isinstance(value, int) and value == 0:
        return 0
    return parse_amount_to_minor(value, field=field, label=label)


def _line_key(value):
    key = (value or "").strip()
    if key not in LINE_KEYS:
        raise AppError(400, "validation", "Poste d'enveloppe inconnu.", {"line_key": "Choisissez un poste."})
    return key


def _participants(ctx, sejour_id):
    rows = ctx.conn.execute(
        """SELECT p.id, p.display_name, p.active
           FROM sejour_participant sp
           JOIN person p ON p.id=sp.person_id
           WHERE sp.sejour_id=?
           ORDER BY p.display_name, p.id""",
        (sejour_id,),
    ).fetchall()
    return [
        {"id": row["id"], "display_name": row["display_name"], "active": bool(row["active"])}
        for row in rows
    ]


def _planned(ctx, sejour_id):
    rows = ctx.conn.execute(
        "SELECT line_key, amount_minor FROM sejour_envelope_line WHERE sejour_id=?",
        (sejour_id,),
    ).fetchall()
    return {row["line_key"]: row["amount_minor"] for row in rows}


def _visible_expenses(ctx, person, sejour_id, currency):
    """Dépenses rattachées que cette personne a le droit de voir. Les autres n'entrent pas dans les totaux."""
    if "finances" not in enabled_keys(ctx):
        return []
    from .finance import get_transaction

    rows = ctx.conn.execute(
        """SELECT id, transaction_id, line_key
           FROM sejour_expense
           WHERE sejour_id=? AND archived=0
           ORDER BY id""",
        (sejour_id,),
    ).fetchall()
    found = []
    for row in rows:
        if row["line_key"] not in LINE_KEYS:
            continue
        if not can_see_object(ctx, person, "finance_transaction", row["transaction_id"]):
            continue
        try:
            txn = get_transaction(ctx, person, row["transaction_id"])
        except AppError as exc:
            if exc.status == 404:
                continue
            raise
        if txn["kind"] != "expense" or txn["currency"] != currency:
            continue
        found.append({
            "id": txn["id"],
            "attachment_id": row["id"],
            "line_key": row["line_key"],
            "line_label": LINE_LABEL[row["line_key"]],
            "label": txn["label"],
            "txn_date": txn["txn_date"],
            "amount_minor": txn["amount_minor"],
            "amount_label": txn["amount_label"],
            "currency": txn["currency"],
            "payer_name": txn["payer_name"],
            "visibility": txn["visibility"],
            "category_name": txn["category_name"],
        })
    found.sort(key=lambda item: (item["txn_date"], item["id"]))
    return found


def _money(currency, planned, expenses):
    spent_by_line = {key: 0 for key in LINE_KEYS}
    for item in expenses:
        spent_by_line[item["line_key"]] += item["amount_minor"]
    lines = []
    for key, label in LINES:
        amount = int(planned.get(key, 0))
        spent = spent_by_line[key]
        lines.append({
            "key": key,
            "label": label,
            "amount_minor": amount,
            "amount_label": format_minor(amount, currency),
            "spent_minor": spent,
            "spent_label": format_minor(spent, currency),
            "remaining_minor": amount - spent,
            "remaining_label": format_minor(amount - spent, currency),
        })
    envelope = sum(line["amount_minor"] for line in lines)
    spent = sum(line["spent_minor"] for line in lines)
    return {
        "lines": lines,
        "envelope_minor": envelope,
        "envelope_label": format_minor(envelope, currency),
        "spent_minor": spent,
        "spent_label": format_minor(spent, currency),
        "remaining_minor": envelope - spent,
        "remaining_label": format_minor(envelope - spent, currency),
    }


def _public(ctx, person, row, *, with_expenses=True):
    planned = _planned(ctx, row["id"])
    expenses = _visible_expenses(ctx, person, row["id"], row["currency"]) if with_expenses else []
    money = _money(row["currency"], planned, expenses)
    return {
        "id": row["id"],
        "public_id": row["public_id"],
        "title": row["title"],
        "destination": row["destination"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "currency": row["currency"],
        "created_by": row["created_by"],
        "participants": _participants(ctx, row["id"]),
        "expenses": expenses,
        **money,
    }


def _load(ctx, sejour_id):
    require_module(ctx, "calendrier")
    require_household(ctx.conn, hh(ctx))
    row = ctx.conn.execute(
        f"""SELECT id, public_id, title, destination, start_date, end_date, currency,
                  created_by, archived
           FROM sejour WHERE id=? AND household_id={hh(ctx)}""",
        (sejour_id,),
    ).fetchone()
    if row is None or row["archived"]:
        raise AppError(404, "not_found", "Séjour introuvable.")
    return row


def list_sejours(ctx, person):
    require_module(ctx, "calendrier")
    require_household(ctx.conn, hh(ctx))
    rows = ctx.conn.execute(
        f"""SELECT id, public_id, title, destination, start_date, end_date, currency,
                  created_by, archived
           FROM sejour
           WHERE household_id={hh(ctx)} AND archived=0
           ORDER BY start_date, id"""
    ).fetchall()
    return {"items": [_public(ctx, person, row, with_expenses=False) for row in rows]}


def get_sejour(ctx, person, sejour_id):
    return _public(ctx, person, _load(ctx, sejour_id))


def overlapping(ctx, person, start, end, q=""):
    """Séjours du foyer dont l'intervalle coupe [start, end]. Lecture seule, sans événement calendrier."""
    require_module(ctx, "calendrier")
    where = [
        f"household_id={hh(ctx)}", "archived=0",
        "start_date<=:end", "end_date>=:start",
    ]
    params = {"start": start, "end": end}
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(title LIKE :q ESCAPE '\\' OR destination LIKE :q ESCAPE '\\')")
        params["q"] = f"%{escaped}%"
    rows = ctx.conn.execute(
        f"""SELECT id, title, destination, start_date, end_date
           FROM sejour WHERE {' AND '.join(where)}
           ORDER BY start_date, id""",
        params,
    ).fetchall()
    found = []
    for row in rows:
        found.append({
            "id": row["id"],
            "title": row["title"],
            "destination": row["destination"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "participant_ids": [item["id"] for item in _participants(ctx, row["id"])],
        })
    return found


def _parse(ctx, data, *, partial=False):
    fields = {}
    if not partial or "title" in data:
        fields["title"] = text_value(data.get("title"), "title", 200, required=True, label="Le titre")
    if not partial or "destination" in data:
        fields["destination"] = text_value(
            data.get("destination", ""), "destination", 200, required=False, label="La destination",
        )
    if not partial or "start_date" in data:
        start = date_value(data.get("start_date"), key="start_date", label="La date de début")
        if not start:
            raise AppError(400, "validation", "Date de début requise.", {"start_date": "Date de début requise."})
        fields["start_date"] = start
    if not partial or "end_date" in data:
        end = date_value(data.get("end_date"), key="end_date", label="La date de fin")
        if not end:
            raise AppError(400, "validation", "Date de fin requise.", {"end_date": "Date de fin requise."})
        fields["end_date"] = end
    if not partial or "currency" in data:
        fields["currency"] = require_currency(data.get("currency"))
    if not partial or "participant_ids" in data:
        raw = data.get("participant_ids") or []
        if isinstance(raw, str):
            raw = [part for part in raw.replace(";", ",").split(",") if part.strip()]
        ids = []
        for value in raw:
            try:
                person_id = int(value)
            except (TypeError, ValueError):
                raise AppError(
                    400, "validation", "Participant invalide.",
                    {"participant_ids": "Participant invalide."},
                )
            _active_member(ctx, person_id)
            ids.append(person_id)
        fields["participant_ids"] = list(dict.fromkeys(ids))
    line_fields = [f"envelope_{key}" for key, _label in LINES]
    if not partial or any(name in data for name in line_fields):
        lines = {}
        for key, label in LINES:
            name = f"envelope_{key}"
            if partial and name not in data:
                continue
            lines[key] = _optional_minor(data.get(name), name, label)
        fields["lines"] = lines
    return fields


def _dates_ok(start, end):
    if end < start:
        raise AppError(400, "validation", "La fin précède le début.", {"end_date": "La fin précède le début."})


def _write_participants(ctx, sejour_id, person_ids):
    ctx.conn.execute("DELETE FROM sejour_participant WHERE sejour_id=?", (sejour_id,))
    for person_id in person_ids:
        ctx.conn.execute(
            "INSERT INTO sejour_participant(sejour_id, person_id) VALUES(?,?)",
            (sejour_id, person_id),
        )


def _write_lines(ctx, sejour_id, lines):
    for key, amount in lines.items():
        ctx.conn.execute(
            """INSERT INTO sejour_envelope_line(sejour_id, line_key, amount_minor)
               VALUES(?,?,?)
               ON CONFLICT(sejour_id, line_key) DO UPDATE SET amount_minor=excluded.amount_minor""",
            (sejour_id, key, amount),
        )


def create_sejour(ctx, person, data):
    require_module(ctx, "calendrier")
    require_household(ctx.conn, hh(ctx))
    fields = _parse(ctx, data, partial=False)
    _dates_ok(fields["start_date"], fields["end_date"])
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO sejour(
                 household_id, public_id, title, destination, start_date, end_date, currency,
                 created_by, archived, created_at, updated_at
               ) VALUES({hh(ctx)},?,?,?,?,?,?,?,0,?,?)""",
            (
                str(uuid.uuid4()), fields["title"], fields["destination"],
                fields["start_date"], fields["end_date"], fields["currency"],
                person["id"], moment, moment,
            ),
        )
        sejour_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _write_participants(ctx, sejour_id, fields["participant_ids"])
        _write_lines(ctx, sejour_id, fields["lines"])
    audit(ctx.home, ctx.clock, "sejour_create", "ok", person["id"], "sejour", sejour_id)
    return sejour_id


def update_sejour(ctx, person, sejour_id, data):
    existing = _load(ctx, sejour_id)
    fields = _parse(ctx, data, partial=True)
    start = fields.get("start_date", existing["start_date"])
    end = fields.get("end_date", existing["end_date"])
    _dates_ok(start, end)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            """UPDATE sejour
               SET title=?, destination=?, start_date=?, end_date=?, updated_at=?
               WHERE id=?""",
            (
                fields.get("title", existing["title"]),
                fields.get("destination", existing["destination"]),
                start, end, moment, sejour_id,
            ),
        )
        if "participant_ids" in fields:
            _write_participants(ctx, sejour_id, fields["participant_ids"])
        if "lines" in fields:
            _write_lines(ctx, sejour_id, fields["lines"])
    audit(ctx.home, ctx.clock, "sejour_update", "ok", person["id"], "sejour", sejour_id)
    return get_sejour(ctx, person, sejour_id)


def attach_expense(ctx, person, sejour_id, transaction_id, line_key):
    item = get_sejour(ctx, person, sejour_id)
    require_module(ctx, "finances")
    key = _line_key(line_key)
    try:
        txn_id = int(transaction_id)
    except (TypeError, ValueError):
        raise AppError(400, "validation", "Dépense invalide.", {"transaction_id": "Dépense invalide."})
    from .finance import get_transaction

    txn = get_transaction(ctx, person, txn_id)
    if txn["kind"] != "expense":
        raise AppError(
            400, "validation", "Seules les dépenses peuvent être rattachées.",
            {"transaction_id": "Seules les dépenses peuvent être rattachées."},
        )
    if txn["currency"] != item["currency"]:
        raise AppError(
            400, "validation",
            f"La dépense doit être en {item['currency']} (pas de conversion).",
            {"transaction_id": f"Le séjour est en {item['currency']}."},
        )
    existing = ctx.conn.execute(
        "SELECT id, sejour_id FROM sejour_expense WHERE transaction_id=? AND archived=0",
        (txn_id,),
    ).fetchone()
    if existing is not None:
        raise AppError(
            409, "conflict", "Cette dépense est déjà rattachée à un séjour.",
            {"transaction_id": "Déjà rattachée."},
        )
    moment = iso_utc(ctx.clock.now())
    try:
        with write_tx(ctx):
            ctx.conn.execute(
                """INSERT INTO sejour_expense(sejour_id, transaction_id, line_key, created_by, created_at, archived)
                   VALUES(?,?,?,?,?,0)""",
                (sejour_id, txn_id, key, person["id"], moment),
            )
            attachment_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        raise AppError(
            409, "conflict", "Cette dépense est déjà rattachée à un séjour.",
            {"transaction_id": "Déjà rattachée."},
        )
    audit(ctx.home, ctx.clock, "sejour_attach", "ok", person["id"], "sejour_expense", attachment_id)
    return attachment_id


def record_expense(ctx, person, sejour_id, data):
    """Crée une dépense du foyer dans la devise du séjour, puis la rattache à un poste."""
    item = get_sejour(ctx, person, sejour_id)
    require_module(ctx, "finances")
    key = _line_key(data.get("line_key"))
    from .finance import create_transaction

    payload = dict(data)
    payload["kind"] = "expense"
    payload["currency"] = item["currency"]
    txn_id = create_transaction(ctx, person, payload)
    return attach_expense(ctx, person, sejour_id, txn_id, key)


def detach_expense(ctx, person, sejour_id, attachment_id):
    get_sejour(ctx, person, sejour_id)
    try:
        attachment_id = int(attachment_id)
    except (TypeError, ValueError):
        raise AppError(404, "not_found", "Rattachement introuvable.")
    row = ctx.conn.execute(
        """SELECT id, transaction_id FROM sejour_expense
           WHERE id=? AND sejour_id=? AND archived=0""",
        (attachment_id, sejour_id),
    ).fetchone()
    if row is None or not can_see_object(ctx, person, "finance_transaction", row["transaction_id"]):
        raise AppError(404, "not_found", "Rattachement introuvable.")
    with write_tx(ctx):
        ctx.conn.execute("UPDATE sejour_expense SET archived=1 WHERE id=?", (attachment_id,))
    audit(ctx.home, ctx.clock, "sejour_detach", "ok", person["id"], "sejour_expense", attachment_id)
