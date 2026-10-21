"""Calendrier : événements du foyer (distincts des repères Index)."""

import uuid
from calendar import monthrange
from datetime import date, timedelta

from ..tenancy import hh

from ..audit import audit
from ..clock import civil_today, iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..validate import date_value, text_value, timezone_name
from .modules import require_module

RECURRENCES = frozenset({"none", "daily", "weekly", "monthly", "yearly"})
RECURRENCE_LABEL = {
    "daily": "Tous les jours",
    "weekly": "Chaque semaine",
    "monthly": "Chaque mois",
    "yearly": "Chaque année",
}
MAX_OCCURRENCES = 1000

SELECT = """
SELECT e.*, r.display_name AS responsible_name
FROM calendar_event e
LEFT JOIN person r ON r.id=e.responsible_id
"""


def _person_or_none(ctx, person_id):
    if person_id is None:
        return None
    return ctx.conn.execute(
        f'SELECT id FROM person WHERE id=? AND household_id={hh(ctx)}', (person_id,)
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
        "recurrence_label": RECURRENCE_LABEL.get(row["recurrence"]),
        "archived": bool(row["archived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_events(ctx, person, *, from_date=None, to_date=None, q="", page=1):
    require_module(ctx, "calendrier")
    household = require_household(ctx.conn, hh(ctx))
    today = civil_today(ctx.clock, household["timezone"])
    start = from_date or today.isoformat()
    if to_date:
        end = to_date
    else:
        end = ctx.conn.execute("SELECT date(?, '+90 days')", (start,)).fetchone()[0]
    start = date_value(start, key="from", label="La date de début") or today.isoformat()
    end = date_value(end, key="to", label="La date de fin") or end
    where = [f'e.household_id={hh(ctx)}', "e.archived=0", "e.start_date <= :end", "(e.end_date IS NULL OR e.end_date >= :start)"]
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
    row = ctx.conn.execute(f"{SELECT} WHERE e.id=? AND e.household_id={hh(ctx)}", (event_id,)).fetchone()
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
    household = require_household(ctx.conn, hh(ctx))
    fields = _parse(data, household["timezone"], partial=False)
    if fields.get("end_date") and fields["end_date"] < fields["start_date"]:
        raise AppError(400, "validation", "La fin précède le début.", {"end_date": "La fin précède le début."})
    if fields.get("responsible_id") is not None and _person_or_none(ctx, fields["responsible_id"]) is None:
        raise AppError(400, "validation", "Responsable inconnu.", {"responsible_id": "Responsable inconnu."})
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO calendar_event(
                 household_id, public_id, title, notes, all_day, start_date, end_date,
                 start_at, end_at, timezone, responsible_id, created_by, recurrence,
                 archived, created_at, updated_at
               ) VALUES({hh(ctx)},?,?,?,?,?,?,NULL,NULL,?,?,?,?,0,?,?)""",
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
    household = require_household(ctx.conn, hh(ctx))
    existing = ctx.conn.execute(
        f"""SELECT id, household_id, public_id, title, notes, all_day, start_date, end_date,
                  start_at, end_at, timezone, responsible_id, created_by, recurrence,
                  archived, created_at, updated_at
           FROM calendar_event WHERE id=? AND household_id={hh(ctx)} AND archived=0""",
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
    if responsible_id is not None and _person_or_none(ctx, responsible_id) is None:
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


def _nth(first, recurrence, n):
    """n-ième occurrence calculée depuis la date d'origine : un 31 reste un 31 quand le mois le permet."""
    if recurrence == "daily":
        return first + timedelta(days=n)
    if recurrence == "weekly":
        return first + timedelta(weeks=n)
    if recurrence == "monthly":
        index = first.month - 1 + n
        year, month = first.year + index // 12, index % 12 + 1
        return date(year, month, min(first.day, monthrange(year, month)[1]))
    year = first.year + n
    return date(year, first.month, min(first.day, monthrange(year, first.month)[1]))


def _first_index(first, recurrence, earliest):
    """Indice sûr (jamais trop grand) de la première occurrence pouvant chevaucher `earliest`."""
    if earliest <= first:
        return 0
    if recurrence == "daily":
        return (earliest - first).days
    if recurrence == "weekly":
        return (earliest - first).days // 7
    if recurrence == "monthly":
        return max(0, (earliest.year - first.year) * 12 + earliest.month - first.month - 1)
    return max(0, earliest.year - first.year - 1)


def occurrence_dates(start_date, end_date, recurrence, window_start, window_end):
    """Paires (début, fin) des occurrences qui chevauchent [window_start, window_end], bornes incluses.

    La durée de chaque occurrence est celle de l'événement d'origine (end_date - start_date).
    Les séries n'ont pas de date de fin en base : elles se répètent indéfiniment.
    """
    first = date.fromisoformat(start_date)
    length = date.fromisoformat(end_date) - first if end_date else timedelta(0)
    window_start = date.fromisoformat(window_start) if isinstance(window_start, str) else window_start
    window_end = date.fromisoformat(window_end) if isinstance(window_end, str) else window_end
    if recurrence not in RECURRENCE_LABEL:
        if first <= window_end and first + length >= window_start:
            return [(first, first + length)]
        return []
    found = []
    n = _first_index(first, recurrence, window_start - length)
    while len(found) < MAX_OCCURRENCES:
        begin = _nth(first, recurrence, n)
        if begin > window_end:
            break
        if begin + length >= window_start:
            found.append((begin, begin + length))
        n += 1
    return found


def _expand(ctx, start, end, q=""):
    where = [
        f"e.household_id={hh(ctx)}", "e.archived=0", "e.start_date <= :end",
        "(e.recurrence != 'none' OR e.end_date IS NULL OR e.end_date >= :start)",
    ]
    params = {"start": start, "end": end}
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("e.title LIKE :q ESCAPE '\\'")
        params["q"] = f"%{escaped}%"
    rows = ctx.conn.execute(f"{SELECT} WHERE {' AND '.join(where)} ORDER BY e.start_date, e.id", params).fetchall()
    found = []
    for row in rows:
        base = _public(row)
        for begin, finish in occurrence_dates(row["start_date"], row["end_date"], row["recurrence"], start, end):
            item = dict(base)
            item.update({
                "start_date": begin.isoformat(),
                "end_date": finish.isoformat() if row["end_date"] else None,
                "series_start_date": row["start_date"],
                "series_end_date": row["end_date"],
                "is_occurrence": row["recurrence"] != "none",
            })
            found.append(item)
    found.sort(key=lambda item: (item["start_date"], item["id"]))
    return found


def occurrences(ctx, person, *, from_date, to_date, q=""):
    """Événements du foyer actif sur [from_date, to_date], séries récurrentes développées en occurrences.

    Lecture seule : rien n'est écrit en base ; chaque occurrence renvoie vers la série (même `id`).
    """
    require_module(ctx, "calendrier")
    start = date_value(from_date, key="from", label="La date de début")
    end = date_value(to_date, key="to", label="La date de fin")
    if not start or not end:
        raise AppError(400, "validation", "Période requise.", {"from": "Période requise."})
    return _expand(ctx, start, end, q)


def is_occurrence(item, day):
    """Vrai si `day` (AAAA-MM-JJ) est le début d'une occurrence de l'événement `item` (tel que renvoyé par get_event)."""
    try:
        target = date.fromisoformat(str(day or ""))
    except ValueError:
        return False
    return any(
        begin == target
        for begin, _ in occurrence_dates(item["start_date"], item["end_date"], item["recurrence"], target, target)
    )


def upcoming(ctx, person, *, within_days=30, limit=20):
    household = require_household(ctx.conn, hh(ctx))
    today = civil_today(ctx.clock, household["timezone"])
    horizon = today + timedelta(days=int(within_days))
    items = [
        item for item in _expand(ctx, today.isoformat(), horizon.isoformat())
        if item["start_date"] >= today.isoformat()
    ]
    return items[:int(limit)]
