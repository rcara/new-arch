"""Accueil transversal alimenté par données réelles."""

from ..clock import civil_today
from ..db import require_household
from . import events, milestones, modules, tasks


def dashboard(ctx, person):
    household = require_household(ctx.conn)
    enabled = modules.enabled_keys(ctx)
    payload = {
        "household_name": household["name"],
        "timezone": household["timezone"],
        "today": civil_today(ctx.clock, household["timezone"]).isoformat(),
        "modules": sorted(enabled),
        "milestones": None,
        "tasks": [],
        "events": [],
    }

    if person.get("can_view_index"):
        summary = milestones.today_items(ctx, person)
        payload["milestones"] = {
            "today": summary["today"],
            "urgent_items": summary.get("urgent_items", []),
            "other_count": summary.get("other_count", 0),
            "total": summary.get("total", 0),
            "counters": summary.get("counters", {}),
            "urgent": summary.get("urgent", True),
        }
        payload["today"] = summary["today"]
    else:
        payload["milestones"] = {"denied": True}

    if "organisation" in enabled:
        payload["tasks"] = tasks.open_due_soon(ctx, person, within_days=30, limit=15)

    if "calendrier" in enabled:
        payload["events"] = events.upcoming(ctx, person, within_days=30, limit=15)

    if "finances" in enabled:
        from . import finance
        finance.seed_defaults(ctx, person)
        payload["finance_balances"] = finance.person_balances(ctx, person, currency="CHF")

    if "inventaire" in enabled:
        from . import inventory
        payload["warranties"] = inventory.upcoming_warranties(ctx, person, within_days=90, limit=10)

    return payload
