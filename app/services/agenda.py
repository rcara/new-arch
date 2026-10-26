"""Agenda : vues mois, semaine et liste (lecture seule, au-dessus de events, séjours et milestones).

Les événements récurrents apparaissent comme autant d'occurrences, calculées à la lecture sur la période.

Les droits restent ceux des services : événements du foyer via `events.list_events`, échéances de repères
uniquement si le module est actif et que la personne a accès à l'index.
"""

from datetime import date, timedelta

from ..clock import civil_today
from ..db import require_household
from ..tenancy import hh
from . import events, google_calendar, milestones, modules, sejours

VIEWS = ("mois", "semaine", "liste")
LIST_DAYS = 60
MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
WEEKDAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")


def _anchor(raw, today):
    try:
        return date.fromisoformat(str(raw or ""))
    except ValueError:
        return today


def _month_start(day):
    return day.replace(day=1)


def _add_months(day, count):
    month = day.month - 1 + count
    return date(day.year + month // 12, month % 12 + 1, 1)


def _range(view, anchor):
    if view == "mois":
        first = _month_start(anchor)
        last = _add_months(first, 1) - timedelta(days=1)
        return first - timedelta(days=first.weekday()), last + timedelta(days=6 - last.weekday())
    if view == "semaine":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    return anchor, anchor + timedelta(days=LIST_DAYS - 1)


def _events(ctx, person, start, end, q=""):
    return events.occurrences(ctx, person, from_date=start.isoformat(), to_date=end.isoformat(), q=q)


def _deadlines(ctx, person, start, end):
    if "reperes" not in modules.enabled_keys(ctx) or not person.get("can_view_index"):
        return []
    found, page = [], 1
    while True:
        listed = milestones.list_milestones(ctx, person, page=page)
        for item in listed["items"]:
            if item["due_date"] and start.isoformat() <= item["due_date"] <= end.isoformat():
                found.append(item)
        if page * listed["page_size"] >= listed["total"] or not listed["items"]:
            return found
        page += 1


def _sejours(ctx, person, start, end, q=""):
    return sejours.overlapping(ctx, person, start.isoformat(), end.isoformat(), q=q)


def _entries(ctx, person, start, end, member_id, q):
    entries = []
    for item in _events(ctx, person, start, end, q):
        entries.append({
            "kind": "event", "id": item["id"], "title": item["title"],
            "start": item["start_date"], "end": item["end_date"] or item["start_date"],
            "who": item["responsible_name"], "people": {item["responsible_id"]},
            "recurrence": item["recurrence"], "recurrence_label": item["recurrence_label"],
            "occurrence": item["start_date"] if item["is_occurrence"] else None,
        })
    for item in _sejours(ctx, person, start, end, q):
        entries.append({
            "kind": "sejour", "id": item["id"], "title": item["title"],
            "start": item["start_date"], "end": item["end_date"],
            "who": item["destination"], "people": set(item["participant_ids"]),
            "span": True,
        })
    for item in [] if q else _deadlines(ctx, person, start, end):
        entries.append({
            "kind": "milestone", "id": item["id"], "title": item["name"],
            "start": item["due_date"], "end": item["due_date"],
            "who": item["responsible_name"] or item["holder_name"],
            "people": {item["responsible_id"], item["holder_id"]}, "status": item["status"],
        })
    # Overlay Google (autres calendriers) : lecture seule, pas de filtre membre.
    if not member_id:
        for item in google_calendar.overlay_entries(ctx, start=start, end=end, q=q):
            entries.append(item)
    if member_id:
        entries = [entry for entry in entries if member_id in entry["people"]]
    entries.sort(key=lambda entry: (entry["start"], entry["kind"] != "event", entry["title"].lower()))
    return entries


def _by_day(entries, start, end, *, span=True):
    days = {}
    for entry in entries:
        first = max(date.fromisoformat(entry["start"]), start)
        last = min(date.fromisoformat(entry["end"]), end) if span or entry.get("span") else first
        day = first
        while day <= last:
            days.setdefault(day.isoformat(), []).append(entry)
            day += timedelta(days=1)
    return days


def _label(view, anchor, start, end):
    if view == "mois":
        return f"{MONTHS[anchor.month - 1].capitalize()} {anchor.year}"
    if view == "semaine":
        return f"Semaine du {start.day} {MONTHS[start.month - 1]} au {end.day} {MONTHS[end.month - 1]} {end.year}"
    return f"Du {start.day} {MONTHS[start.month - 1]} au {end.day} {MONTHS[end.month - 1]} {end.year}"


def _step(view, anchor, direction):
    if view == "mois":
        return _add_months(anchor, direction)
    if view == "semaine":
        return anchor + timedelta(days=7 * direction)
    return anchor + timedelta(days=LIST_DAYS * direction)


def build(ctx, person, *, view="mois", anchor="", member_id=None, q=""):
    household = require_household(ctx.conn, hh(ctx))
    today = civil_today(ctx.clock, household["timezone"])
    view = view if view in VIEWS else "mois"
    day = _anchor(anchor, today)
    start, end = _range(view, day)
    google_calendar.maybe_sync(ctx, person)
    entries = _entries(ctx, person, start, end, member_id, q.strip())
    days = _by_day(entries, start, end, span=view != "liste")
    weeks = []
    if view in ("mois", "semaine"):
        cursor = start
        while cursor <= end:
            week = []
            for _ in range(7):
                iso = cursor.isoformat()
                week.append({
                    "iso": iso, "day": cursor.day, "weekday": WEEKDAYS[cursor.weekday()],
                    "in_month": view == "semaine" or cursor.month == day.month,
                    "is_today": cursor == today, "entries": days.get(iso, []),
                })
                cursor += timedelta(days=1)
            weeks.append(week)
    groups = [
        {"iso": iso, "weekday": WEEKDAYS[date.fromisoformat(iso).weekday()], "is_today": iso == today.isoformat(),
         "entries": days[iso]}
        for iso in sorted(days)
    ]
    return {
        "view": view,
        "anchor": day.isoformat(),
        "today": today.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "label": _label(view, day, start, end),
        "prev": _step(view, day, -1).isoformat(),
        "next": _step(view, day, 1).isoformat(),
        "weeks": weeks,
        "groups": groups,
        "count": len(entries),
        "weekdays": WEEKDAYS,
    }
