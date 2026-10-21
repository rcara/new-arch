"""Multi-foyer : appartenances, bascule et création."""

import sqlite3

from ..audit import audit
from ..clock import iso_utc
from ..db import require_household, write_tx
from ..errors import AppError
from ..security import hash_token
from ..tenancy import hh
from ..validate import text_value, timezone_name
from .modules import DEFAULT_MODULES, ensure_seeded


def list_memberships(ctx):
    """Foyers accessibles pour le compte de connexion courant."""
    login_id = getattr(ctx, "login_person_id", None) or ctx.actor_id
    if not login_id:
        return []
    rows = ctx.conn.execute(
        """SELECT m.household_id, m.person_id, h.name AS household_name, h.timezone,
                  p.display_name, p.is_principal
           FROM household_membership m
           JOIN household h ON h.id=m.household_id
           JOIN person p ON p.id=m.person_id
           WHERE m.login_person_id=? AND p.active=1
           ORDER BY h.id""",
        (login_id,),
    ).fetchall()
    current = hh(ctx)
    return [
        {
            "household_id": row["household_id"],
            "person_id": row["person_id"],
            "household_name": row["household_name"],
            "timezone": row["timezone"],
            "display_name": row["display_name"],
            "is_principal": bool(row["is_principal"]),
            "active": row["household_id"] == current,
        }
        for row in rows
    ]


def switch_household(ctx, session_token, household_id):
    """Active la persona du foyer cible pour la session courante."""
    if not session_token:
        raise AppError(401, "unauthorized", "Connexion requise.")
    try:
        household_id = int(household_id)
    except (TypeError, ValueError):
        raise AppError(400, "validation", "Foyer invalide.", {"household_id": "Invalide."})
    login_id = getattr(ctx, "login_person_id", None) or ctx.actor_id
    if not login_id:
        raise AppError(401, "unauthorized", "Connexion requise.")
    require_household(ctx.conn, household_id)
    row = ctx.conn.execute(
        """SELECT m.person_id, p.active
           FROM household_membership m
           JOIN person p ON p.id=m.person_id
           WHERE m.login_person_id=? AND m.household_id=?""",
        (login_id, household_id),
    ).fetchone()
    if row is None or not row["active"]:
        raise AppError(403, "forbidden", "Ce foyer n'est pas accessible.")
    if household_id == hh(ctx) and row["person_id"] == ctx.actor_id:
        return {"household_id": household_id, "person_id": row["person_id"]}
    with write_tx(ctx):
        ctx.conn.execute(
            """UPDATE session SET person_id=?
               WHERE token_hash=? AND login_person_id=? AND revoked_at IS NULL""",
            (row["person_id"], hash_token(session_token), login_id),
        )
        if ctx.conn.total_changes == 0:
            raise AppError(401, "unauthorized", "Connexion requise.")
    audit(ctx.home, ctx.clock, "household_switch", "ok", login_id, "household", household_id)
    return {"household_id": household_id, "person_id": row["person_id"]}


def create_household(ctx, household_name, timezone, display_name):
    """Crée un foyer supplémentaire pour le compte connecté (sans nouvel identifiant)."""
    login_id = getattr(ctx, "login_person_id", None) or ctx.actor_id
    if not login_id:
        raise AppError(401, "unauthorized", "Connexion requise.")
    account = ctx.conn.execute(
        "SELECT person_id FROM account WHERE person_id=?",
        (login_id,),
    ).fetchone()
    if account is None:
        raise AppError(403, "forbidden", "Seul un compte peut créer un foyer.")
    household_name = text_value(household_name, "household_name", 120, required=True, label="Le nom du foyer")
    timezone = timezone_name(timezone or "Europe/Zurich")
    display_name = text_value(display_name, "display_name", 120, required=True, label="Votre nom")
    moment = iso_utc(ctx.clock.now())
    try:
        with write_tx(ctx):
            ctx.conn.execute(
                "INSERT INTO household(name, timezone, created_at) VALUES(?,?,?)",
                (household_name, timezone, moment),
            )
            household_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            ctx.conn.execute(
                """INSERT INTO person(household_id, display_name, relationship, is_principal, active,
                   can_view_index, created_at) VALUES(?,?, '', 1, 1, 1, ?)""",
                (household_id, display_name, moment),
            )
            person_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            ctx.conn.execute(
                """INSERT INTO household_membership(login_person_id, household_id, person_id, created_at)
                   VALUES(?,?,?,?)""",
                (login_id, household_id, person_id, moment),
            )
            ensure_seeded(ctx.conn, household_id)
            for key, enabled in DEFAULT_MODULES:
                ctx.conn.execute(
                    "INSERT OR IGNORE INTO module_setting(household_id, module_key, enabled) VALUES(?,?,?)",
                    (household_id, key, enabled),
                )
    except sqlite3.IntegrityError:
        raise AppError(409, "conflict", "Impossible de créer ce foyer.")
    audit(ctx.home, ctx.clock, "household_create", "ok", login_id, "household", household_id)
    return {
        "household_id": household_id,
        "person_id": person_id,
        "household_name": household_name,
        "timezone": timezone,
        "display_name": display_name,
    }
