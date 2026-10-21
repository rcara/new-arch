"""Montants monétaires exacts : unités mineures (INTEGER), jamais de float."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .errors import AppError

CURRENCIES = frozenset({"CHF", "EUR"})
# ISO 4217 minor units for CHF and EUR
MINOR_FACTOR = 100


def require_currency(value):
    currency = (value or "").strip().upper()
    if currency not in CURRENCIES:
        raise AppError(400, "validation", "Devise non supportée.", {"currency": "Utilisez CHF ou EUR."})
    return currency


def parse_amount_to_minor(value, *, field="amount", label="Le montant"):
    """Accepte int (déjà en minor), str '12.50' / '12,50', ou Decimal. Jamais float."""
    if isinstance(value, bool):
        raise AppError(400, "validation", f"{label} est invalide.", {field: f"{label} est invalide."})
    if isinstance(value, int):
        if value <= 0:
            raise AppError(400, "validation", f"{label} doit être positif.", {field: f"{label} doit être positif."})
        return value
    if isinstance(value, float):
        raise AppError(400, "validation", f"{label} ne peut pas être un flottant.", {field: "Utilisez une chaîne ou des centimes."})
    if value is None or value == "":
        raise AppError(400, "validation", f"{label} est requis.", {field: f"{label} est requis."})
    if isinstance(value, Decimal):
        text = format(value, "f")
    else:
        text = str(value).strip().replace(" ", "").replace("'", "")
        text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        raise AppError(400, "validation", f"{label} est invalide.", {field: f"{label} est invalide."})
    if amount <= 0:
        raise AppError(400, "validation", f"{label} doit être positif.", {field: f"{label} doit être positif."})
    quantized = (amount * MINOR_FACTOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    minor = int(quantized)
    if minor <= 0:
        raise AppError(400, "validation", f"{label} doit être positif.", {field: f"{label} doit être positif."})
    return minor


def format_minor(minor, currency="CHF"):
    if minor is None:
        return ""
    sign = "-" if minor < 0 else ""
    value = abs(int(minor))
    whole, cents = divmod(value, MINOR_FACTOR)
    return f"{sign}{whole},{cents:02d} {currency}"


def split_equal(total_minor, person_ids):
    """Répartition égale avec reste aux premiers (largest remainder). Somme exacte."""
    ids = list(person_ids)
    if not ids:
        raise AppError(400, "validation", "Au moins une personne pour la répartition.")
    n = len(ids)
    base = total_minor // n
    remainder = total_minor - base * n
    shares = []
    for index, person_id in enumerate(ids):
        share = base + (1 if index < remainder else 0)
        shares.append({"person_id": person_id, "share_minor": share, "method": "equal"})
    assert sum(s["share_minor"] for s in shares) == total_minor
    return shares


def split_percent(total_minor, allocations):
    """allocations: [{person_id, percent}] percent en centièmes (50.00% => 5000) ou float-like Decimal string.
    Utilise restes les plus grands pour une somme exacte.
    """
    if not allocations:
        raise AppError(400, "validation", "Répartition vide.")
    weights = []
    for item in allocations:
        person_id = int(item["person_id"])
        raw = item.get("percent", item.get("weight"))
        if isinstance(raw, float):
            raise AppError(400, "validation", "Les pourcentages ne peuvent pas être des flottants.")
        if isinstance(raw, int):
            # interprété comme centièmes de pourcent (5000 = 50%)
            bps = raw
        else:
            text = str(raw).strip().replace(",", ".")
            try:
                pct = Decimal(text)
            except (InvalidOperation, ValueError):
                raise AppError(400, "validation", "Pourcentage invalide.", {"percent": "Pourcentage invalide."})
            bps = int((pct * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if bps < 0:
            raise AppError(400, "validation", "Pourcentage négatif.")
        weights.append((person_id, bps))
    total_bps = sum(w for _, w in weights)
    if total_bps <= 0:
        raise AppError(400, "validation", "La somme des pourcentages doit être positive.")
    # Exact parts via truncation + largest remainder
    raw_parts = []
    for person_id, bps in weights:
        exact = Decimal(total_minor) * Decimal(bps) / Decimal(total_bps)
        floor = int(exact)  # truncate toward zero (amounts positifs)
        frac = exact - floor
        raw_parts.append((person_id, floor, frac))
    assigned = sum(part[1] for part in raw_parts)
    leftover = total_minor - assigned
    ordered = sorted(enumerate(raw_parts), key=lambda item: (-item[1][2], item[0]))
    shares_map = {person_id: floor for person_id, floor, _frac in raw_parts}
    for index in range(leftover):
        person_id = ordered[index % len(ordered)][1][0]
        shares_map[person_id] += 1
    shares = [
        {"person_id": person_id, "share_minor": shares_map[person_id], "method": "percent"}
        for person_id, _bps in weights
    ]
    assert sum(item["share_minor"] for item in shares) == total_minor
    return shares


def split_fixed(total_minor, allocations):
    """allocations: [{person_id, amount_minor|amount}]. Somme doit égaler total."""
    shares = []
    running = 0
    for item in allocations:
        person_id = int(item["person_id"])
        if "share_minor" in item or "amount_minor" in item:
            share = int(item.get("share_minor", item.get("amount_minor")))
        else:
            share = parse_amount_to_minor(item.get("amount"), field="amount", label="La part")
        if share < 0:
            raise AppError(400, "validation", "Part négative.")
        shares.append({"person_id": person_id, "share_minor": share, "method": "fixed"})
        running += share
    if running != total_minor:
        raise AppError(
            400,
            "validation",
            f"La somme des parts ({running}) doit égaler le montant ({total_minor}).",
            {"splits": "Somme des parts incorrecte."},
        )
    return shares


def split_income_prorata(total_minor, incomes):
    """incomes: [{person_id, income_minor}]. Pondération par revenu déclaré."""
    positive = [item for item in incomes if int(item.get("income_minor") or 0) > 0]
    if not positive:
        # fallback equal among provided persons
        return split_equal(total_minor, [int(item["person_id"]) for item in incomes])
    return split_percent(
        total_minor,
        [{"person_id": int(item["person_id"]), "percent": int(item["income_minor"])} for item in positive],
    )
