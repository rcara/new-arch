"""Dataset de démonstration non sensible — jamais de données personnelles réelles."""

from io import BytesIO

from ..db import household_row
from ..errors import AppError
from . import auth, events, finance, inventory, media, milestones, people, tasks

# Identifiants fictifs documentés — uniquement pour un foyer vide / démo.
DEMO_HOUSEHOLD = "Maison Démo"
DEMO_USERNAME = "alex"
DEMO_PASSWORD = "DemoFoyer-2026!"
DEMO_PASSWORD_SECONDARY = "DemoCamille-2026!"
JPEG_TINY = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class _DemoUpload:
    """Fichier minimal compatible avec store_asset (stream.read)."""

    def __init__(self, filename, data, content_type):
        self.filename = filename
        self.content_type = content_type
        self.stream = BytesIO(data)


def seed_demo(ctx, limiter):
    """Initialise un foyer fictif riche. Refuse si un foyer existe déjà."""
    if household_row(ctx.conn) is not None:
        raise AppError(
            409,
            "conflict",
            "Un foyer existe déjà. Seed démo uniquement sur un dossier vide (nouveau FOYER_HOME).",
        )
    token, csrf, profile = auth.bootstrap(
        ctx,
        limiter,
        DEMO_HOUSEHOLD,
        "Europe/Zurich",
        "Alex Martin",
        DEMO_USERNAME,
        DEMO_PASSWORD,
    )
    principal = {
        "id": profile["person_id"],
        "display_name": "Alex Martin",
        "is_principal": 1,
        "can_view_index": 1,
    }
    camille_id = people.add_person(
        ctx, principal, "Camille Dubois", relationship="colocataire",
        username="camille", password=DEMO_PASSWORD_SECONDARY,
    )

    tasks.create_task(ctx, principal, {
        "title": "Sortir les poubelles",
        "due_date": "2027-02-22",
        "assignee_id": principal["id"],
        "priority": "normal",
        "notes": "Collecte le mardi (démo).",
    })
    tasks.create_task(ctx, principal, {
        "title": "Réviser le budget courses",
        "due_date": "2027-02-28",
        "assignee_id": camille_id,
        "priority": "low",
    })
    events.create_event(ctx, principal, {
        "title": "Réunion foyer",
        "start_date": "2027-03-01",
        "end_date": "2027-03-01",
        "all_day": True,
        "notes": "Agenda fictif — aucune donnée réelle.",
    })

    finance.seed_defaults(ctx, principal)
    accounts = finance.list_ledger_accounts(ctx, principal)["items"]
    chf = next(a for a in accounts if a["currency"] == "CHF")
    cats = finance.list_categories(ctx, principal, kind="expense")["items"]
    food = next(c for c in cats if c["name"] == "Alimentation")
    finance.create_transaction(ctx, principal, {
        "kind": "expense",
        "amount": "45,50",
        "currency": "CHF",
        "txn_date": "2027-02-18",
        "label": "Courses marché (démo)",
        "category_id": food["id"],
        "ledger_account_id": chf["id"],
        "payer_id": principal["id"],
        "split_method": "equal",
        "split_person_ids": [principal["id"], camille_id],
        "visibility": "household",
    })
    finance.create_budget(ctx, principal, {
        "category_id": food["id"],
        "period": "month",
        "year": 2027,
        "month": 2,
        "amount": "400,00",
        "currency": "CHF",
    })

    place_id = inventory.create_place(ctx, principal, {"name": "Cuisine", "notes": "Étage 0 (démo)"})
    inventory.create_item(ctx, principal, {
        "name": "Mixeur plongeant",
        "category": "Électroménager",
        "place_id": place_id,
        "purchase_date": "2025-06-01",
        "purchase_price": "79,90",
        "purchase_currency": "CHF",
        "condition": "good",
        "visibility": "household",
        "owner_ids": [principal["id"], camille_id],
    })

    milestones.create_milestone(ctx, principal, {
        "name": "Assurance habitation (démo)",
        "category": "Logement",
        "holder_id": principal["id"],
        "due_date": "2027-09-01",
    })

    media.create_work(ctx, principal, {
        "kind": "film",
        "title": "Le Voyage de Chihiro",
        "creator": "Hayao Miyazaki",
        "year": 2001,
        "status": "favorite",
        "visibility": "household",
    })
    media.create_work(ctx, principal, {
        "kind": "book",
        "title": "Le Petit Prince",
        "creator": "Antoine de Saint-Exupéry",
        "year": 1943,
        "status": "wishlist",
        "visibility": "household",
    })
    media.store_asset(
        ctx,
        principal,
        {"title": "Pochette démo", "collection": "Affiches", "visibility": "household"},
        _DemoUpload("pochette-demo.jpg", JPEG_TINY, "image/jpeg"),
    )

    return {
        "household": DEMO_HOUSEHOLD,
        "username": DEMO_USERNAME,
        "password": DEMO_PASSWORD,
        "secondary_username": "camille",
        "secondary_password": DEMO_PASSWORD_SECONDARY,
        "token": token,
        "csrf": csrf,
        "person_id": principal["id"],
    }
