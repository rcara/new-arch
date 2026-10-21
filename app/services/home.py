"""Tableau de bord / Accueil transversal alimenté par données réelles."""

from ..clock import civil_today
from ..db import require_household
from ..tenancy import hh
from . import auth, events, milestones, modules, tasks


def dashboard(ctx, person):
    household = require_household(ctx.conn, hh(ctx))
    enabled = modules.enabled_keys(ctx)
    profile = auth.self_profile(ctx, person)
    payload = {
        "household_name": household["name"],
        "timezone": household["timezone"],
        "today": civil_today(ctx.clock, household["timezone"]).isoformat(),
        "modules": sorted(enabled),
        "person": profile,
        "mine": {
            "tasks": [],
            "task_count": 0,
            "balance": None,
            "media_in_progress": [],
            "urgent_milestones": 0,
        },
        "milestones": None,
        "tasks": [],
        "events": [],
    }

    if person.get("can_view_index"):
        summary = milestones.today_items(ctx, person)
        urgent = summary.get("urgent_items", [])
        payload["milestones"] = {
            "today": summary["today"],
            "urgent_items": urgent,
            "other_count": summary.get("other_count", 0),
            "total": summary.get("total", 0),
            "counters": summary.get("counters", {}),
            "urgent": summary.get("urgent", True),
        }
        payload["today"] = summary["today"]
        payload["mine"]["urgent_milestones"] = len(urgent)
    else:
        payload["milestones"] = {"denied": True}

    if "organisation" in enabled:
        payload["tasks"] = tasks.open_due_soon(ctx, person, within_days=30, limit=15)
        mine_tasks = tasks.open_due_soon(
            ctx, person, within_days=30, limit=10, assignee_id=person["id"],
        )
        payload["mine"]["tasks"] = mine_tasks
        payload["mine"]["task_count"] = len(mine_tasks)

    if "calendrier" in enabled:
        payload["events"] = events.upcoming(ctx, person, within_days=30, limit=15)

    if "finances" in enabled:
        from . import finance
        finance.seed_defaults(ctx, person)
        balances = finance.person_balances(ctx, person, currency="CHF")
        payload["finance_balances"] = balances
        mine_entry = next(
            (item for item in balances.get("entries", []) if item["person_id"] == person["id"]),
            None,
        )
        payload["mine"]["balance"] = mine_entry

    if "inventaire" in enabled:
        from . import inventory
        payload["warranties"] = inventory.upcoming_warranties(ctx, person, within_days=90, limit=10)

    if "mediatheque" in enabled:
        from . import media
        media_dash = media.dashboard(ctx, person)
        payload["media"] = media_dash
        payload["mine"]["media_in_progress"] = media_dash.get("in_progress") or []

    return payload
