"""Finances du foyer : comptes, transactions, splits, budgets, soldes."""

import csv
import io
import sqlite3
import uuid
from ..tenancy import hh

from ..audit import audit
from ..clock import iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..money import (
    CURRENCIES,
    format_minor,
    parse_amount_to_minor,
    require_currency,
    split_equal,
    split_fixed,
    split_income_prorata,
    split_percent,
)
from ..validate import date_value, text_value
from .modules import require_module
from .people import list_active_members

ACCOUNT_KINDS = frozenset({"checking", "cash", "savings", "credit", "other"})
TXN_KINDS = frozenset({"expense", "income", "transfer", "reimbursement"})
SPLIT_METHODS = frozenset({"equal", "percent", "fixed", "income_prorata"})
DEFAULT_CATEGORIES = (
    ("Alimentation", "expense"),
    ("Logement", "expense"),
    ("Transport", "expense"),
    ("Santé", "expense"),
    ("Loisirs", "expense"),
    ("Abonnements", "expense"),
    ("Divers", "expense"),
    ("Salaire", "income"),
    ("Autre revenu", "income"),
)


def _require(ctx):
    require_module(ctx, "finances")
    return require_household(ctx.conn, hh(ctx))


def _active_person(ctx, person_id):
    row = ctx.conn.execute(
        f'SELECT id, display_name, active FROM person WHERE id=? AND household_id={hh(ctx)}',
        (person_id,),
    ).fetchone()
    if row is None or not row["active"]:
        raise AppError(400, "validation", "Personne inconnue ou inactive.")
    return row


def seed_defaults(ctx, person):
    """Catégories + comptes CHF/EUR de base si absents."""
    _require(ctx)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        count = ctx.conn.execute(
            f'SELECT COUNT(*) AS n FROM finance_category WHERE household_id={hh(ctx)}'
        ).fetchone()["n"]
        if count == 0:
            for name, kind in DEFAULT_CATEGORIES:
                ctx.conn.execute(
                    f"""INSERT INTO finance_category(household_id, public_id, name, kind, archived, created_at)
                       VALUES({hh(ctx)},?,?,?,0,?)""",
                    (str(uuid.uuid4()), name, kind, moment),
                )
        accounts = ctx.conn.execute(
            f'SELECT COUNT(*) AS n FROM finance_ledger_account WHERE household_id={hh(ctx)}'
        ).fetchone()["n"]
        if accounts == 0:
            for name, currency in (("Compte foyer CHF", "CHF"), ("Compte foyer EUR", "EUR")):
                ctx.conn.execute(
                    f"""INSERT INTO finance_ledger_account(
                         household_id, public_id, name, currency, account_kind, owner_id,
                         archived, created_at, updated_at
                       ) VALUES({hh(ctx)},?,?,?,'checking',NULL,0,?,?)""",
                    (str(uuid.uuid4()), name, currency, moment, moment),
                )


def list_ledger_accounts(ctx, person):
    _require(ctx)
    seed_defaults(ctx, person)
    rows = ctx.conn.execute(
        f"""SELECT a.id, a.public_id, a.name, a.currency, a.account_kind, a.owner_id,
                  a.archived, p.display_name AS owner_name
           FROM finance_ledger_account a
           LEFT JOIN person p ON p.id=a.owner_id
           WHERE a.household_id={hh(ctx)} AND a.archived=0
           ORDER BY a.currency, a.id"""
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "public_id": row["public_id"],
                "name": row["name"],
                "currency": row["currency"],
                "account_kind": row["account_kind"],
                "owner_id": row["owner_id"],
                "owner_name": row["owner_name"],
            }
            for row in rows
        ]
    }


def create_ledger_account(ctx, person, data):
    _require(ctx)
    name = text_value(data.get("name"), "name", 120, required=True, label="Le nom")
    currency = require_currency(data.get("currency"))
    kind = (data.get("account_kind") or "checking").strip()
    if kind not in ACCOUNT_KINDS:
        raise AppError(400, "validation", "Type de compte inconnu.", {"account_kind": "Type inconnu."})
    owner_id = data.get("owner_id")
    if owner_id in (None, "", 0, "0"):
        owner_id = None
    else:
        owner_id = int(owner_id)
        _active_person(ctx, owner_id)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO finance_ledger_account(
                 household_id, public_id, name, currency, account_kind, owner_id,
                 archived, created_at, updated_at
               ) VALUES({hh(ctx)},?,?,?,?,?,0,?,?)""",
            (str(uuid.uuid4()), name, currency, kind, owner_id, moment, moment),
        )
        new_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(ctx.home, ctx.clock, "finance_account_create", "ok", person["id"], "finance_ledger_account", new_id)
    return new_id


def list_categories(ctx, person, *, kind=""):
    _require(ctx)
    seed_defaults(ctx, person)
    where = [f'household_id={hh(ctx)}', "archived=0"]
    params = {}
    if kind:
        if kind not in {"expense", "income"}:
            raise AppError(400, "validation", "Type de catégorie inconnu.")
        where.append("kind=:kind")
        params["kind"] = kind
    rows = ctx.conn.execute(
        f"SELECT id, public_id, name, kind FROM finance_category WHERE {' AND '.join(where)} ORDER BY kind, name",
        params,
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


def set_income_share(ctx, person, person_id, income_value, currency="CHF"):
    _require(ctx)
    if not person.get("is_principal"):
        raise AppError(403, "forbidden", "Réservé au compte principal.")
    _active_person(ctx, person_id)
    currency = require_currency(currency)
    if income_value in (None, ""):
        income_minor = 0
    elif isinstance(income_value, int):
        income_minor = max(0, income_value)
    else:
        income_minor = parse_amount_to_minor(income_value, field="income", label="Le revenu") if str(income_value).strip() not in {"0", "0.0", "0,00"} else 0
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            """INSERT INTO finance_income_share(person_id, household_id, income_minor, currency, updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(person_id) DO UPDATE SET
                 income_minor=excluded.income_minor,
                 currency=excluded.currency,
                 updated_at=excluded.updated_at""",
            (person_id, hh(ctx), income_minor, currency, moment),
        )
    return {"person_id": person_id, "income_minor": income_minor, "currency": currency}


def list_income_shares(ctx, person):
    _require(ctx)
    rows = ctx.conn.execute(
        f"""SELECT s.person_id, p.display_name, s.income_minor, s.currency
           FROM finance_income_share s
           JOIN person p ON p.id=s.person_id
           WHERE s.household_id={hh(ctx)} AND p.active=1
           ORDER BY p.id"""
    ).fetchall()
    return {
        "items": [
            {
                "person_id": row["person_id"],
                "display_name": row["display_name"],
                "income_minor": row["income_minor"],
                "currency": row["currency"],
                "income_label": format_minor(row["income_minor"], row["currency"]),
            }
            for row in rows
        ]
    }


def _can_see_txn(ctx, person, row):
    if person.get("is_principal"):
        return True
    if row["visibility"] == "household":
        return True
    if row["created_by"] == person["id"] or row["payer_id"] == person["id"]:
        return True
    if row["beneficiary_id"] == person["id"]:
        return True
    split = ctx.conn.execute(
        "SELECT 1 FROM finance_split WHERE transaction_id=? AND person_id=?",
        (row["id"], person["id"]),
    ).fetchone()
    return split is not None


def _txn_public(ctx, row, splits=None):
    if splits is None:
        splits = ctx.conn.execute(
            """SELECT s.person_id, p.display_name, s.share_minor, s.method
               FROM finance_split s JOIN person p ON p.id=s.person_id
               WHERE s.transaction_id=? ORDER BY s.person_id""",
            (row["id"],),
        ).fetchall()
    return {
        "id": row["id"],
        "public_id": row["public_id"],
        "kind": row["kind"],
        "amount_minor": row["amount_minor"],
        "amount_label": format_minor(row["amount_minor"], row["currency"]),
        "currency": row["currency"],
        "txn_date": row["txn_date"],
        "label": row["label"],
        "notes": row["notes"],
        "category_id": row["category_id"],
        "category_name": row["category_name"] if "category_name" in row.keys() else None,
        "ledger_account_id": row["ledger_account_id"],
        "ledger_account_name": row["ledger_account_name"] if "ledger_account_name" in row.keys() else None,
        "counterparty_account_id": row["counterparty_account_id"],
        "payer_id": row["payer_id"],
        "payer_name": row["payer_name"] if "payer_name" in row.keys() else None,
        "beneficiary_id": row["beneficiary_id"],
        "beneficiary_name": row["beneficiary_name"] if "beneficiary_name" in row.keys() else None,
        "visibility": row["visibility"],
        "settles_transaction_id": row["settles_transaction_id"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "splits": [
            {
                "person_id": s["person_id"],
                "display_name": s["display_name"],
                "share_minor": s["share_minor"],
                "share_label": format_minor(s["share_minor"], row["currency"]),
                "method": s["method"],
            }
            for s in splits
        ],
    }


TXN_SELECT = """
SELECT t.id, t.public_id, t.kind, t.amount_minor, t.currency, t.txn_date, t.label, t.notes,
       t.category_id, c.name AS category_name,
       t.ledger_account_id, a.name AS ledger_account_name,
       t.counterparty_account_id, t.payer_id, pay.display_name AS payer_name,
       t.beneficiary_id, ben.display_name AS beneficiary_name,
       t.visibility, t.settles_transaction_id, t.created_by, t.created_at, t.archived
FROM finance_transaction t
LEFT JOIN finance_category c ON c.id=t.category_id
JOIN finance_ledger_account a ON a.id=t.ledger_account_id
JOIN person pay ON pay.id=t.payer_id
LEFT JOIN person ben ON ben.id=t.beneficiary_id
"""


def list_transactions(ctx, person, *, kind="", currency="", page=1):
    _require(ctx)
    seed_defaults(ctx, person)
    where = [f't.household_id={hh(ctx)}', "t.archived=0"]
    params = {}
    if kind:
        if kind not in TXN_KINDS:
            raise AppError(400, "validation", "Type de transaction inconnu.")
        where.append("t.kind=:kind")
        params["kind"] = kind
    if currency:
        params["currency"] = require_currency(currency)
        where.append("t.currency=:currency")
    clause = " AND ".join(where)
    rows = ctx.conn.execute(
        f"{TXN_SELECT} WHERE {clause} ORDER BY t.txn_date DESC, t.id DESC LIMIT 200",
        params,
    ).fetchall()
    items = [_txn_public(ctx, row) for row in rows if _can_see_txn(ctx, person, row)]
    page = max(1, int(page or 1))
    start = (page - 1) * 50
    return {"items": items[start:start + 50], "page": page, "page_size": 50, "total": len(items)}


def get_transaction(ctx, person, txn_id):
    _require(ctx)
    row = ctx.conn.execute(f"{TXN_SELECT} WHERE t.id=? AND t.household_id={hh(ctx)}", (txn_id,)).fetchone()
    if row is None or row["archived"]:
        raise AppError(404, "not_found", "Transaction introuvable.")
    if not _can_see_txn(ctx, person, row):
        raise AppError(404, "not_found", "Transaction introuvable.")
    return _txn_public(ctx, row)


def _build_splits(ctx, method, total_minor, data, currency):
    method = (method or "equal").strip()
    if method not in SPLIT_METHODS:
        raise AppError(400, "validation", "Méthode de répartition inconnue.", {"split_method": "Méthode inconnue."})
    person_ids = data.get("split_person_ids") or data.get("person_ids") or []
    if isinstance(person_ids, str):
        person_ids = [p for p in person_ids.replace(";", ",").split(",") if p.strip()]
    person_ids = [int(pid) for pid in person_ids]
    for pid in person_ids:
        _active_person(ctx, pid)

    if method == "equal":
        if len(person_ids) < 1:
            raise AppError(400, "validation", "Indiquez les personnes pour une répartition égale.")
        return split_equal(total_minor, person_ids)

    if method == "percent":
        allocations = data.get("splits") or []
        if not allocations:
            raise AppError(400, "validation", "Indiquez les pourcentages.")
        cleaned = []
        for item in allocations:
            cleaned.append({
                "person_id": int(item["person_id"]),
                "percent": item.get("percent", item.get("weight")),
            })
            _active_person(ctx, int(item["person_id"]))
        return split_percent(total_minor, cleaned)

    if method == "fixed":
        allocations = data.get("splits") or []
        if not allocations:
            raise AppError(400, "validation", "Indiquez les montants fixes.")
        for item in allocations:
            _active_person(ctx, int(item["person_id"]))
        return split_fixed(total_minor, allocations)

    # income_prorata
    if not person_ids:
        person_ids = [m["id"] for m in list_active_members(ctx, {"id": 0})]
    incomes = []
    for pid in person_ids:
        row = ctx.conn.execute(
            "SELECT income_minor FROM finance_income_share WHERE person_id=? AND currency=?",
            (pid, currency),
        ).fetchone()
        incomes.append({"person_id": pid, "income_minor": int(row["income_minor"]) if row else 0})
    return split_income_prorata(total_minor, incomes)


def create_transaction(ctx, person, data):
    _require(ctx)
    seed_defaults(ctx, person)
    kind = (data.get("kind") or "expense").strip()
    if kind not in TXN_KINDS:
        raise AppError(400, "validation", "Type de transaction inconnu.", {"kind": "Type inconnu."})
    amount_minor = parse_amount_to_minor(data.get("amount_minor", data.get("amount")))
    currency = require_currency(data.get("currency"))
    txn_date = date_value(data.get("txn_date"), key="txn_date", label="La date")
    if not txn_date:
        raise AppError(400, "validation", "Date requise.", {"txn_date": "Date requise."})
    label = text_value(data.get("label"), "label", 200, required=True, label="Le libellé")
    notes = text_value(data.get("notes", ""), "notes", 4000, required=False, label="La note")
    visibility = (data.get("visibility") or "household").strip()
    if visibility not in {"household", "private"}:
        raise AppError(400, "validation", "Visibilité inconnue.", {"visibility": "Visibilité inconnue."})

    try:
        ledger_account_id = int(data.get("ledger_account_id"))
    except (TypeError, ValueError):
        raise AppError(400, "validation", "Compte requis.", {"ledger_account_id": "Compte requis."})
    account = ctx.conn.execute(
        f'SELECT id, currency, archived FROM finance_ledger_account WHERE id=? AND household_id={hh(ctx)}',
        (ledger_account_id,),
    ).fetchone()
    if account is None or account["archived"]:
        raise AppError(400, "validation", "Compte inconnu.", {"ledger_account_id": "Compte inconnu."})
    if account["currency"] != currency:
        raise AppError(
            400,
            "validation",
            "La devise de la transaction doit correspondre au compte (pas de conversion implicite).",
            {"currency": f"Le compte est en {account['currency']}."},
        )

    payer_id = data.get("payer_id", person["id"])
    try:
        payer_id = int(payer_id)
    except (TypeError, ValueError):
        raise AppError(400, "validation", "Payeur invalide.", {"payer_id": "Payeur invalide."})
    _active_person(ctx, payer_id)

    category_id = data.get("category_id")
    counterparty_account_id = None
    beneficiary_id = None
    settles_transaction_id = None
    splits = []

    if kind in {"expense", "income"}:
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            raise AppError(400, "validation", "Catégorie requise.", {"category_id": "Catégorie requise."})
        cat = ctx.conn.execute(
            f'SELECT id, kind, archived FROM finance_category WHERE id=? AND household_id={hh(ctx)}',
            (category_id,),
        ).fetchone()
        if cat is None or cat["archived"] or cat["kind"] != kind:
            raise AppError(400, "validation", "Catégorie invalide.", {"category_id": "Catégorie invalide."})
        if kind == "expense":
            splits = _build_splits(ctx, data.get("split_method") or "equal", amount_minor, data, currency)
            if sum(s["share_minor"] for s in splits) != amount_minor:
                raise AppError(500, "storage", "Répartition incohérente.")
        else:
            category_id = category_id
            splits = []
    elif kind == "transfer":
        try:
            counterparty_account_id = int(data.get("counterparty_account_id"))
        except (TypeError, ValueError):
            raise AppError(400, "validation", "Compte destination requis.", {"counterparty_account_id": "Compte requis."})
        other = ctx.conn.execute(
            f'SELECT id, currency, archived FROM finance_ledger_account WHERE id=? AND household_id={hh(ctx)}',
            (counterparty_account_id,),
        ).fetchone()
        if other is None or other["archived"]:
            raise AppError(400, "validation", "Compte destination inconnu.")
        if other["currency"] != currency:
            raise AppError(400, "validation", "Transfert inter-devises refusé sans taux identifié.")
        category_id = None
    elif kind == "reimbursement":
        try:
            beneficiary_id = int(data.get("beneficiary_id"))
        except (TypeError, ValueError):
            raise AppError(400, "validation", "Bénéficiaire requis.", {"beneficiary_id": "Bénéficiaire requis."})
        _active_person(ctx, beneficiary_id)
        if beneficiary_id == payer_id:
            raise AppError(400, "validation", "Le bénéficiaire doit différer du payeur.")
        raw_settle = data.get("settles_transaction_id")
        if raw_settle not in (None, ""):
            settles_transaction_id = int(raw_settle)
            original = ctx.conn.execute(
                f'SELECT id, kind, currency, archived FROM finance_transaction WHERE id=? AND household_id={hh(ctx)}',
                (settles_transaction_id,),
            ).fetchone()
            if original is None or original["archived"] or original["kind"] != "expense":
                raise AppError(400, "validation", "Transaction d'origine invalide.")
            if original["currency"] != currency:
                raise AppError(400, "validation", "Devise différente de la dépense d'origine.")
        category_id = None

    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO finance_transaction(
                 household_id, public_id, kind, amount_minor, currency, txn_date, label, notes,
                 category_id, ledger_account_id, counterparty_account_id, payer_id, beneficiary_id,
                 created_by, visibility, settles_transaction_id, archived, created_at, updated_at
               ) VALUES({hh(ctx)},?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (
                str(uuid.uuid4()), kind, amount_minor, currency, txn_date, label, notes,
                category_id, ledger_account_id, counterparty_account_id, payer_id, beneficiary_id,
                person["id"], visibility, settles_transaction_id, moment, moment,
            ),
        )
        txn_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for share in splits:
            ctx.conn.execute(
                """INSERT INTO finance_split(transaction_id, person_id, share_minor, method)
                   VALUES(?,?,?,?)""",
                (txn_id, share["person_id"], share["share_minor"], share["method"]),
            )
    audit(ctx.home, ctx.clock, "finance_txn_create", kind, person["id"], "finance_transaction", txn_id)
    return txn_id


def person_balances(ctx, person, *, currency="CHF"):
    """Soldes entre personnes : positif = la personne doit recevoir."""
    _require(ctx)
    currency = require_currency(currency)
    members = list_active_members(ctx, person)
    nets = {m["id"]: 0 for m in members}

    expenses = ctx.conn.execute(
        f"""SELECT t.id, t.amount_minor, t.payer_id, t.visibility, t.created_by, t.beneficiary_id
           FROM finance_transaction t
           WHERE t.household_id={hh(ctx)} AND t.archived=0 AND t.kind='expense' AND t.currency=?""",
        (currency,),
    ).fetchall()
    for row in expenses:
        if not _can_see_txn(ctx, person, row):
            continue
        splits = ctx.conn.execute(
            "SELECT person_id, share_minor FROM finance_split WHERE transaction_id=?",
            (row["id"],),
        ).fetchall()
        payer = row["payer_id"]
        for split in splits:
            pid = split["person_id"]
            share = split["share_minor"]
            if pid == payer:
                continue
            # pid owes share to payer => payer net +, pid net -
            if payer in nets:
                nets[payer] += share
            if pid in nets:
                nets[pid] -= share

    reimbursements = ctx.conn.execute(
        f"""SELECT id, amount_minor, payer_id, beneficiary_id, visibility, created_by
           FROM finance_transaction
           WHERE household_id={hh(ctx)} AND archived=0 AND kind='reimbursement' AND currency=?""",
        (currency,),
    ).fetchall()
    for row in reimbursements:
        if not _can_see_txn(ctx, person, row):
            continue
        payer = row["payer_id"]
        beneficiary = row["beneficiary_id"]
        amount = row["amount_minor"]
        # payer reimburses beneficiary => reduces what payer owes beneficiary
        if payer in nets:
            nets[payer] += amount
        if beneficiary in nets:
            nets[beneficiary] -= amount

    items = []
    names = {m["id"]: m["display_name"] for m in members}
    for pid, net in sorted(nets.items(), key=lambda item: item[0]):
        items.append({
            "person_id": pid,
            "display_name": names.get(pid, str(pid)),
            "net_minor": net,
            "net_label": format_minor(net, currency),
            "meaning": "à recevoir" if net > 0 else ("à verser" if net < 0 else "à jour"),
        })
    return {"currency": currency, "entries": items}


def create_budget(ctx, person, data):
    _require(ctx)
    try:
        category_id = int(data.get("category_id"))
    except (TypeError, ValueError):
        raise AppError(400, "validation", "Catégorie requise.", {"category_id": "Catégorie requise."})
    cat = ctx.conn.execute(
        f'SELECT id, kind FROM finance_category WHERE id=? AND household_id={hh(ctx)} AND archived=0',
        (category_id,),
    ).fetchone()
    if cat is None or cat["kind"] != "expense":
        raise AppError(400, "validation", "Catégorie de dépense requise.")
    period = (data.get("period") or "month").strip()
    if period not in {"month", "year"}:
        raise AppError(400, "validation", "Période inconnue.")
    try:
        year = int(data.get("year"))
    except (TypeError, ValueError):
        raise AppError(400, "validation", "Année invalide.", {"year": "Année invalide."})
    month = data.get("month")
    if period == "month":
        try:
            month = int(month)
        except (TypeError, ValueError):
            raise AppError(400, "validation", "Mois requis.", {"month": "Mois requis."})
        if month < 1 or month > 12:
            raise AppError(400, "validation", "Mois invalide.", {"month": "Mois invalide."})
    else:
        month = None
    raw_amount = data.get("amount_minor", data.get("amount"))
    if raw_amount in (0, "0", "0.00", "0,00"):
        amount_minor = 0
    else:
        amount_minor = parse_amount_to_minor(raw_amount, field="amount", label="Le budget")
    currency = require_currency(data.get("currency"))
    moment = iso_utc(ctx.clock.now())
    try:
        with write_tx(ctx):
            ctx.conn.execute(
                f"""INSERT INTO finance_budget(
                     household_id, public_id, category_id, period, year, month,
                     amount_minor, currency, created_by, created_at
                   ) VALUES({hh(ctx)},?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), category_id, period, year, month, amount_minor, currency, person["id"], moment),
            )
            new_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        raise AppError(409, "conflict", "Ce budget existe déjà.")
    return new_id


def list_budgets(ctx, person, *, year=None, month=None, currency="CHF"):
    _require(ctx)
    currency = require_currency(currency)
    where = [f'b.household_id={hh(ctx)}', "b.currency=:currency"]
    params = {"currency": currency}
    if year is not None:
        where.append("b.year=:year")
        params["year"] = int(year)
    if month is not None:
        where.append("b.month=:month")
        params["month"] = int(month)
    rows = ctx.conn.execute(
        f"""SELECT b.id, b.public_id, b.category_id, c.name AS category_name, b.period,
                   b.year, b.month, b.amount_minor, b.currency
            FROM finance_budget b
            JOIN finance_category c ON c.id=b.category_id
            WHERE {' AND '.join(where)}
            ORDER BY b.year DESC, b.month DESC, c.name""",
        params,
    ).fetchall()
    items = []
    for row in rows:
        spent = _spent_in_period(ctx, person, row["category_id"], row["period"], row["year"], row["month"], currency)
        items.append({
            "id": row["id"],
            "category_id": row["category_id"],
            "category_name": row["category_name"],
            "period": row["period"],
            "year": row["year"],
            "month": row["month"],
            "amount_minor": row["amount_minor"],
            "amount_label": format_minor(row["amount_minor"], currency),
            "spent_minor": spent,
            "spent_label": format_minor(spent, currency),
            "remaining_minor": row["amount_minor"] - spent,
            "remaining_label": format_minor(row["amount_minor"] - spent, currency),
            "currency": currency,
        })
    return {"items": items, "currency": currency}


def _spent_in_period(ctx, person, category_id, period, year, month, currency):
    if period == "month":
        prefix = f"{year:04d}-{month:02d}"
        rows = ctx.conn.execute(
            f"""SELECT t.id, t.amount_minor, t.visibility, t.payer_id, t.created_by, t.beneficiary_id
               FROM finance_transaction t
               WHERE t.household_id={hh(ctx)} AND t.archived=0 AND t.kind='expense'
                 AND t.category_id=? AND t.currency=? AND t.txn_date LIKE ?""",
            (category_id, currency, prefix + "%"),
        ).fetchall()
    else:
        rows = ctx.conn.execute(
            f"""SELECT t.id, t.amount_minor, t.visibility, t.payer_id, t.created_by, t.beneficiary_id
               FROM finance_transaction t
               WHERE t.household_id={hh(ctx)} AND t.archived=0 AND t.kind='expense'
                 AND t.category_id=? AND t.currency=? AND t.txn_date >= ? AND t.txn_date < ?""",
            (category_id, currency, f"{year:04d}-01-01", f"{year + 1:04d}-01-01"),
        ).fetchall()
    total = 0
    for row in rows:
        if _can_see_txn(ctx, person, row):
            total += row["amount_minor"]
    return total


def export_csv(ctx, person, *, currency=""):
    _require(ctx)
    listed = list_transactions(ctx, person, currency=currency, page=1)
    # gather all pages roughly via direct query already limited; extend for export
    where = [f't.household_id={hh(ctx)}', "t.archived=0"]
    params = {}
    if currency:
        where.append("t.currency=:currency")
        params["currency"] = require_currency(currency)
    rows = ctx.conn.execute(
        f"{TXN_SELECT} WHERE {' AND '.join(where)} ORDER BY t.txn_date, t.id",
        params,
    ).fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([
        "date", "kind", "label", "amount_minor", "currency", "category",
        "account", "payer", "beneficiary", "visibility", "counts_in_budget",
    ])
    for row in rows:
        if not _can_see_txn(ctx, person, row):
            continue
        writer.writerow([
            row["txn_date"],
            row["kind"],
            row["label"],
            row["amount_minor"],
            row["currency"],
            row["category_name"] or "",
            row["ledger_account_name"] or "",
            row["payer_name"] or "",
            row["beneficiary_name"] or "",
            row["visibility"],
            "yes" if row["kind"] == "expense" else "no",
        ])
    return buffer.getvalue()


def import_csv(ctx, person, content):
    """Import CSV simple (même format que l'export, hors remboursements liés)."""
    _require(ctx)
    seed_defaults(ctx, person)
    text = content.decode("utf-8-sig") if isinstance(content, (bytes, bytearray)) else str(content)
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    created = 0
    errors = []
    accounts = {row["name"]: row for row in list_ledger_accounts(ctx, person)["items"]}
    categories = {(row["name"], row["kind"]): row for row in list_categories(ctx, person)["items"]}
    members = {m["display_name"]: m for m in list_active_members(ctx, person)}
    for index, row in enumerate(reader, start=2):
        try:
            kind = (row.get("kind") or "expense").strip()
            if kind not in {"expense", "income"}:
                raise AppError(400, "validation", f"Ligne {index}: type non importable ({kind}).")
            currency = require_currency(row.get("currency"))
            account_name = (row.get("account") or "").strip()
            account = accounts.get(account_name)
            if account is None:
                raise AppError(400, "validation", f"Ligne {index}: compte inconnu.")
            if account["currency"] != currency:
                raise AppError(400, "validation", f"Ligne {index}: devise ≠ compte.")
            cat_name = (row.get("category") or "").strip()
            cat = categories.get((cat_name, kind))
            if cat is None:
                raise AppError(400, "validation", f"Ligne {index}: catégorie inconnue.")
            payer_name = (row.get("payer") or "").strip()
            payer = members.get(payer_name)
            payer_id = payer["id"] if payer else person["id"]
            amount_raw = row.get("amount_minor") or row.get("amount")
            if str(amount_raw).isdigit():
                amount_minor = int(amount_raw)
            else:
                amount_minor = parse_amount_to_minor(amount_raw)
            payload = {
                "kind": kind,
                "amount_minor": amount_minor,
                "currency": currency,
                "txn_date": row.get("date"),
                "label": row.get("label") or "Import",
                "category_id": cat["id"],
                "ledger_account_id": account["id"],
                "payer_id": payer_id,
                "visibility": (row.get("visibility") or "household").strip(),
                "split_method": "equal",
                "split_person_ids": [payer_id],
            }
            if kind == "expense":
                # default: payer bears 100% unless multiple members and visibility household
                if payload["visibility"] == "household" and len(members) > 1:
                    payload["split_person_ids"] = [m["id"] for m in members.values()]
            create_transaction(ctx, person, payload)
            created += 1
        except AppError as exc:
            errors.append(exc.message)
    return {"created": created, "errors": errors}
