"""Modules activables : masquage UI et blocage serveur, sans jamais toucher aux données."""

from ..audit import audit
from ..db import require_household, write_tx
from ..errors import AppError
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


# Toujours actifs : « accueil » est la page d'atterrissage après connexion et bascule de foyer,
# « foyer » porte la gestion des membres et des accès (retirer un compte doit rester possible),
# « parametres » héberge ce formulaire (le désactiver empêcherait de réactiver quoi que ce soit).
LOCKED = {
    "accueil": "Page d'arrivée après connexion.",
    "foyer": "Gestion des membres et des accès.",
    "parametres": "Permet de réactiver les modules.",
}

# Préfixes d'URL bloqués quand le module est désactivé (pages HTML et API JSON).
ROUTE_PREFIXES = (
    ("/organisation", "organisation"),
    ("/a-faire", "organisation"),
    ("/calendrier", "calendrier"),
    ("/sejours", "calendrier"),
    ("/agenda", "calendrier"),
    ("/recherche", "recherche"),
    ("/finances", "finances"),
    ("/inventaire", "inventaire"),
    ("/maison", "inventaire"),
    ("/mediatheque", "mediatheque"),
    ("/reperes", "reperes"),
    ("/decisions", "decisions"),
    ("/coffre", "coffre"),
    ("/api/tasks", "organisation"),
    ("/api/events", "calendrier"),
    ("/api/search", "recherche"),
    ("/api/finance", "finances"),
    ("/api/inventory", "inventaire"),
    ("/api/media", "mediatheque"),
    ("/api/milestones", "reperes"),
    ("/api/decisions", "decisions"),
    ("/api/files", "coffre"),
)


def module_for_path(path):
    for prefix, key in ROUTE_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return key
    return None


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
            "enabled": key in LOCKED or by_key.get(key, False),
            "locked": key in LOCKED,
            "locked_reason": LOCKED.get(key, ""),
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


def set_enabled(ctx, person, wanted):
    """Enregistre l'état des modules basculables du foyer actif. Les données restent intactes."""
    from .auth import require_principal

    require_principal(person)
    wanted = set(wanted)
    if wanted - set(LABELS):
        raise AppError(400, "validation", "Module inconnu.")
    require_household(ctx.conn, hh(ctx))
    changed = []
    with write_tx(ctx):
        ensure_seeded(ctx.conn, hh(ctx))
        current = {
            row["module_key"]: bool(row["enabled"])
            for row in ctx.conn.execute(
                "SELECT module_key, enabled FROM module_setting WHERE household_id=?", (hh(ctx),),
            )
        }
        for key in NAV_ORDER:
            target = key in LOCKED or key in wanted
            if current.get(key) != target:
                ctx.conn.execute(
                    "UPDATE module_setting SET enabled=? WHERE household_id=? AND module_key=?",
                    (1 if target else 0, hh(ctx), key),
                )
                changed.append((key, target))
    for key, target in changed:
        audit(ctx.home, ctx.clock, "module_enable" if target else "module_disable", "ok", person["id"], "module", key)
    return list_modules(ctx)
