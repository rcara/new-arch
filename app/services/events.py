"""Calendrier : événements du foyer (distincts des repères Index)."""

import uuid

from ..audit import audit
from ..clock import civil_today, iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..validate import date_value, text_value, timezone_name
from .modules import require_module

RECURRENCES = frozenset({"none", "daily", "weekly", "monthly", "yearly"})

SELECT = """
SELECT e.*, r.display_name AS responsible_name
FROM calendar_event e
LEFT JOIN person r ON r.id=e.responsible_id
"""


def _person_or_none(conn, person_id):
    if person_id is None:
        return None
    return conn.execute(
        "SELECT id FROM person WHERE id=? AND household_id=1", (person_id,)
    ).fetchone()


def _public(row):
    return {
        "id": row["id"],
        "public_id": row["public_id"],
        "title": row["title"],
        "notes": row["notes"],
        "all_day": bool(row["all_day"]),
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "timezone": row["timezone"],
        "responsible_id": row["responsible_id"],
        "responsible_name": row["responsible_name"] if "responsible_name" in row.keys() else None,
        "created_by": row["created_by"],
        "recurrence": row["recurrence"],
        "archived": bool(row["archived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_events(ctx, person, *, from_date=None, to_date=None, q="", page=1):
    require_module(ctx, "calendrier")
    household = require_household(ctx.conn)
    today = civil_today(ctx.clock, household["timezone"])
    start = from_date or today.isoformat()
    if to_date:
        end = to_date
    else:
        end = ctx.conn.execute("SELECT date(?, '+90 days')", (start,)).fetchone()[0]
    start = date_value(start, key="from", label="La date de début") or today.isoformat()
    end = date_value(end, key="to", label="La date de fin") or end
    where = ["e.household_id=1", "e.archived=0", "e.start_date <= :end", "(e.end_date IS NULL OR e.end_date >= :start)"]
    params = {"start": start, "end": end}
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("e.title LIKE :q ESCAPE '\\'")
        params["q"] = f"%{escaped}%"
    clause = " AND ".join(where)
    page = max(1, int(page or 1))
    total = ctx.conn.execute(f"SELECT COUNT(*) AS n FROM calendar_event e WHERE {clause}", params).fetchone()["n"]
    params["limit"] = 100
    params["offset"] = (page - 1) * 100
    rows = ctx.conn.execute(
        f"{SELECT} WHERE {clause} ORDER BY e.start_date, e.id LIMIT :limit OFFSET :offset",
        params,
    ).fetchall()
    return {
        "items": [_public(row) for row in rows],
        "page": page,
        "page_size": 100,
        "total": total,
        "from_date": start,
        "to_date": end,
    }


def get_event(ctx, person, event_id):
    require_module(ctx, "calendrier")
    row = ctx.conn.execute(f"{SELECT} WHERE e.id=? AND e.household_id=1", (event_id,)).fetchone()
    if row is None or row["archived"]:
        raise AppError(404, "not_found", "Événement introuvable.")
    return _public(row)


def _parse(data, household_tz, *, partial=False):
    fields = {}
    if not partial or "title" in data:
        fields["title"] = text_value(data.get("title"), "title", 200, required=True, label="Le titre")
    if not partial or "notes" in data:
        fields["notes"] = text_value(data.get("notes", ""), "notes", 4000, required=False, label="La note")
    if not partial or "start_date" in data:
        start = date_value(data.get("start_date"), key="start_date", label="La date de début")
        if not start:
            raise AppError(400, "validation", "Date de début requise.", {"start_date": "Date de début requise."})
        fields["start_date"] = start
    if not partial or "end_date" in data:
        fields["end_date"] = date_value(data.get("end_date"), key="end_date", label="La date de fin")
    if "all_day" in data:
        raw = data.get("all_day")
        fields["all_day"] = 1 if raw in (True, 1, "1", "true", "on") else 0
    elif not partial:
        fields["all_day"] = 1
    if not partial or "timezone" in data:
        tz = data.get("timezone") or household_tz
        fields["timezone"] = timezone_name(tz)
    if not partial or "recurrence" in data:
        recurrence = (data.get("recurrence") or "none").strip()
        if recurrence not in RECURRENCES:
            raise AppError(400, "validation", "Récurrence inconnue.", {"recurrence": "Récurrence inconnue."})
        fields["recurrence"] = recurrence
    if not partial or "responsible_id" in data:
        raw = data.get("responsible_id")
        if raw in (None, "", 0, "0"):
            fields["responsible_id"] = None
        else:
            try:
                fields["responsible_id"] = int(raw)
            except (TypeError, ValueError):
                raise AppError(400, "validation", "Responsable invalide.", {"responsible_id": "Responsable invalide."})
        fields["_has_responsible"] = True
    return fields


def create_event(ctx, person, data):
    require_module(ctx, "calendrier")
    household = require_household(ctx.conn)
    fields = _parse(data, household["timezone"], partial=False)
    if fields.get("end_date") and fields["end_date"] < fields["start_date"]:
        raise AppError(400, "validation", "La fin précède le début.", {"end_date": "La fin précède le début."})
    if fields.get("responsible_id") is not None and _person_or_none(ctx.conn, fields["responsible_id"]) is None:
        raise AppError(400, "validation", "Responsable inconnu.", {"responsible_id": "Responsable inconnu."})
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            """INSERT INTO calendar_event(
                 household_id, public_id, title, notes, all_day, start_date, end_date,
                 start_at, end_at, timezone, responsible_id, created_by, recurrence,
                 archived, created_at, updated_at
               ) VALUES(1,?,?,?,?,?,?,NULL,NULL,?,?,?,?,0,?,?)""",
            (
                str(uuid.uuid4()),
                fields["title"],
                fields.get("notes", ""),
                fields.get("all_day", 1),
                fields["start_date"],
                fields.get("end_date"),
                fields["timezone"],
                fields.get("responsible_id"),
                person["id"],
                fields["recurrence"],
                moment,
                moment,
            ),
        )
        event_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(ctx.home, ctx.clock, "event_create", "ok", person["id"], "calendar_event", event_id)
    return event_id


def update_event(ctx, person, event_id, data):
    require_module(ctx, "calendrier")
    household = require_household(ctx.conn)
    existing = ctx.conn.execute(
        """SELECT id, household_id, public_id, title, notes, all_day, start_date, end_date,
                  start_at, end_at, timezone, responsible_id, created_by, recurrence,
                  archived, created_at, updated_at
           FROM calendar_event WHERE id=? AND household_id=1 AND archived=0""",
        (event_id,),
    ).fetchone()
    if existing is None:
        raise AppError(404, "not_found", "Événement introuvable.")
    fields = _parse(data, household["timezone"], partial=True)
    title = fields.get("title", existing["title"])
    notes = fields.get("notes", existing["notes"])
    all_day = fields.get("all_day", existing["all_day"])
    start_date = fields.get("start_date", existing["start_date"])
    end_date = fields["end_date"] if "end_date" in fields else existing["end_date"]
    timezone = fields.get("timezone", existing["timezone"])
    recurrence = fields.get("recurrence", existing["recurrence"])
    responsible_id = fields["responsible_id"] if fields.get("_has_responsible") else existing["responsible_id"]
    if end_date and end_date < start_date:
        raise AppError(400, "validation", "La fin précède le début.", {"end_date": "La fin précède le début."})
    if responsible_id is not None and _person_or_none(ctx.conn, responsible_id) is None:
        raise AppError(400, "validation", "Responsable inconnu.", {"responsible_id": "Responsable inconnu."})
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            """UPDATE calendar_event SET title=?, notes=?, all_day=?, start_date=?, end_date=?,
                 timezone=?, responsible_id=?, recurrence=?, updated_at=? WHERE id=?""",
            (
                title, notes, all_day, start_date, end_date, timezone,
                responsible_id, recurrence, moment, event_id,
            ),
        )
    audit(ctx.home, ctx.clock, "event_update", "ok", person["id"], "calendar_event", event_id)
    return get_event(ctx, person, event_id)


def upcoming(ctx, person, *, within_days=30, limit=20):
    require_household(ctx.conn)
    household = require_household(ctx.conn)
    today = civil_today(ctx.clock, household["timezone"]).isoformat()
    rows = ctx.conn.execute(
        f"""{SELECT}
            WHERE e.household_id=1 AND e.archived=0
              AND e.start_date >= ?
              AND e.start_date <= date(?, '+' || ? || ' days')
            ORDER BY e.start_date, e.id
            LIMIT ?""",
        (today, today, int(within_days), int(limit)),
    ).fetchall()
    return [_public(row) for row in rows]
