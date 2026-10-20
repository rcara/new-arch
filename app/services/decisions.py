"""Décisions : brouillon, scellement irréversible, résultat unique."""

import json
import sqlite3

from .auth import require_principal
from ..audit import audit
from ..clock import iso_utc
from ..db import write_tx
from ..errors import AppError
from ..validate import NE_RIEN, normalize_options, normalize_rule, text_value

CHOICE_LIMIT = 1000
LONG_LIMIT = 2000


def _dump_options(options):
    return json.dumps(normalize_options(options), ensure_ascii=False)


def _dump_rule(rule):
    if rule is None:
        return None
    if not isinstance(rule, dict):
        raise AppError(400, "validation", "Règle invalide.", {"rule": "Règle invalide."})
    extra = set(rule) - {"name", "lines"}
    if extra:
        raise AppError(400, "validation", "Règle invalide.", {"rule": "Règle invalide."})
    normalized = normalize_rule(rule.get("name"), rule.get("lines"))
    if normalized is None:
        return None
    return json.dumps(normalized, ensure_ascii=False)


def _parts(fields):
    choice = text_value(fields.get("choice") or "", "choice", CHOICE_LIMIT, label="Le choix")
    expected = text_value(fields.get("expected") or "", "expected", LONG_LIMIT, label="Ce qu'on attend")
    reconsider = text_value(fields.get("reconsider_if") or "", "reconsider_if", LONG_LIMIT, label="Le changement d'avis")
    options = _dump_options(fields.get("options") or [])
    rule = _dump_rule(fields.get("rule"))
    return choice, options, expected, reconsider, rule


def _complete(choice, options_json, expected, reconsider):
    options = json.loads(options_json)
    if not choice.strip() or not expected.strip() or not reconsider.strip():
        return False
    if NE_RIEN not in options or options.count(NE_RIEN) != 1:
        return False
    if not 1 <= len(options) <= 20:
        return False
    return True


def create_decision(ctx, person, fields):
    require_principal(person)
    milestone_id = fields.get("milestone_id")
    if isinstance(milestone_id, str) and milestone_id.isdigit():
        milestone_id = int(milestone_id)
    if isinstance(milestone_id, bool) or not isinstance(milestone_id, int):
        raise AppError(400, "validation", "Échéance requise.", {"milestone_id": "Choisissez un repère."})
    choice, options, expected, reconsider, rule = _parts(fields)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        milestone = ctx.conn.execute("SELECT id FROM milestone WHERE id=?", (milestone_id,)).fetchone()
        if milestone is None:
            raise AppError(404, "not_found", "Introuvable.")
        ctx.conn.execute(
            """INSERT INTO decision(milestone_id, author_id, choice, options_json, expected, reconsider_if,
               rule_json, created_at, sealed_at, draft_version)
               VALUES(?,?,?,?,?,?,?,?,NULL,1)""",
            (milestone_id, person["id"], choice, options, expected, reconsider, rule, moment),
        )
        new_id = ctx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(ctx.home, ctx.clock, "decision_create", "ok", person["id"], "decision", new_id)
    return new_id


def update_decision(ctx, person, decision_id, fields, expected_version):
    require_principal(person)
    choice, options, expected, reconsider, rule = _parts(fields)
    with write_tx(ctx):
        row = ctx.conn.execute(
            "SELECT id, sealed_at, draft_version FROM decision WHERE id=?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise AppError(404, "not_found", "Introuvable.")
        if row["sealed_at"] is not None:
            raise AppError(409, "conflict", "La page scellée ne peut plus être modifiée.")
        if expected_version != row["draft_version"]:
            raise AppError(409, "conflict", "Cette page a été modifiée entre-temps. Rechargez-la.")
        try:
            cur = ctx.conn.execute(
                """UPDATE decision SET choice=?, options_json=?, expected=?, reconsider_if=?, rule_json=?,
                   draft_version=draft_version+1
                   WHERE id=? AND sealed_at IS NULL AND draft_version=?""",
                (choice, options, expected, reconsider, rule, decision_id, expected_version),
            )
        except sqlite3.IntegrityError:
            raise AppError(409, "conflict", "La page scellée ne peut plus être modifiée.")
        if cur.rowcount != 1:
            raise AppError(409, "conflict", "Cette page a été modifiée entre-temps. Rechargez-la.")
    audit(ctx.home, ctx.clock, "decision_update", "ok", person["id"], "decision", decision_id)


def seal_decision(ctx, person, decision_id, expected_version, confirm):
    require_principal(person)
    if confirm is not True:
        raise AppError(400, "validation", "Le scellement doit être confirmé.", {"confirm": "Confirmation requise."})
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        row = ctx.conn.execute(
            """SELECT id, sealed_at, draft_version, choice, options_json, expected, reconsider_if
               FROM decision WHERE id=?""",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise AppError(404, "not_found", "Introuvable.")
        if row["sealed_at"] is not None:
            raise AppError(409, "conflict", "Cette page est déjà scellée.")
        if expected_version != row["draft_version"]:
            raise AppError(409, "conflict", "Cette page a été modifiée entre-temps. Rechargez-la.")
        if not _complete(row["choice"], row["options_json"], row["expected"], row["reconsider_if"]):
            raise AppError(400, "validation", "Les quatre parties et l'option « Ne rien faire » sont requises pour sceller.", {})
        try:
            cur = ctx.conn.execute(
                """UPDATE decision SET sealed_at=?, draft_version=draft_version+1
                   WHERE id=? AND sealed_at IS NULL AND draft_version=?""",
                (moment, decision_id, expected_version),
            )
        except sqlite3.IntegrityError:
            raise AppError(400, "validation", "La page est incomplète.", {})
        if cur.rowcount != 1:
            raise AppError(409, "conflict", "Cette page a été modifiée entre-temps. Rechargez-la.")
    audit(ctx.home, ctx.clock, "decision_seal", "ok", person["id"], "decision", decision_id)


def add_result(ctx, person, decision_id, body, confirm):
    require_principal(person)
    if confirm is not True:
        raise AppError(400, "validation", "Le résultat doit être confirmé.", {"confirm": "Confirmation requise."})
    body = text_value(body, "body", 4000, required=True, label="Le résultat")
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        row = ctx.conn.execute("SELECT sealed_at FROM decision WHERE id=?", (decision_id,)).fetchone()
        if row is None:
            raise AppError(404, "not_found", "Introuvable.")
        if row["sealed_at"] is None:
            raise AppError(409, "conflict", "Le résultat s'ajoute seulement à une page scellée.")
        existing = ctx.conn.execute(
            "SELECT decision_id FROM decision_result WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        if existing is not None:
            raise AppError(409, "conflict", "Un résultat est déjà enregistré.")
        try:
            ctx.conn.execute(
                "INSERT INTO decision_result(decision_id, author_id, body, created_at) VALUES(?,?,?,?)",
                (decision_id, person["id"], body, moment),
            )
        except sqlite3.IntegrityError:
            raise AppError(409, "conflict", "Le résultat ne peut pas être enregistré.")
    audit(ctx.home, ctx.clock, "decision_result", "ok", person["id"], "decision", decision_id)


def _load_readable(ctx, person, decision_id):
    row = ctx.conn.execute(
        """SELECT d.id, d.milestone_id, d.author_id, d.choice, d.options_json, d.expected,
                  d.reconsider_if, d.rule_json, d.created_at, d.sealed_at, d.draft_version,
                  a.display_name AS author_name
           FROM decision d JOIN person a ON a.id=d.author_id
           WHERE d.id=? AND (
             ?=1 OR EXISTS(SELECT 1 FROM decision_access x WHERE x.decision_id=d.id AND x.person_id=?)
           )""",
        (decision_id, 1 if person["is_principal"] else 0, person["id"]),
    ).fetchone()
    if row is None:
        raise AppError(404, "not_found", "Introuvable.")
    return row


def decision_payload(ctx, person, decision_id):
    row = _load_readable(ctx, person, decision_id)
    result = ctx.conn.execute(
        "SELECT body, created_at, author_id FROM decision_result WHERE decision_id=?",
        (decision_id,),
    ).fetchone()
    payload = {
        "id": row["id"],
        "author_name": row["author_name"],
        "choice": row["choice"],
        "options": json.loads(row["options_json"]),
        "expected": row["expected"],
        "reconsider_if": row["reconsider_if"],
        "rule": json.loads(row["rule_json"]) if row["rule_json"] else None,
        "created_at": row["created_at"],
        "sealed_at": row["sealed_at"],
        "draft_version": row["draft_version"],
        "result": None if result is None else {"body": result["body"], "created_at": result["created_at"]},
    }
    if person["can_view_index"]:
        milestone = ctx.conn.execute(
            "SELECT id, name, due_date FROM milestone WHERE id=?",
            (row["milestone_id"],),
        ).fetchone()
        payload["milestone_id"] = milestone["id"]
        payload["milestone_name"] = milestone["name"]
        payload["milestone_due_date"] = milestone["due_date"]
    return payload


def list_decisions(ctx, person):
    if person["can_view_index"]:
        rows = ctx.conn.execute(
            """SELECT d.id, d.created_at, d.sealed_at, m.id AS milestone_id, m.name AS milestone_name
               FROM decision d JOIN milestone m ON m.id=d.milestone_id
               WHERE ?=1 OR EXISTS(SELECT 1 FROM decision_access a WHERE a.decision_id=d.id AND a.person_id=?)
               ORDER BY d.created_at, d.id""",
            (1 if person["is_principal"] else 0, person["id"]),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "sealed_at": row["sealed_at"],
                "milestone_id": row["milestone_id"],
                "milestone_name": row["milestone_name"],
            }
            for row in rows
        ]
    rows = ctx.conn.execute(
        """SELECT d.id, d.created_at, d.sealed_at
           FROM decision d
           WHERE EXISTS(SELECT 1 FROM decision_access a WHERE a.decision_id=d.id AND a.person_id=?)
           ORDER BY d.created_at, d.id""",
        (person["id"],),
    ).fetchall()
    return [{"id": row["id"], "created_at": row["created_at"], "sealed_at": row["sealed_at"]} for row in rows]
