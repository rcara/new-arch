"""Repères : statuts calculés, archives, projection sans pièce ni décision."""

import sqlite3

from .auth import require_principal
from ..audit import audit
from ..clock import civil_today, iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..present import STATUS_LABEL, notice_date
from ..validate import (
    CATEGORIES,
    amount_cents,
    amount_from_form,
    due_date_value,
    notice_days_value,
    text_value,
)

STATUS_SQL = """
CASE WHEN m.due_date IS NULL THEN 'sans_date'
     WHEN m.due_date < :today THEN 'expire'
     WHEN m.due_date <= date(:today, '+30 days') THEN 'sous_30'
     WHEN m.due_date <= date(:today, '+90 days') THEN 'sous_90'
     ELSE 'a_jour' END
"""

PROJECTION = f"""
SELECT m.id, m.name, m.category, m.holder_id, h.display_name AS holder_name, h.active AS holder_active,
       m.responsible_id, r.display_name AS responsible_name, r.active AS responsible_active,
       m.location, m.amount_cents, m.due_date, m.notice_days, m.note, m.archived,
       m.created_at, m.updated_at,
       EXISTS(SELECT 1 FROM stored_file f WHERE f.milestone_id=m.id) AS has_file,
       {STATUS_SQL} AS status
FROM milestone m
JOIN person h ON h.id=m.holder_id
LEFT JOIN person r ON r.id=m.responsible_id
"""


def require_index(person):
    if not person["can_view_index"]:
        raise AppError(403, "forbidden", "Les repères ne vous sont pas accordés.")


def _today(ctx):
    household = require_household(ctx.conn)
    return household, civil_today(ctx.clock, household["timezone"])


def _like(value):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def counters(ctx, person):
    require_index(person)
    household, today = _today(ctx)
    rows = ctx.conn.execute(
        f"SELECT {STATUS_SQL} AS status, COUNT(*) AS n FROM milestone m WHERE m.archived=0 GROUP BY status",
        {"today": today.isoformat()},
    ).fetchall()
    found = {row["status"]: row["n"] for row in rows}
    keys = ("expire", "sous_30", "sous_90", "a_jour", "sans_date")
    counts = {key: int(found.get(key, 0)) for key in keys}
    return {
        "today": today.isoformat(),
        "timezone": household["timezone"],
        "household_name": household["name"],
        "urgent": counts["expire"] == 0 and counts["sous_30"] == 0,
        "counters": counts,
    }


def list_milestones(ctx, person, *, q="", category="", statut="", archives=False, page=1):
    require_index(person)
    _household, today = _today(ctx)
    where = []
    params = {"today": today.isoformat()}
    if not archives:
        where.append("m.archived=0")
    if category:
        if category not in CATEGORIES:
            raise AppError(400, "validation", "Catégorie inconnue.", {"category": "Catégorie inconnue."})
        where.append("m.category=:category")
        params["category"] = category
    if statut:
        if statut not in STATUS_LABEL:
            raise AppError(400, "validation", "Statut inconnu.", {"statut": "Statut inconnu."})
        where.append(f"({STATUS_SQL})=:statut")
        params["statut"] = statut
    if q:
        where.append(
            "(m.name LIKE :q ESCAPE '\\' OR m.category LIKE :q ESCAPE '\\' OR h.display_name LIKE :q ESCAPE '\\')"
        )
        params["q"] = _like(q.strip())
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    page = max(1, int(page or 1))
    total = ctx.conn.execute(f"SELECT COUNT(*) AS n FROM milestone m JOIN person h ON h.id=m.holder_id {clause}", params).fetchone()["n"]
    params["limit"] = 50
    params["offset"] = (page - 1) * 50
    rows = ctx.conn.execute(
        f"{PROJECTION} {clause} ORDER BY m.due_date IS NULL, m.due_date, m.id LIMIT :limit OFFSET :offset",
        params,
    ).fetchall()
    return {
        "items": [_public_item(row) for row in rows],
        "page": page,
        "page_size": 50,
        "total": total,
        "today": today.isoformat(),
    }


def today_items(ctx, person):
    summary = counters(ctx, person)
    rows = ctx.conn.execute(
        f"{PROJECTION} WHERE m.archived=0 ORDER BY m.due_date IS NULL, m.due_date, m.id",
        {"today": summary["today"]},
    ).fetchall()
    summary["items"] = [
        {
            "id": row["id"],
            "name": row["name"],
            "due_date": row["due_date"],
            "status": row["status"],
            "has_file": bool(row["has_file"]),
        }
        for row in rows
    ]
    summary["total"] = len(summary["items"])
    return summary


def get_milestone(ctx, person, milestone_id):
    require_index(person)
    _household, today = _today(ctx)
    row = ctx.conn.execute(
        f"{PROJECTION} WHERE m.id=:id",
        {"id": milestone_id, "today": today.isoformat()},
    ).fetchone()
    if row is None:
        raise AppError(404, "not_found", "Introuvable.")
    item = _detail(row)
    decisions = ctx.conn.execute(
        """SELECT d.id, d.created_at,
                  CASE WHEN :principal=1 OR a.person_id IS NOT NULL THEN 1 ELSE 0 END AS can_read
           FROM decision d
           LEFT JOIN decision_access a ON a.decision_id=d.id AND a.person_id=:pid
           WHERE d.milestone_id=:mid
           ORDER BY d.created_at, d.id""",
        {"principal": 1 if person["is_principal"] else 0, "pid": person["id"], "mid": milestone_id},
    ).fetchall()
    item["decisions"] = [
        {"id": d["id"], "created_at": d["created_at"], "can_read": bool(d["can_read"])}
        for d in decisions
    ]
    item["notice_date"] = notice_date(row["due_date"], row["notice_days"])
    return item


def _public_item(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "holder_id": row["holder_id"],
        "holder_name": row["holder_name"],
        "holder_active": bool(row["holder_active"]),
        "responsible_id": row["responsible_id"],
        "responsible_name": row["responsible_name"],
        "due_date": row["due_date"],
        "status": row["status"],
        "has_file": bool(row["has_file"]),
        "archived": bool(row["archived"]),
        "amount_cents": row["amount_cents"],
    }


def _detail(row):
    item = _public_item(row)
    item.update({
        "location": row["location"],
        "notice_days": row["notice_days"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "responsible_active": None if row["responsible_active"] is None else bool(row["responsible_active"]),
    })
    return item


def _assignable(conn, person_id, current_id, key, label):
    row = conn.execute("SELECT id, active FROM person WHERE id=?", (person_id,)).fetchone()
    if row is None:
        raise AppError(400, "validation", "Personne inconnue.", {key: f"{label} est inconnu."})
    if not row["active"] and person_id != current_id:
        raise AppError(400, "validation", "Personne retirée.", {key: f"{label} est retiré du foyer."})
    return row


def normalize_milestone(data, *, from_form=False):
    name = text_value(data.get("name"), "name", 160, required=True, label="Le nom")
    category = data.get("category")
    if category not in CATEGORIES:
        raise AppError(400, "validation", "Catégorie inconnue.", {"category": "Choisissez l'une des sept catégories."})
    holder = data.get("holder_id")
    if isinstance(holder, str) and holder.strip().isdigit():
        holder = int(holder.strip())
    if isinstance(holder, bool) or not isinstance(holder, int):
        raise AppError(400, "validation", "Titulaire requis.", {"holder_id": "Le titulaire est requis."})
    responsible = data.get("responsible_id")
    if responsible in ("", None):
        responsible = None
    elif isinstance(responsible, str) and responsible.strip().isdigit():
        responsible = int(responsible.strip())
    if responsible is not None and (isinstance(responsible, bool) or not isinstance(responsible, int)):
        raise AppError(400, "validation", "Responsable invalide.", {"responsible_id": "Responsable invalide."})
    if responsible is not None and responsible == holder:
        raise AppError(400, "validation", "Responsable distinct.", {"responsible_id": "Le responsable est indiqué seulement s'il est distinct du titulaire."})
    if from_form:
        cents = amount_from_form(data.get("amount"))
    else:
        cents = amount_cents(data.get("amount_cents"))
    location = text_value(data.get("location") or "", "location", 250, label="L'emplacement")
    note = text_value(data.get("note") or "", "note", 2000, label="La note")
    due = due_date_value(data.get("due_date"))
    notice = notice_days_value(data.get("notice_days"))
    return {
        "name": name,
        "category": category,
        "holder_id": holder,
        "responsible_id": responsible,
        "location": location,
        "amount_cents": cents,
        "due_date": due,
        "notice_days": notice,
        "note": note,
    }


def create_milestone(ctx, person, fields):
    require_principal(person)
    normalized = normalize_milestone(fields, from_form=fields.get("_from_form", False))
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        _assignable(ctx.conn, normalized["holder_id"], None, "holder_id", "Le titulaire")
        if normalized["responsible_id"] is not None:
            _assignable(ctx.conn, normalized["responsible_id"], None, "responsible_id", "Le responsable")
        try:
            ctx.conn.execute(
                """INSERT INTO milestone(household_id, name, category, holder_id, responsible_id, location,
                   amount_cents, due_date, notice_days, note, archived, created_at, updated_at)
                   VALUES(1,?,?,?,?,?,?,?,?,?,0,?,?)""",
                (
                    normalized["name"], normalized["category"], normalized["holder_id"], normalized["responsible_id"],
                    normalized["location"], normalized["amount_cents"], normalized["due_date"], normalized["notice_days"],
                    normalized["note"], moment, moment,
                ),
            )
        except sqlite3.IntegrityError:
            raise AppError(400, "validation", "Repère refusé.", {})
        new_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(ctx.home, ctx.clock, "milestone_create", "ok", person["id"], "milestone", new_id)
    return new_id


def update_milestone(ctx, person, milestone_id, fields, expected_updated_at, archive=None):
    require_principal(person)
    if not expected_updated_at:
        raise AppError(409, "conflict", "Rechargez le repère avant de l'enregistrer.")
    with write_tx(ctx):
        current = ctx.conn.execute(
            """SELECT id, name, category, holder_id, responsible_id, location, amount_cents,
                      due_date, notice_days, note, archived, updated_at
               FROM milestone WHERE id=?""",
            (milestone_id,),
        ).fetchone()
        if current is None:
            raise AppError(404, "not_found", "Introuvable.")
        if current["updated_at"] != expected_updated_at:
            raise AppError(409, "conflict", "Ce repère a été modifié entre-temps. Rechargez la fiche.")
        merged = {
            "name": fields.get("name", current["name"]),
            "category": fields.get("category", current["category"]),
            "holder_id": fields.get("holder_id", current["holder_id"]),
            "responsible_id": current["responsible_id"] if "responsible_id" not in fields else fields.get("responsible_id"),
            "location": fields.get("location", current["location"]),
            "amount_cents": current["amount_cents"] if "amount_cents" not in fields and "amount" not in fields else fields.get("amount_cents", fields.get("amount")),
            "due_date": current["due_date"] if "due_date" not in fields else fields.get("due_date"),
            "notice_days": current["notice_days"] if "notice_days" not in fields else fields.get("notice_days"),
            "note": current["note"] if "note" not in fields else fields.get("note"),
            "_from_form": fields.get("_from_form", False),
        }
        if fields.get("_from_form"):
            merged["amount"] = fields.get("amount")
        normalized = normalize_milestone(merged, from_form=bool(fields.get("_from_form")))
        archived = current["archived"] if archive is None else (1 if archive else 0)
        _assignable(ctx.conn, normalized["holder_id"], current["holder_id"], "holder_id", "Le titulaire")
        if normalized["responsible_id"] is not None:
            _assignable(ctx.conn, normalized["responsible_id"], current["responsible_id"], "responsible_id", "Le responsable")
        moment = iso_utc(ctx.clock.now())
        try:
            cur = ctx.conn.execute(
                """UPDATE milestone SET name=?, category=?, holder_id=?, responsible_id=?, location=?,
                   amount_cents=?, due_date=?, notice_days=?, note=?, archived=?, updated_at=?
                   WHERE id=? AND updated_at=?""",
                (
                    normalized["name"], normalized["category"], normalized["holder_id"], normalized["responsible_id"],
                    normalized["location"], normalized["amount_cents"], normalized["due_date"], normalized["notice_days"],
                    normalized["note"], archived, moment, milestone_id, expected_updated_at,
                ),
            )
        except sqlite3.IntegrityError:
            raise AppError(400, "validation", "Repère refusé.", {})
        if cur.rowcount != 1:
            raise AppError(409, "conflict", "Ce repère a été modifié entre-temps. Rechargez la fiche.")
    audit(ctx.home, ctx.clock, "milestone_update", "ok", person["id"], "milestone", milestone_id)
    return milestone_id
