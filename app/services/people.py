"""Personnes, comptes locaux et trois droits indépendants."""

import sqlite3
from ..tenancy import hh

from .auth import require_principal
from ..audit import audit
from ..clock import iso_utc
from ..db import write_tx
from ..errors import AppError
from ..security import hash_password
from ..validate import password_value, text_value, username_value


def list_people(ctx, person):
    require_principal(person)
    rows = ctx.conn.execute(
        """SELECT p.id, p.display_name, p.relationship, p.is_principal, p.active, p.can_view_index,
                  a.username IS NOT NULL AS has_account
           FROM person p LEFT JOIN account a ON a.person_id=p.id
           ORDER BY p.is_principal DESC, p.id"""
    ).fetchall()
    return [_public_person(row) for row in rows]


def list_active_members(ctx, person):
    """Membres actifs (noms seulement) — accessible à tout compte connecté."""
    if person is None:
        raise AppError(401, "unauthorized", "Connexion requise.")
    rows = ctx.conn.execute(
        f"""SELECT id, display_name, active FROM person
           WHERE household_id={hh(ctx)} AND active=1 ORDER BY is_principal DESC, id"""
    ).fetchall()
    return [{"id": row["id"], "display_name": row["display_name"], "active": True} for row in rows]


def _public_person(row):
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "relationship": row["relationship"],
        "is_principal": bool(row["is_principal"]),
        "active": bool(row["active"]),
        "can_view_index": bool(row["can_view_index"]),
        "has_account": bool(row["has_account"]),
    }


def _target_account(conn, person_id):
    row = conn.execute(
        """SELECT p.id, p.is_principal, p.active, p.can_view_index, a.person_id AS account_id
           FROM person p LEFT JOIN account a ON a.person_id=p.id
           WHERE p.id=?""",
        (person_id,),
    ).fetchone()
    if row is None:
        raise AppError(404, "not_found", "Introuvable.")
    if row["is_principal"] or not row["active"] or row["account_id"] is None:
        raise AppError(409, "conflict", "Les accès se règlent pour un compte secondaire actif.")
    return row


def add_person(ctx, person, display_name, relationship="", username=None, password=None):
    require_principal(person)
    display_name = text_value(display_name, "display_name", 120, required=True, label="Le nom")
    relationship = text_value(relationship or "", "relationship", 120, label="Le lien de parenté")
    create_account = bool(username or password)
    if create_account:
        username = username_value(username or "")
        password = password_value(password or "")
        password_hash = hash_password(password)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO person(household_id, display_name, relationship, is_principal, active,
               can_view_index, created_at) VALUES({hh(ctx)},?,?,0,1,1,?)""",
            (display_name, relationship, moment),
        )
        new_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if create_account:
            try:
                ctx.conn.execute(
                    "INSERT INTO account(person_id, username, password_hash, created_at) VALUES(?,?,?,?)",
                    (new_id, username, password_hash, moment),
                )
                ctx.conn.execute(
                    """INSERT INTO household_membership(login_person_id, household_id, person_id, created_at)
                       VALUES(?,?,?,?)""",
                    (new_id, hh(ctx), new_id, moment),
                )
            except sqlite3.IntegrityError:
                raise AppError(409, "conflict", "Cet identifiant est déjà utilisé.")
    audit(ctx.home, ctx.clock, "person_add", "ok", person["id"], "person", new_id)
    return new_id


def update_person(ctx, person, person_id, display_name, relationship):
    require_principal(person)
    display_name = text_value(display_name, "display_name", 120, required=True, label="Le nom")
    relationship = text_value(relationship or "", "relationship", 120, label="Le lien de parenté")
    with write_tx(ctx):
        row = ctx.conn.execute("SELECT id, is_principal FROM person WHERE id=?", (person_id,)).fetchone()
        if row is None:
            raise AppError(404, "not_found", "Introuvable.")
        ctx.conn.execute(
            "UPDATE person SET display_name=?, relationship=? WHERE id=?",
            (display_name, relationship, person_id),
        )
    audit(ctx.home, ctx.clock, "person_update", "ok", person["id"], "person", person_id)


def create_account(ctx, person, person_id, username, password):
    require_principal(person)
    username = username_value(username)
    password = password_value(password)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        row = ctx.conn.execute(
            """SELECT p.id, p.active, p.is_principal, a.person_id AS account_id
               FROM person p LEFT JOIN account a ON a.person_id=p.id WHERE p.id=?""",
            (person_id,),
        ).fetchone()
        if row is None:
            raise AppError(404, "not_found", "Introuvable.")
        if not row["active"]:
            raise AppError(409, "conflict", "Cette personne est retirée du foyer.")
        if row["account_id"] is not None:
            raise AppError(409, "conflict", "Cette personne a déjà un compte.")
        try:
            ctx.conn.execute(
                "INSERT INTO account(person_id, username, password_hash, created_at) VALUES(?,?,?,?)",
                (person_id, username, hash_password(password), moment),
            )
            ctx.conn.execute(
                """INSERT INTO household_membership(login_person_id, household_id, person_id, created_at)
                   VALUES(?,?,?,?)""",
                (person_id, hh(ctx), person_id, moment),
            )
        except sqlite3.IntegrityError:
            raise AppError(409, "conflict", "Cet identifiant est déjà utilisé.")
    audit(ctx.home, ctx.clock, "account_create", "ok", person["id"], "person", person_id)


def deactivate_person(ctx, person, person_id, confirm):
    require_principal(person)
    if confirm is not True:
        raise AppError(400, "validation", "Le retrait doit être confirmé.", {"confirm": "Confirmation requise."})
    if person_id == person["id"]:
        raise AppError(409, "conflict", "Le compte principal reste actif.")
    with write_tx(ctx):
        row = ctx.conn.execute(
            "SELECT id, is_principal, active FROM person WHERE id=?",
            (person_id,),
        ).fetchone()
        if row is None:
            raise AppError(404, "not_found", "Introuvable.")
        if row["is_principal"]:
            raise AppError(409, "conflict", "Le compte principal reste actif.")
        if row["active"]:
            try:
                ctx.conn.execute("UPDATE person SET active=0 WHERE id=? AND is_principal=0", (person_id,))
            except sqlite3.IntegrityError:
                raise AppError(409, "conflict", "Le compte principal reste actif.")
    audit(ctx.home, ctx.clock, "person_deactivate", "ok", person["id"], "person", person_id)


def set_index_access(ctx, person, person_id, allowed):
    require_principal(person)
    if not isinstance(allowed, bool):
        raise AppError(400, "validation", "Valeur d'accès invalide.", {"allowed": "Indiquez vrai ou faux."})
    with write_tx(ctx):
        _target_account(ctx.conn, person_id)
        ctx.conn.execute("UPDATE person SET can_view_index=? WHERE id=?", (1 if allowed else 0, person_id))
    audit(ctx.home, ctx.clock, "index_access", "ok", person["id"], "person", person_id)


def grant_decision(ctx, person, person_id, decision_id):
    _change_decision(ctx, person, person_id, decision_id, grant=True)


def revoke_decision(ctx, person, person_id, decision_id):
    _change_decision(ctx, person, person_id, decision_id, grant=False)


def _change_decision(ctx, person, person_id, decision_id, grant):
    require_principal(person)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        _target_account(ctx.conn, person_id)
        found = ctx.conn.execute("SELECT id FROM decision WHERE id=?", (decision_id,)).fetchone()
        if found is None:
            raise AppError(404, "not_found", "Introuvable.")
        if grant:
            ctx.conn.execute(
                """INSERT OR IGNORE INTO decision_access(decision_id, person_id, granted_by, granted_at)
                   VALUES(?,?,?,?)""",
                (decision_id, person_id, person["id"], moment),
            )
        else:
            ctx.conn.execute(
                "DELETE FROM decision_access WHERE decision_id=? AND person_id=?",
                (decision_id, person_id),
            )
    audit(ctx.home, ctx.clock, "decision_access", "ok", person["id"], "decision", decision_id)


def grant_file(ctx, person, person_id, file_id):
    _change_file(ctx, person, person_id, file_id, grant=True)


def revoke_file(ctx, person, person_id, file_id):
    _change_file(ctx, person, person_id, file_id, grant=False)


def _change_file(ctx, person, person_id, file_id, grant):
    require_principal(person)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        _target_account(ctx.conn, person_id)
        found = ctx.conn.execute("SELECT id FROM stored_file WHERE id=?", (file_id,)).fetchone()
        if found is None:
            raise AppError(404, "not_found", "Introuvable.")
        if grant:
            ctx.conn.execute(
                """INSERT OR IGNORE INTO file_access(file_id, person_id, granted_by, granted_at)
                   VALUES(?,?,?,?)""",
                (file_id, person_id, person["id"], moment),
            )
        else:
            ctx.conn.execute(
                "DELETE FROM file_access WHERE file_id=? AND person_id=?",
                (file_id, person_id),
            )
    audit(ctx.home, ctx.clock, "file_access", "ok", person["id"], "file", file_id)


def access_state(ctx, person, person_id):
    require_principal(person)
    target = _target_account(ctx.conn, person_id)
    decisions = ctx.conn.execute(
        """SELECT d.id, d.created_at, m.name AS milestone_name,
                  EXISTS(SELECT 1 FROM decision_access a WHERE a.decision_id=d.id AND a.person_id=?) AS granted
           FROM decision d JOIN milestone m ON m.id=d.milestone_id
           ORDER BY d.created_at, d.id""",
        (person_id,),
    ).fetchall()
    files = ctx.conn.execute(
        """SELECT f.id, f.original_name,
                  EXISTS(SELECT 1 FROM file_access a WHERE a.file_id=f.id AND a.person_id=?) AS granted
           FROM stored_file f ORDER BY f.created_at, f.id""",
        (person_id,),
    ).fetchall()
    return {
        "person_id": person_id,
        "can_view_index": bool(target["can_view_index"]),
        "decisions": [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "milestone_name": row["milestone_name"],
                "granted": bool(row["granted"]),
            }
            for row in decisions
        ],
        "files": [
            {"id": row["id"], "original_name": row["original_name"], "granted": bool(row["granted"])}
            for row in files
        ],
    }


def apply_access_form(ctx, person, person_id, index_allowed, decision_ids, file_ids):
    """Enregistre chaque écart comme un accord ou une révocation explicite."""
    require_principal(person)
    state = access_state(ctx, person, person_id)
    wanted_decisions = set(decision_ids)
    wanted_files = set(file_ids)
    known_decisions = {item["id"] for item in state["decisions"]}
    known_files = {item["id"] for item in state["files"]}
    if not wanted_decisions <= known_decisions or not wanted_files <= known_files:
        raise AppError(404, "not_found", "Introuvable.")
    if index_allowed != state["can_view_index"]:
        set_index_access(ctx, person, person_id, index_allowed)
    for item in state["decisions"]:
        if item["granted"] and item["id"] not in wanted_decisions:
            revoke_decision(ctx, person, person_id, item["id"])
        elif not item["granted"] and item["id"] in wanted_decisions:
            grant_decision(ctx, person, person_id, item["id"])
    for item in state["files"]:
        if item["granted"] and item["id"] not in wanted_files:
            revoke_file(ctx, person, person_id, item["id"])
        elif not item["granted"] and item["id"] in wanted_files:
            grant_file(ctx, person, person_id, item["id"])
