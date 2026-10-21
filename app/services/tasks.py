"""Organisation : tâches du foyer, récurrences simples."""

import uuid
from calendar import monthrange
from datetime import date, timedelta
from ..tenancy import hh

from ..audit import audit
from ..clock import iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..validate import due_date_value, text_value
from .modules import require_module

PRIORITIES = frozenset({"low", "normal", "high"})
STATUSES = frozenset({"open", "done", "cancelled"})
RECURRENCES = frozenset({"none", "daily", "weekly", "monthly", "yearly"})
PRIORITY_LABEL = {"low": "Basse", "normal": "Normale", "high": "Haute"}
STATUS_LABEL = {"open": "Ouverte", "done": "Faite", "cancelled": "Annulée"}
RECURRENCE_LABEL = {
    "none": "Aucune",
    "daily": "Quotidienne",
    "weekly": "Hebdomadaire",
    "monthly": "Mensuelle",
    "yearly": "Annuelle",
}

SELECT = """
SELECT t.*, a.display_name AS assignee_name
FROM task t
LEFT JOIN person a ON a.id=t.assignee_id
"""


def _person_or_none(ctx, person_id):
    if person_id is None:
        return None
    return ctx.conn.execute(
        f'SELECT id, display_name, active FROM person WHERE id=? AND household_id={hh(ctx)}',
        (person_id,),
    ).fetchone()


def _public(row):
    return {
        "id": row["id"],
        "public_id": row["public_id"],
        "title": row["title"],
        "notes": row["notes"],
        "status": row["status"],
        "status_label": STATUS_LABEL.get(row["status"], row["status"]),
        "priority": row["priority"],
        "priority_label": PRIORITY_LABEL.get(row["priority"], row["priority"]),
        "assignee_id": row["assignee_id"],
        "assignee_name": row["assignee_name"] if "assignee_name" in row.keys() else None,
        "created_by": row["created_by"],
        "due_date": row["due_date"],
        "recurrence": row["recurrence"],
        "recurrence_label": RECURRENCE_LABEL.get(row["recurrence"], row["recurrence"]),
        "archived": bool(row["archived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def list_tasks(ctx, person, *, status="open", q="", page=1, assignee=""):
    require_module(ctx, "organisation")
    require_household(ctx.conn, hh(ctx))
    where = [f't.household_id={hh(ctx)}', "t.archived=0"]
    params = {}
    if assignee == "moi":
        where.append("t.assignee_id=:me")
        params["me"] = person["id"]
    elif assignee == "partage":
        where.append("t.assignee_id IS NULL")
    if status:
        if status not in STATUSES:
            raise AppError(400, "validation", "Statut inconnu.", {"status": "Statut inconnu."})
        where.append("t.status=:status")
        params["status"] = status
    if q:
        where.append("t.title LIKE :q ESCAPE '\\'")
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["q"] = f"%{escaped}%"
    clause = " AND ".join(where)
    page = max(1, int(page or 1))
    total = ctx.conn.execute(f"SELECT COUNT(*) AS n FROM task t WHERE {clause}", params).fetchone()["n"]
    params["limit"] = 50
    params["offset"] = (page - 1) * 50
    rows = ctx.conn.execute(
        f"""{SELECT} WHERE {clause}
            ORDER BY t.due_date IS NULL, t.due_date,
                     CASE t.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, t.id DESC
            LIMIT :limit OFFSET :offset""",
        params,
    ).fetchall()
    return {"items": [_public(row) for row in rows], "page": page, "page_size": 50, "total": total}


def get_task(ctx, person, task_id):
    require_module(ctx, "organisation")
    row = ctx.conn.execute(f"{SELECT} WHERE t.id=? AND t.household_id={hh(ctx)}", (task_id,)).fetchone()
    if row is None or row["archived"]:
        raise AppError(404, "not_found", "Tâche introuvable.")
    return _public(row)


def _parse_fields(data, *, partial=False):
    fields = {}
    if not partial or "title" in data:
        fields["title"] = text_value(data.get("title"), "title", 200, required=True, label="Le titre")
    if not partial or "notes" in data:
        fields["notes"] = text_value(data.get("notes", ""), "notes", 4000, required=False, label="La note")
    if not partial or "priority" in data:
        priority = (data.get("priority") or "normal").strip()
        if priority not in PRIORITIES:
            raise AppError(400, "validation", "Priorité inconnue.", {"priority": "Priorité inconnue."})
        fields["priority"] = priority
    if not partial or "recurrence" in data:
        recurrence = (data.get("recurrence") or "none").strip()
        if recurrence not in RECURRENCES:
            raise AppError(400, "validation", "Récurrence inconnue.", {"recurrence": "Récurrence inconnue."})
        fields["recurrence"] = recurrence
    if not partial or "due_date" in data:
        fields["due_date"] = due_date_value(data.get("due_date"))
        fields["_has_due"] = True
    if not partial or "assignee_id" in data:
        raw = data.get("assignee_id")
        if raw in (None, "", 0, "0"):
            fields["assignee_id"] = None
        else:
            try:
                fields["assignee_id"] = int(raw)
            except (TypeError, ValueError):
                raise AppError(400, "validation", "Assigné invalide.", {"assignee_id": "Assigné invalide."})
        fields["_has_assignee"] = True
    if "status" in data and data.get("status") is not None:
        status = str(data.get("status")).strip()
        if status not in STATUSES:
            raise AppError(400, "validation", "Statut inconnu.", {"status": "Statut inconnu."})
        fields["status"] = status
    return fields


def create_task(ctx, person, data):
    require_module(ctx, "organisation")
    fields = _parse_fields(data, partial=False)
    if fields.get("assignee_id") is not None and _person_or_none(ctx, fields["assignee_id"]) is None:
        raise AppError(400, "validation", "Assigné inconnu.", {"assignee_id": "Assigné inconnu."})
    moment = iso_utc(ctx.clock.now())
    public_id = str(uuid.uuid4())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO task(
                 household_id, public_id, title, notes, status, priority, assignee_id,
                 created_by, due_date, recurrence, archived, created_at, updated_at, completed_at
               ) VALUES({hh(ctx)},?,?,?,'open',?,?,?,?,?,0,?,?,NULL)""",
            (
                public_id,
                fields["title"],
                fields.get("notes", ""),
                fields["priority"],
                fields.get("assignee_id"),
                person["id"],
                fields.get("due_date"),
                fields["recurrence"],
                moment,
                moment,
            ),
        )
        task_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(ctx.home, ctx.clock, "task_create", "ok", person["id"], "task", task_id)
    return task_id


def next_due_date(current, recurrence):
    if recurrence == "none" or not current:
        return None
    base = date.fromisoformat(current)
    if recurrence == "daily":
        return (base + timedelta(days=1)).isoformat()
    if recurrence == "weekly":
        return (base + timedelta(weeks=1)).isoformat()
    if recurrence == "monthly":
        year, month = base.year, base.month + 1
        if month > 12:
            year, month = year + 1, 1
        day = min(base.day, monthrange(year, month)[1])
        return date(year, month, day).isoformat()
    if recurrence == "yearly":
        try:
            return date(base.year + 1, base.month, base.day).isoformat()
        except ValueError:
            return date(base.year + 1, base.month, 28).isoformat()
    return None


def update_task(ctx, person, task_id, data):
    require_module(ctx, "organisation")
    existing = ctx.conn.execute(
        f"""SELECT id, household_id, public_id, title, notes, status, priority, assignee_id,
                  created_by, due_date, recurrence, archived, created_at, updated_at, completed_at
           FROM task WHERE id=? AND household_id={hh(ctx)} AND archived=0""",
        (task_id,),
    ).fetchone()
    if existing is None:
        raise AppError(404, "not_found", "Tâche introuvable.")
    fields = _parse_fields(data, partial=True)
    if fields.get("_has_assignee") and fields.get("assignee_id") is not None:
        if _person_or_none(ctx, fields["assignee_id"]) is None:
            raise AppError(400, "validation", "Assigné inconnu.", {"assignee_id": "Assigné inconnu."})

    title = fields.get("title", existing["title"])
    notes = fields.get("notes", existing["notes"])
    priority = fields.get("priority", existing["priority"])
    recurrence = fields.get("recurrence", existing["recurrence"])
    due_date = fields["due_date"] if fields.get("_has_due") else existing["due_date"]
    assignee_id = fields["assignee_id"] if fields.get("_has_assignee") else existing["assignee_id"]
    new_status = fields.get("status", existing["status"])
    moment = iso_utc(ctx.clock.now())
    completed_at = existing["completed_at"]
    spawn = None
    if new_status == "done" and existing["status"] != "done":
        completed_at = moment
        if existing["recurrence"] != "none":
            spawn = {
                "title": title,
                "notes": notes,
                "priority": priority,
                "assignee_id": assignee_id,
                "due_date": next_due_date(due_date, existing["recurrence"]),
                "recurrence": existing["recurrence"],
            }
    elif new_status != "done":
        completed_at = None

    with write_tx(ctx):
        ctx.conn.execute(
            """UPDATE task SET title=?, notes=?, priority=?, assignee_id=?, due_date=?,
                 recurrence=?, status=?, completed_at=?, updated_at=? WHERE id=?""",
            (
                title, notes, priority, assignee_id, due_date, recurrence,
                new_status, completed_at, moment, task_id,
            ),
        )
        if spawn is not None:
            ctx.conn.execute(
                f"""INSERT INTO task(
                     household_id, public_id, title, notes, status, priority, assignee_id,
                     created_by, due_date, recurrence, archived, created_at, updated_at, completed_at
                   ) VALUES({hh(ctx)},?,?,?,'open',?,?,?,?,?,0,?,?,NULL)""",
                (
                    str(uuid.uuid4()),
                    spawn["title"],
                    spawn["notes"],
                    spawn["priority"],
                    spawn["assignee_id"],
                    person["id"],
                    spawn["due_date"],
                    spawn["recurrence"],
                    moment,
                    moment,
                ),
            )
    audit(ctx.home, ctx.clock, "task_update", "ok", person["id"], "task", task_id)
    return get_task(ctx, person, task_id)


def open_due_soon(ctx, person, *, within_days=30, limit=20, assignee_id=None):
    """Tâches ouvertes pour l'accueil (module organisation requis côté appelant)."""
    require_household(ctx.conn, hh(ctx))
    from ..clock import civil_today

    household = require_household(ctx.conn, hh(ctx))
    today = civil_today(ctx.clock, household["timezone"]).isoformat()
    where = [
        f't.household_id={hh(ctx)}',
        "t.archived=0",
        "t.status='open'",
        "(t.due_date IS NULL OR t.due_date <= date(?, '+' || ? || ' days'))",
    ]
    params = [today, int(within_days)]
    if assignee_id is not None:
        where.append("t.assignee_id=?")
        params.append(int(assignee_id))
    params.append(int(limit))
    rows = ctx.conn.execute(
        f"""{SELECT}
            WHERE {' AND '.join(where)}
            ORDER BY t.due_date IS NULL, t.due_date,
                     CASE t.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END
            LIMIT ?""",
        params,
    ).fetchall()
    return [_public(row) for row in rows]
