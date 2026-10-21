"""Modules activables pour la navigation et le masquage UI."""

from ..db import require_household
from ..tenancy import hh

DEFAULT_MODULES = (
    ("accueil", 1),
    ("foyer", 1),
    ("finances", 1),
    ("inventaire", 1),
    ("calendrier", 1),
    ("organisation", 1),
    ("coffre", 1),
    ("decisions", 1),
    ("mediatheque", 1),
    ("reperes", 1),
    ("recherche", 1),
    ("parametres", 1),
)

LABELS = {
    "accueil": "Accueil",
    "foyer": "Foyer",
    "finances": "Finances",
    "inventaire": "Inventaire",
    "calendrier": "Calendrier",
    "organisation": "Organisation",
    "coffre": "Coffre",
    "decisions": "Décisions",
    "mediatheque": "Médiathèque",
    "reperes": "Repères",
    "recherche": "Recherche",
    "parametres": "Paramètres",
}

NAV_ORDER = (
    "accueil",
    "finances",
    "inventaire",
    "calendrier",
    "organisation",
    "coffre",
    "decisions",
    "mediatheque",
    "reperes",
    "foyer",
    "recherche",
    "parametres",
)


def ensure_seeded(conn, household_id):
    existing = {
        row["module_key"]
        for row in conn.execute(
            "SELECT module_key FROM module_setting WHERE household_id=?",
            (household_id,),
        )
    }
    for key, enabled in DEFAULT_MODULES:
        if key not in existing:
            conn.execute(
                "INSERT INTO module_setting(household_id, module_key, enabled) VALUES(?,?,?)",
                (household_id, key, enabled),
            )


def list_modules(ctx):
    require_household(ctx.conn, hh(ctx))
    ensure_seeded(ctx.conn, hh(ctx))
    rows = ctx.conn.execute(
        f'SELECT module_key, enabled FROM module_setting WHERE household_id={hh(ctx)}'
    ).fetchall()
    by_key = {row["module_key"]: bool(row["enabled"]) for row in rows}
    return [
        {
            "key": key,
            "label": LABELS[key],
            "enabled": by_key.get(key, False),
        }
        for key in NAV_ORDER
        if key in LABELS
    ]


def enabled_keys(ctx):
    return {item["key"] for item in list_modules(ctx) if item["enabled"]}


def require_module(ctx, key):
    from ..errors import AppError

    if key not in enabled_keys(ctx):
        raise AppError(404, "not_found", "Module indisponible.")
