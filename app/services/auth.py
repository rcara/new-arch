"""Bootstrap, connexion, sessions."""

import sqlite3

from ..audit import audit
from ..clock import iso_utc
from ..db import household_row, write_tx
from ..errors import AppError
from ..security import SESSION_HOURS, hash_password, hash_token, needs_rehash, new_token, verify_password
from ..validate import password_value, text_value, timezone_name, username_value

AUTH_FAILURE = "Identifiant ou mot de passe incorrect."
RATE_LIMITED = "Trop de tentatives. Réessayez plus tard."


def require_principal(person):
    if not person or not person["is_principal"]:
        raise AppError(403, "forbidden", "Action réservée au compte principal.")


def profile(person):
    return {
        "display_name": person["display_name"],
        "role": "principal" if person["is_principal"] else "secondaire",
        "can_view_index": bool(person["can_view_index"]),
        "person_id": person["id"],
    }


def bootstrap(ctx, limiter, household_name, timezone, display_name, username, password, failpoint=None):
    household_name = text_value(household_name, "household_name", 120, required=True, label="Le nom du foyer")
    timezone = timezone_name(timezone)
    display_name = text_value(display_name, "display_name", 120, required=True, label="Votre nom")
    username = username_value(username)
    password = password_value(password)
    password_hash = hash_password(password)
    token = new_token()
    csrf = new_token()
    moment = iso_utc(ctx.clock.now())
    expires = iso_utc(_plus_hours(ctx))
    try:
        with write_tx(ctx):
            if household_row(ctx.conn) is not None:
                raise AppError(409, "conflict", "Le foyer existe déjà.")
            ctx.conn.execute(
                "INSERT INTO household(id, name, timezone, created_at) VALUES(1,?,?,?)",
                (household_name, timezone, moment),
            )
            if failpoint == "after_household":
                raise RuntimeError("storage")
            ctx.conn.execute(
                """INSERT INTO person(household_id, display_name, relationship, is_principal, active,
                   can_view_index, created_at) VALUES(1,?, '', 1, 1, 1, ?)""",
                (display_name, moment),
            )
            person_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            ctx.conn.execute(
                "INSERT INTO account(person_id, username, password_hash, created_at) VALUES(?,?,?,?)",
                (person_id, username, password_hash, moment),
            )
            ctx.conn.execute(
                """INSERT INTO session(token_hash, person_id, expires_at, revoked_at, csrf_token)
                   VALUES(?,?,?,NULL,?)""",
                (hash_token(token), person_id, expires, csrf),
            )
    except sqlite3.IntegrityError:
        raise AppError(409, "conflict", "Le foyer existe déjà.")
    audit(ctx.home, ctx.clock, "bootstrap", "ok", person_id, "person", person_id)
    person = {
        "id": person_id,
        "display_name": display_name,
        "is_principal": 1,
        "can_view_index": 1,
    }
    return token, csrf, profile(person)


def _plus_hours(ctx):
    from datetime import timedelta
    return ctx.clock.now() + timedelta(hours=SESSION_HOURS)


def open_session(ctx, limiter, username, password):
    if not isinstance(username, str) or not isinstance(password, str):
        raise AppError(401, "unauthorized", AUTH_FAILURE)
    username = username.strip()
    key = username.casefold()
    if limiter.too_many(key):
        audit(ctx.home, ctx.clock, "login", "limited")
        raise AppError(401, "unauthorized", RATE_LIMITED)
    if not username or len(username) > 80 or any(ch.isspace() for ch in username) or not password or len(password) > 128:
        limiter.add(key)
        raise AppError(401, "unauthorized", AUTH_FAILURE)
    row = ctx.conn.execute(
        """SELECT a.person_id, a.password_hash, p.display_name, p.is_principal, p.can_view_index, p.active
           FROM account a JOIN person p ON p.id=a.person_id
           WHERE a.username=? COLLATE NOCASE""",
        (username,),
    ).fetchone()
    stored = row["password_hash"] if row else ctx.dummy_hash
    password_ok = verify_password(stored, password)
    if row is None or not row["active"] or not password_ok:
        limiter.add(key)
        audit(ctx.home, ctx.clock, "login", "denied")
        raise AppError(401, "unauthorized", AUTH_FAILURE)
    token = new_token()
    csrf = new_token()
    moment = iso_utc(ctx.clock.now())
    expires = iso_utc(_plus_hours(ctx))
    with write_tx(ctx):
        if needs_rehash(row["password_hash"]):
            ctx.conn.execute(
                "UPDATE account SET password_hash=? WHERE person_id=?",
                (hash_password(password), row["person_id"]),
            )
        ctx.conn.execute(
            "UPDATE session SET revoked_at=? WHERE person_id=? AND revoked_at IS NULL",
            (moment, row["person_id"]),
        )
        ctx.conn.execute(
            """INSERT INTO session(token_hash, person_id, expires_at, revoked_at, csrf_token)
               VALUES(?,?,?,NULL,?)""",
            (hash_token(token), row["person_id"], expires, csrf),
        )
    limiter.clear_user(key)
    audit(ctx.home, ctx.clock, "login", "ok", row["person_id"], "person", row["person_id"])
    person = {
        "id": row["person_id"],
        "display_name": row["display_name"],
        "is_principal": row["is_principal"],
        "can_view_index": row["can_view_index"],
    }
    return token, csrf, profile(person)


def close_session(ctx, token):
    if not token:
        return
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            "UPDATE session SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
            (moment, hash_token(token)),
        )
    audit(ctx.home, ctx.clock, "logout", "ok", getattr(ctx, "actor_id", None))


def load_session(conn, clock, token):
    if not token:
        return None
    row = conn.execute(
        """SELECT s.csrf_token, s.expires_at, s.revoked_at,
                  p.id, p.display_name, p.is_principal, p.can_view_index, p.active, p.relationship
           FROM session s JOIN person p ON p.id=s.person_id
           WHERE s.token_hash=?""",
        (hash_token(token),),
    ).fetchone()
    if row is None or row["revoked_at"] or not row["active"] or not row["csrf_token"]:
        return None
    from ..clock import parse_utc
    if parse_utc(row["expires_at"]) <= clock.now():
        return None
    return row
