"""Recherche transversale filtrée par permissions."""

from ..db import require_household
from ..errors import AppError
from ..validate import text_value
from .links import can_see_object
from .modules import enabled_keys, require_module
from .milestones import require_index
from ..tenancy import hh


def search(ctx, person, q, *, limit=40):
    require_module(ctx, "recherche")
    require_household(ctx.conn, hh(ctx))
    query = text_value(q, "q", 120, required=True, label="La recherche")
    if len(query) < 2:
        raise AppError(400, "validation", "Saisissez au moins 2 caractères.", {"q": "Trop court."})
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    items = []
    # Un module désactivé renvoie 404 : ses éléments ne doivent pas apparaître.
    enabled = enabled_keys(ctx)

    if person.get("can_view_index") and "reperes" in enabled:
        rows = ctx.conn.execute(
            f"""SELECT id, name FROM milestone
               WHERE household_id={hh(ctx)} AND archived=0 AND name LIKE ? ESCAPE '\\'
               ORDER BY id DESC LIMIT ?""",
            (like, limit),
        ).fetchall()
        for row in rows:
            items.append({"type": "milestone", "id": row["id"], "title": row["name"], "href": f"/reperes/{row['id']}"})

    rows = [] if "organisation" not in enabled else ctx.conn.execute(
        f"""SELECT id, title FROM task
           WHERE household_id={hh(ctx)} AND archived=0 AND title LIKE ? ESCAPE '\\'
           ORDER BY id DESC LIMIT ?""",
        (like, limit),
    ).fetchall()
    for row in rows:
        items.append({"type": "task", "id": row["id"], "title": row["title"], "href": f"/organisation/{row['id']}"})

    rows = [] if "calendrier" not in enabled else ctx.conn.execute(
        f"""SELECT id, title FROM calendar_event
           WHERE household_id={hh(ctx)} AND archived=0 AND title LIKE ? ESCAPE '\\'
           ORDER BY id DESC LIMIT ?""",
        (like, limit),
    ).fetchall()
    for row in rows:
        items.append({"type": "calendar_event", "id": row["id"], "title": row["title"], "href": f"/calendrier/{row['id']}"})

    # Décisions : titre = choix uniquement si accessible ; jamais le corps expected/reconsider
    rows = [] if "decisions" not in enabled else ctx.conn.execute(
        f"""SELECT d.id, d.choice, d.author_id, d.sealed_at FROM decision d
           JOIN milestone m ON m.id=d.milestone_id
           WHERE m.household_id={hh(ctx)} AND d.choice LIKE ? ESCAPE '\\'
           ORDER BY d.id DESC LIMIT ?""",
        (like, limit),
    ).fetchall()
    for row in rows:
        if not can_see_object(ctx, person, "decision", row["id"]):
            continue
        title = (row["choice"] or "").strip() or ("Décision scellée" if row["sealed_at"] else "Brouillon")
        items.append({"type": "decision", "id": row["id"], "title": title, "href": f"/decisions/{row['id']}"})

    # Fichiers : existence seule, jamais le nom original dans la recherche globale
    rows = ctx.conn.execute(
        f"""SELECT f.id FROM stored_file f
           JOIN milestone m ON m.id=f.milestone_id
           WHERE m.household_id={hh(ctx)}
           ORDER BY f.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    for row in rows:
        if not can_see_object(ctx, person, "stored_file", row["id"]):
            continue
        # Ne pas matcher sur original_name pour éviter fuite ; on n'ajoute que si q vide... skip files in text search
        # Intentionnel : la recherche ne révèle pas les noms de fichiers.

    # Personnes (foyer)
    if person.get("is_principal") and "foyer" in enabled:
        rows = ctx.conn.execute(
            f"""SELECT id, display_name FROM person
               WHERE household_id={hh(ctx)} AND active=1 AND display_name LIKE ? ESCAPE '\\'
               ORDER BY id LIMIT ?""",
            (like, limit),
        ).fetchall()
        for row in rows:
            items.append({"type": "person", "id": row["id"], "title": row["display_name"], "href": "/foyer"})

    rows = [] if "inventaire" not in enabled else ctx.conn.execute(
        f"""SELECT id, name, visibility, created_by FROM inventory_item
           WHERE household_id={hh(ctx)} AND archived=0 AND name LIKE ? ESCAPE '\\'
           ORDER BY id DESC LIMIT ?""",
        (like, limit),
    ).fetchall()
    for row in rows:
        if not can_see_object(ctx, person, "inventory_item", row["id"]):
            continue
        items.append({
            "type": "inventory_item",
            "id": row["id"],
            "title": row["name"],
            "href": f"/inventaire/{row['id']}",
        })

    rows = [] if "mediatheque" not in enabled else ctx.conn.execute(
        f"""SELECT id, title FROM media_work
           WHERE household_id={hh(ctx)} AND archived=0 AND title LIKE ? ESCAPE '\\'
           ORDER BY id DESC LIMIT ?""",
        (like, limit),
    ).fetchall()
    for row in rows:
        if not can_see_object(ctx, person, "media_work", row["id"]):
            continue
        items.append({
            "type": "media_work",
            "id": row["id"],
            "title": row["title"],
            "href": f"/mediatheque/oeuvres/{row['id']}",
        })

    return {"q": query, "items": items[:limit], "total": min(len(items), limit)}


# keep import used for potential callers needing index gate
_ = require_index
