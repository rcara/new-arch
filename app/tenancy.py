"""Multi-foyer : identifiant de foyer courant porté par le contexte."""


def hh(ctx) -> int:
    """Household id actif (jamais 0)."""
    value = getattr(ctx, "household_id", None)
    if value is None:
        return 1
    return int(value)
