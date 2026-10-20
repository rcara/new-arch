"""Affichage français. Aucun total de montants."""

from datetime import date, timedelta

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

STATUS_LABEL = {
    "expire": "Expiré",
    "sous_30": "Sous 30 jours",
    "sous_90": "Sous 90 jours",
    "a_jour": "À jour",
    "sans_date": "Sans date",
}


def status_for(due, today):
    if due is None or due == "":
        return "sans_date"
    if isinstance(due, str):
        due = date.fromisoformat(due)
    if due < today:
        return "expire"
    if due <= today + timedelta(days=30):
        return "sous_30"
    if due <= today + timedelta(days=90):
        return "sous_90"
    return "a_jour"


def format_date(value):
    if value is None or value == "":
        return "Sans date"
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {MOIS[value.month - 1]} {value.year}"


def format_timestamp(value, timezone_name):
    from zoneinfo import ZoneInfo
    from .clock import parse_utc
    local = parse_utc(value).astimezone(ZoneInfo(timezone_name))
    return f"{format_date(local.date())} à {local.strftime('%H:%M')}"


def format_cents(cents):
    if cents is None:
        return "Non renseigné"
    cents = int(cents)
    euros, cent = divmod(abs(cents), 100)
    digits = str(euros)
    groups = []
    while digits:
        groups.append(digits[-3:])
        digits = digits[:-3]
    grouped = "\u202f".join(reversed(groups))
    return f"{grouped},{cent:02d} €"


def notice_date(due, notice_days):
    if not due:
        return None
    return (date.fromisoformat(due) - timedelta(days=int(notice_days or 0))).isoformat()
