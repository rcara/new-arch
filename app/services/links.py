"""Liens typés cross-module avec contrôle d'existence et d'ACL."""

import sqlite3

from ..audit import audit
from ..clock import iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from .milestones import require_index

ALLOWED_TYPES = frozenset({
    "milestone", "decision", "stored_file", "person", "task", "calendar_event",
    "inventory_item", "inventory_place", "finance_transaction",
})
ALLOWED_RELATIONS = frozenset({
    "relates_to",
    "documents",
    "depends_on",
    "concerns",
    "follows",
    "supports",
    "purchased_via",
    "warranty_deadline",
})


def _like_person(conn, person_id):
    row = conn.execute(
        "SELECT id, display_name, active FROM person WHERE id=? AND household_id=1",
        (person_id,),
    ).fetchone()
    return row


def can_see_object(ctx, person, object_type, object_id):
    """True si l'acteur peut connaître l'existence de l'objet (sans contenu sensible)."""
    if object_type not in ALLOWED_TYPES:
        return False
    if object_type == "person":
        return _like_person(ctx.conn, object_id) is not None
    if object_type == "milestone":
        if not person.get("can_view_index"):
            return False
        row = ctx.conn.execute(
            "SELECT id FROM milestone WHERE id=? AND household_id=1", (object_id,)
        ).fetchone()
        return row is not None
    if object_type == "decision":
        row = ctx.conn.execute(
            """SELECT d.id, d.author_id FROM decision d
               JOIN milestone m ON m.id=d.milestone_id
               WHERE d.id=? AND m.household_id=1""",
            (object_id,),
        ).fetchone()
        if row is None:
            return False
        if row["author_id"] == person["id"] or person.get("is_principal"):
            return True
        granted = ctx.conn.execute(
            "SELECT 1 FROM decision_access WHERE decision_id=? AND person_id=?",
            (object_id, person["id"]),
        ).fetchone()
        return granted is not None
    if object_type == "stored_file":
        row = ctx.conn.execute(
            """SELECT f.id, f.uploaded_by FROM stored_file f
               JOIN milestone m ON m.id=f.milestone_id
               WHERE f.id=? AND m.household_id=1""",
            (object_id,),
        ).fetchone()
        if row is None:
            return False
        if row["uploaded_by"] == person["id"] or person.get("is_principal"):
            return True
        granted = ctx.conn.execute(
            "SELECT 1 FROM file_access WHERE file_id=? AND person_id=?",
            (object_id, person["id"]),
        ).fetchone()
        return granted is not None
    if object_type == "task":
        row = ctx.conn.execute(
            "SELECT id FROM task WHERE id=? AND household_id=1 AND archived=0",
            (object_id,),
        ).fetchone()
        return row is not None
    if object_type == "calendar_event":
        row = ctx.conn.execute(
            "SELECT id FROM calendar_event WHERE id=? AND household_id=1 AND archived=0",
            (object_id,),
        ).fetchone()
        return row is not None
    if object_type == "inventory_place":
        row = ctx.conn.execute(
            "SELECT id FROM inventory_place WHERE id=? AND household_id=1 AND archived=0",
            (object_id,),
        ).fetchone()
        return row is not None
    if object_type == "inventory_item":
        row = ctx.conn.execute(
            """SELECT id, visibility, created_by FROM inventory_item
               WHERE id=? AND household_id=1 AND archived=0""",
            (object_id,),
        ).fetchone()
        if row is None:
            return False
        if person.get("is_principal") or row["visibility"] == "household" or row["created_by"] == person["id"]:
            return True
        owned = ctx.conn.execute(
            "SELECT 1 FROM inventory_item_owner WHERE item_id=? AND person_id=?",
            (object_id, person["id"]),
        ).fetchone()
        return owned is not None
    if object_type == "finance_transaction":
        row = ctx.conn.execute(
            """SELECT id, visibility, created_by, payer_id, beneficiary_id FROM finance_transaction
               WHERE id=? AND household_id=1 AND archived=0""",
            (object_id,),
        ).fetchone()
        if row is None:
            return False
        if person.get("is_principal") or row["visibility"] == "household":
            return True
        if row["created_by"] == person["id"] or row["payer_id"] == person["id"] or row["beneficiary_id"] == person["id"]:
            return True
        split = ctx.conn.execute(
            "SELECT 1 FROM finance_split WHERE transaction_id=? AND person_id=?",
            (object_id, person["id"]),
        ).fetchone()
        return split is not None
    return False


def require_object(ctx, person, object_type, object_id):
    if not can_see_object(ctx, person, object_type, object_id):
        raise AppError(404, "not_found", "Objet introuvable.")


def create_link(ctx, person, data):
    require_household(ctx.conn)
    source_type = str(data.get("source_type") or "").strip()
    target_type = str(data.get("target_type") or "").strip()
    relation_type = str(data.get("relation_type") or "relates_to").strip()
    try:
        source_id = int(data.get("source_id"))
        target_id = int(data.get("target_id"))
    except (TypeError, ValueError):
        raise AppError(400, "validation", "Identifiants invalides.", {
            "source_id": "Identifiant source invalide.",
            "target_id": "Identifiant cible invalide.",
        })
    if source_type not in ALLOWED_TYPES or target_type not in ALLOWED_TYPES:
        raise AppError(400, "validation", "Type d'objet inconnu.", {
            "source_type": "Type source inconnu." if source_type not in ALLOWED_TYPES else "",
            "target_type": "Type cible inconnu." if target_type not in ALLOWED_TYPES else "",
        })
    if relation_type not in ALLOWED_RELATIONS:
        raise AppError(400, "validation", "Relation inconnue.", {"relation_type": "Relation inconnue."})
    if source_type == target_type and source_id == target_id:
        raise AppError(400, "validation", "Un objet ne peut pas se lier à lui-même.")
    require_object(ctx, person, source_type, source_id)
    require_object(ctx, person, target_type, target_id)
    moment = iso_utc(ctx.clock.now())
    try:
        with write_tx(ctx):
            ctx.conn.execute(
                """INSERT INTO object_link(
                     household_id, source_type, source_id, target_type, target_id,
                     relation_type, created_by, created_at, archived
                   ) VALUES(1,?,?,?,?,?,?,?,0)""",
                (source_type, source_id, target_type, target_id, relation_type, person["id"], moment),
            )
            link_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        raise AppError(409, "conflict", "Ce lien existe déjà.")
    audit(ctx.home, ctx.clock, "link_create", "ok", person["id"], "object_link", link_id)
    return link_id


def archive_link(ctx, person, link_id):
    require_household(ctx.conn)
    row = ctx.conn.execute(
        """SELECT id, household_id, source_type, source_id, target_type, target_id,
                  relation_type, created_by, created_at, archived
           FROM object_link WHERE id=? AND household_id=1 AND archived=0""",
        (link_id,),
    ).fetchone()
    if row is None:
        raise AppError(404, "not_found", "Lien introuvable.")
    require_object(ctx, person, row["source_type"], row["source_id"])
    require_object(ctx, person, row["target_type"], row["target_id"])
    with write_tx(ctx):
        ctx.conn.execute("UPDATE object_link SET archived=1 WHERE id=?", (link_id,))
    audit(ctx.home, ctx.clock, "link_archive", "ok", person["id"], "object_link", link_id)


def list_links(ctx, person, *, source_type="", source_id=None, target_type="", target_id=None):
    require_household(ctx.conn)
    where = ["household_id=1", "archived=0"]
    params = {}
    if source_type:
        where.append("source_type=:source_type")
        params["source_type"] = source_type
    if source_id is not None:
        where.append("source_id=:source_id")
        params["source_id"] = int(source_id)
    if target_type:
        where.append("target_type=:target_type")
        params["target_type"] = target_type
    if target_id is not None:
        where.append("target_id=:target_id")
        params["target_id"] = int(target_id)
    rows = ctx.conn.execute(
        f"""SELECT id, household_id, source_type, source_id, target_type, target_id,
                   relation_type, created_by, created_at, archived
            FROM object_link WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 200""",
        params,
    ).fetchall()
    items = []
    for row in rows:
        if not can_see_object(ctx, person, row["source_type"], row["source_id"]):
            continue
        if not can_see_object(ctx, person, row["target_type"], row["target_id"]):
            continue
        items.append({
            "id": row["id"],
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "relation_type": row["relation_type"],
            "created_at": row["created_at"],
        })
    return {"items": items}


# Imported for side-effect typing; keep require_index available to callers that need Index.
_ = require_index
