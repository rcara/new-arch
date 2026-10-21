"""App Shell : groupes de navigation et actions « + Ajouter » filtrés par modules et droits.

Les entrées ne font que pointer vers des routes existantes ; les contrôles d'accès restent
dans les services. Ne jamais lister une entrée que la personne ne peut pas ouvrir.
"""

from flask import url_for

# nav (clé historique calculée par le context processor) → (groupe, sous-entrée)
ACTIVE = {
    "today": ("aujourdhui", None),
    "calendrier": ("agenda", "calendrier"),
    "reperes": ("agenda", "reperes"),
    "organisation": ("afaire", "taches"),
    "finances": ("finances", "finances"),
    "inventaire": ("maison", "inventaire"),
    "coffre": ("bibliotheque", "coffre"),
    "mediatheque": ("bibliotheque", "mediatheque"),
    "decisions": ("bibliotheque", "decisions"),
    "recherche": (None, None),
    "foyer": ("parametres", "foyer"),
    "personnes": ("parametres", "foyer"),
    "acces": ("parametres", "acces"),
    "parametres": ("parametres", "preferences"),
    "avance": ("parametres", "avance"),
    "profil": ("parametres", "profil"),
}


def _entry(key, label, endpoint, **kwargs):
    return {"key": key, "label": label, "href": url_for(endpoint, **kwargs)}


def _group(key, label, short, children, section="principal"):
    children = [child for child in children if child]
    if not children:
        return None
    return {
        "key": key,
        "label": label,
        "short": short,
        "href": children[0]["href"],
        "children": children if len(children) > 1 else [],
        "section": section,
    }


def build(person, enabled, nav, here="/"):
    if not person:
        return {"groups": [], "create": [], "active": (None, None), "search": False}
    principal = bool(person.get("is_principal"))
    index = bool(person.get("can_view_index"))

    def on(key):
        return key in enabled

    groups = [
        _group("aujourdhui", "Aujourd'hui", "Aujourd'hui", [
            on("accueil") and _entry("aujourdhui", "Aujourd'hui", "pages.today"),
        ]),
        _group("agenda", "Agenda", "Agenda", [
            on("calendrier") and _entry("calendrier", "Calendrier", "pages.events_get"),
            on("reperes") and index and _entry("reperes", "Repères et échéances", "pages.milestones_get"),
        ]),
        _group("afaire", "À faire", "À faire", [
            on("organisation") and _entry("taches", "Tâches", "pages.tasks_get"),
            on("organisation") and _entry("faites", "Terminées", "pages.tasks_get", status="done"),
        ]),
        _group("finances", "Finances", "Finances", [
            on("finances") and _entry("finances", "Vue d'ensemble", "pages.finance_get"),
            on("finances") and _entry("depense", "Nouvelle dépense", "pages.finance_expense_new"),
            on("finances") and _entry("budget", "Budgets", "pages.finance_budget_new"),
            on("finances") and _entry("remboursement", "Remboursements", "pages.finance_reimburse_new"),
        ]),
        _group("maison", "Maison", "Maison", [
            on("inventaire") and _entry("inventaire", "Inventaire", "pages.inventory_get"),
            on("inventaire") and _entry("lieu", "Pièces et emplacements", "pages.inventory_place_new"),
        ]),
        _group("bibliotheque", "Bibliothèque", "Biblio.", [
            on("coffre") and _entry("coffre", "Documents et coffre", "pages.vault_get"),
            on("mediatheque") and _entry("mediatheque", "Médiathèque", "pages.media_get"),
            on("decisions") and _entry("decisions", "Décisions", "pages.decisions_get"),
        ]),
        _group("parametres", "Paramètres", "Réglages", [
            on("parametres") and _entry("preferences", "Préférences", "pages.settings_get"),
            principal and on("foyer") and _entry("foyer", "Foyer et membres", "pages.foyer_get"),
            principal and on("foyer") and _entry("acces", "Permissions", "pages.access_index"),
            _entry("profil", "Profil", "pages.profile_get"),
            principal and on("parametres") and _entry("avance", "Administration avancée", "pages.settings_advanced_get"),
        ], section="administration"),
    ]
    groups = [group for group in groups if group]

    back = {"next": here if here and here.startswith("/") else "/"}
    create = [
        on("finances") and _entry("depense", "Dépense", "pages.finance_expense_new", **back),
        on("calendrier") and dict(_entry("evenement", "Événement", "pages.event_new", **back), panel="ajout-evenement"),
        on("organisation") and dict(_entry("tache", "Tâche", "pages.task_new", **back), panel="ajout-tache"),
        on("inventaire") and _entry("bien", "Bien", "pages.inventory_item_new", **back),
        principal and on("coffre") and _entry("document", "Document", "pages.vault_get", _anchor="depot"),
        principal and index and on("reperes") and _entry("repere", "Repère", "pages.milestone_new", **back),
        principal and index and on("decisions") and on("reperes")
        and _entry("decision", "Décision", "pages.milestones_get"),
        on("mediatheque") and _entry("oeuvre", "Œuvre ou collection", "pages.media_work_new", **back),
    ]
    return {
        "groups": groups,
        "create": [item for item in create if item],
        "active": ACTIVE.get(nav, (None, None)),
        "search": on("recherche"),
    }
