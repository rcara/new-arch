"""Anniversaires familiaux, récurrents chaque année.

La liste est celle demandée pour le foyer réel. Elle n'entre pas dans le jeu
de démonstration (Maison Démo). L'alimentation est idempotente : un événement
annuel non archivé du même titre n'est pas recréé.

Le 2 décembre, noté « votre serviteur », est enregistré comme Roger Cairo
(titulaire du compte), distinct de Roger Moute (22 avril).
"""

from .. import Ctx
from ..db import any_household, connect, household_row, require_household
from ..tenancy import hh
from . import events
from .demo import DEMO_HOUSEHOLD

# (mois, jour, nom) — orthographe d'origine, ordre du calendrier.
FAMILY_BIRTHDAYS = (
    (1, 21, "Tatie Agnes"),
    (1, 23, "Armel Miniem"),
    (2, 1, "Jason Aquilon"),
    (2, 2, "Julienne Keman"),
    (2, 8, "Stephen Eko"),
    (3, 2, "Anthea Ferrand"),
    (3, 3, "Denise Aquilon"),
    (3, 6, "Lina Caroline Cairo"),
    (3, 8, "Jesse Eko"),
    (3, 17, "Dédé"),
    (4, 4, "Jean Prospère Oloko"),
    (4, 11, "Leila Moute"),
    (4, 11, "Camilla Zobel"),
    (4, 18, "Kimya Cairo"),
    (4, 22, "Roger Moute"),
    (5, 19, "Stéphanie Moute"),
    (5, 19, "Carl Zobel"),
    (5, 24, "Laïna AQUILON"),
    (6, 14, "Yannick Ferrand"),
    (7, 3, "Barbara Moute"),
    (7, 10, "Léa Cairo"),
    (7, 18, "Françoise Bellessort"),
    (7, 18, "Camille Moute"),
    (7, 27, "Jean Gilbert Cairo"),
    (8, 3, "Yanna Marie"),
    (8, 10, "Haylé Claude"),
    (8, 12, "Tatie Marie Claire"),
    (8, 28, "Henry Michel"),
    (9, 3, "Lohan Aquilon"),
    (9, 3, "Sylvie Betcheke"),
    (9, 9, "Luke Richard"),
    (9, 9, "Jean Emmanuel"),
    (9, 22, "Dominique Cairo"),
    (9, 25, "Tatie Julienne"),
    (9, 30, "Yann Aquilon"),
    (10, 5, "Dyahel Aquilon"),
    (10, 11, "Syloé Ferrant"),
    (10, 11, "Wilfried Aboa"),
    (10, 25, "Nell Cairo"),
    (10, 27, "Marien Aboh"),
    (11, 13, "Tatie Gertrude"),
    (11, 17, "Alexander"),
    (11, 26, "Anne Elisabeth"),
    (12, 2, "Roger Cairo"),
    (12, 4, "Jessy Oloko"),
    (12, 10, "Isabelle Cairo"),
    (12, 11, "Kathy Julienne"),
    (12, 17, "Aélyah AQUILON"),
)

NOTE = "Anniversaire familial"
ANCHOR_YEAR = 2000


def title_for(name):
    return f"Anniversaire de {name}"


def _principal(ctx):
    row = ctx.conn.execute(
        f"""SELECT id FROM person
            WHERE household_id={hh(ctx)} AND is_principal=1 AND active=1
            ORDER BY id LIMIT 1"""
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"]}


def ensure_family_birthdays(ctx, person=None):
    """Crée les anniversaires manquants du foyer actif. Retourne le nombre ajouté.

    Sans effet si le foyer s'appelle Maison Démo. Le module Calendrier peut être
    désactivé : les événements sont quand même enregistrés pour le jour où on le rallume.
    """
    household = require_household(ctx.conn, hh(ctx))
    if household["name"] == DEMO_HOUSEHOLD:
        return 0
    actor = person or _principal(ctx)
    if actor is None or actor.get("id") is None:
        return 0
    added = 0
    for month, day, name in FAMILY_BIRTHDAYS:
        title = title_for(name)
        existing = ctx.conn.execute(
            f"""SELECT 1 FROM calendar_event
                WHERE household_id={hh(ctx)} AND archived=0 AND recurrence='yearly' AND title=?""",
            (title,),
        ).fetchone()
        if existing is not None:
            continue
        events.create_event(
            ctx,
            actor,
            {
                "title": title,
                "notes": NOTE,
                "all_day": True,
                "start_date": f"{ANCHOR_YEAR:04d}-{month:02d}-{day:02d}",
                "timezone": household["timezone"],
                "recurrence": "yearly",
            },
            check_module=False,
        )
        added += 1
    return added


def seed_if_household(app):
    """Au démarrage : complète un foyer déjà créé. Jamais pendant les tests, jamais la démo."""
    if app.testing:
        return 0
    conn = connect(app.config["HOME"] / "data" / "metadata.sqlite")
    try:
        if not any_household(conn):
            return 0
        household = household_row(conn, 1)
        if household is None or household["name"] == DEMO_HOUSEHOLD:
            return 0
        ctx = Ctx(
            conn,
            app.config["CLOCK"],
            app.config["HOME"],
            app.config["LOCK"],
            app.config["DUMMY_HASH"],
            crypto=app.config.get("CRYPTO"),
            household_id=household["id"],
        )
        return ensure_family_birthdays(ctx)
    finally:
        conn.close()
