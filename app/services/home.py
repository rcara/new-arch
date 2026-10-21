"""Tableau de bord / Accueil transversal alimenté par données réelles."""

from datetime import date, timedelta

from ..clock import civil_today
from ..db import require_household
from ..money import CURRENCIES
from ..tenancy import hh
from . import auth, events, milestones, modules, tasks

AGENDA_DAYS = 14


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

    if "reperes" not in enabled:
        payload["milestones"] = None
    elif person.get("can_view_index"):
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

    _daily(ctx, person, enabled, payload)
    return payload


def _daily(ctx, person, enabled, payload):
    """Vues « vie quotidienne » de l'accueil, en lecture seule, sur les droits existants."""
    today = date.fromisoformat(payload["today"])
    horizon = (today + timedelta(days=AGENDA_DAYS)).isoformat()

    agenda = []
    for item in payload["events"]:
        if item["start_date"] <= horizon:
            agenda.append({
                "kind": "event", "id": item["id"], "title": item["title"], "date": item["start_date"],
                "end_date": item["end_date"], "who": item["responsible_name"],
                "occurrence": item["start_date"] if item["is_occurrence"] else None,
                "recurrence_label": item["recurrence_label"],
            })
    ms = payload.get("milestones") or {}
    for item in ms.get("urgent_items", []) if not ms.get("denied") else []:
        agenda.append({
            "kind": "milestone", "id": item["id"], "title": item["name"], "date": item["due_date"],
            "status": item["status"], "who": item.get("holder_name"),
        })
    agenda.sort(key=lambda entry: (entry["date"] or "9999", entry["kind"]))
    payload["agenda"] = {"items": agenda[:8], "days": AGENDA_DAYS, "more": max(0, len(agenda) - 8)}

    todo = {"mine": [], "shared": [], "overdue": 0, "enabled": "organisation" in enabled}
    if todo["enabled"]:
        todo["mine"] = payload["mine"]["tasks"][:6]
        todo["shared"] = [item for item in payload["tasks"] if item["assignee_id"] is None][:6]
        visible = {item["id"]: item for item in todo["mine"] + todo["shared"]}
        todo["overdue"] = sum(1 for item in visible.values() if item["due_date"] and item["due_date"] < payload["today"])
    payload["todo"] = todo

    if "finances" in enabled:
        from . import finance
        budgets = []
        balances = []
        for currency in sorted(CURRENCIES):
            listed = finance.list_budgets(ctx, person, year=today.year, month=today.month, currency=currency)
            budgets.extend(item for item in listed["items"] if item["period"] == "month")
            entries = finance.person_balances(ctx, person, currency=currency).get("entries", [])
            open_entries = [item for item in entries if item.get("net_minor")]
            if open_entries:
                balances.append({"currency": currency, "entries": open_entries})
        payload["finance_month"] = {
            "year": today.year,
            "month": today.month,
            "spending": finance.month_spending(ctx, person, year=today.year, month=today.month),
            "budgets": budgets,
            "balances": balances,
        }

    payload["recent"] = _recent(ctx, person, enabled)
    payload["onboarding"] = _onboarding(ctx, person, enabled)


def _recent(ctx, person, enabled):
    """Derniers ajouts visibles. Exclut coffre et décisions (contenus à accès individuel)."""
    entries = []
    if "organisation" in enabled:
        for row in ctx.conn.execute(
            f"SELECT id, title, created_at FROM task WHERE household_id={hh(ctx)} AND archived=0 ORDER BY created_at DESC, id DESC LIMIT 5"
        ):
            entries.append({"kind": "task", "id": row["id"], "title": row["title"], "at": row["created_at"]})
    if "calendrier" in enabled:
        for row in ctx.conn.execute(
            f"SELECT id, title, created_at FROM calendar_event WHERE household_id={hh(ctx)} AND archived=0 ORDER BY created_at DESC, id DESC LIMIT 5"
        ):
            entries.append({"kind": "event", "id": row["id"], "title": row["title"], "at": row["created_at"]})
    if "finances" in enabled:
        from . import finance
        for item in finance.list_transactions(ctx, person)["items"][:5]:
            entries.append({
                "kind": "transaction", "id": item["id"], "title": item["label"], "at": item["created_at"],
                "detail": item["amount_label"],
            })
    if "inventaire" in enabled:
        from . import inventory
        items = sorted(inventory.list_items(ctx, person)["items"], key=lambda item: item["created_at"], reverse=True)
        for item in items[:5]:
            entries.append({"kind": "item", "id": item["id"], "title": item["name"], "at": item["created_at"]})
    entries.sort(key=lambda entry: entry["at"] or "", reverse=True)
    return entries[:6]


def _count(ctx, sql):
    return ctx.conn.execute(sql).fetchone()[0]


def _onboarding(ctx, person, enabled):
    """Étapes de démarrage calculées sur l'état réel ; None quand tout est fait."""
    principal = bool(person.get("is_principal"))
    steps = [{"key": "foyer", "label": "Configurer mon foyer", "done": True, "endpoint": "pages.settings_get"}]
    if principal and "foyer" in enabled:
        steps.append({
            "key": "membre", "label": "Ajouter un membre", "endpoint": "pages.person_new",
            "done": _count(ctx, f"SELECT COUNT(*) FROM person WHERE household_id={hh(ctx)}") > 1,
        })
    if "finances" in enabled:
        steps.append({
            "key": "argent", "label": "Saisir une première dépense ou un budget", "endpoint": "pages.finance_expense_new",
            "done": _count(ctx, f"SELECT COUNT(*) FROM finance_transaction WHERE household_id={hh(ctx)}")
            + _count(ctx, f"SELECT COUNT(*) FROM finance_budget WHERE household_id={hh(ctx)}") > 0,
        })
    if "calendrier" in enabled:
        steps.append({
            "key": "evenement", "label": "Créer un événement", "endpoint": "pages.event_new",
            "done": _count(ctx, f"SELECT COUNT(*) FROM calendar_event WHERE household_id={hh(ctx)}") > 0,
        })
    if "inventaire" in enabled or ("coffre" in enabled and principal):
        steps.append({
            "key": "bien", "label": "Ajouter un bien ou un document",
            "endpoint": "pages.inventory_item_new" if "inventaire" in enabled else "pages.vault_get",
            "done": _count(ctx, f"SELECT COUNT(*) FROM inventory_item WHERE household_id={hh(ctx)}")
            + _count(ctx, "SELECT COUNT(*) FROM stored_file") > 0,
        })
    done = sum(1 for step in steps if step["done"])
    if done == len(steps):
        return None
    return {"steps": steps, "done": done, "total": len(steps)}
