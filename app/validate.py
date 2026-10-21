"""Bornes du brief et bornes techniques nécessaires au stockage."""

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import AppError

CATEGORIES = (
    "Identité",
    "Logement",
    "Véhicule",
    "Santé",
    "Argent et assurances",
    "Travail et formation",
    "Impôts",
)
NE_RIEN = "Ne rien faire"
MAX_FILE_BYTES = 20 * 1024 * 1024
MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def field_error(fields):
    raise AppError(400, "validation", "La saisie est incomplète ou invalide.", fields)


def text_value(value, key, limit, required=False, label="Ce champ"):
    if value is None:
        value = ""
    if not isinstance(value, str):
        field_error({key: f"{label} doit être un texte."})
    value = value.strip()
    if required and not value:
        field_error({key: f"{label} est requis."})
    if len(value) > limit:
        field_error({key: f"{label} dépasse {limit} caractères."})
    return value


def timezone_name(value):
    name = text_value(value, "timezone", 80, required=True, label="Le fuseau")
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        field_error({"timezone": "Fuseau inconnu."})
    return name


def username_value(value):
    name = text_value(value, "username", 80, required=True, label="L'identifiant")
    if any(ch.isspace() for ch in name):
        field_error({"username": "L'identifiant ne contient pas d'espace."})
    return name


def password_value(value, key="password"):
    if not isinstance(value, str) or not value:
        field_error({key: "Le mot de passe est requis."})
    if len(value) < 12 or len(value) > 128:
        field_error({key: "Le mot de passe contient entre 12 et 128 caractères."})
    return value


def optional_int(value, key, label):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        field_error({key: f"{label} est un nombre entier."})
    return value


def amount_cents(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        field_error({"amount_cents": "Le montant est un nombre de centimes, positif ou nul."})
    return value


def amount_from_form(value):
    if value is None:
        return None
    raw = str(value).strip().replace(" ", "").replace("\u202f", "")
    if raw == "":
        return None
    raw = raw.replace(",", ".")
    if raw.count(".") > 1:
        field_error({"amount": "Montant invalide."})
    if "." in raw:
        euros, cents = raw.split(".")
        if not euros.isdigit() or not cents.isdigit() or len(cents) > 2:
            field_error({"amount": "Indiquez au plus deux décimales."})
        cents = cents.ljust(2, "0")
        return int(euros) * 100 + int(cents)
    if not raw.isdigit():
        field_error({"amount": "Montant invalide."})
    return int(raw) * 100


def date_value(value, key="due_date", label="La date"):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        field_error({key: f"{label} est au format AAAA-MM-JJ."})
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        field_error({key: f"{label} n'existe pas."})
    if parsed.isoformat() != value:
        field_error({key: f"{label} est au format AAAA-MM-JJ."})
    return value


def due_date_value(value):
    return date_value(value, key="due_date", label="La date")


def notice_days_value(value):
    if value is None or value == "":
        return 0
    if isinstance(value, str):
        if not value.strip().isdigit():
            field_error({"notice_days": "Le préavis est un nombre de jours."})
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 3650:
        field_error({"notice_days": "Le préavis est compris entre 0 et 3650 jours."})
    return value


def normalize_options(raw):
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        field_error({"options": "Les options forment une liste."})
    cleaned = []
    for item in raw:
        if not isinstance(item, str):
            field_error({"options": "Chaque option est un texte."})
        text = item.strip()
        if not text or text == NE_RIEN:
            continue
        if len(text) > 500:
            field_error({"options": "Une option dépasse 500 caractères."})
        if text in cleaned:
            field_error({"options": "Une option est répétée."})
        cleaned.append(text)
    if len(cleaned) + 1 > 20:
        field_error({"options": "Vingt options au maximum, y compris « Ne rien faire »."})
    return cleaned + [NE_RIEN]


def normalize_rule(name, lines):
    if name is None:
        name = ""
    if not isinstance(name, str):
        field_error({"rule": "Le nom de la règle est un texte."})
    name = name.strip()
    if len(name) > 200:
        field_error({"rule": "Le nom de la règle dépasse 200 caractères."})
    if lines is None:
        lines = []
    if not isinstance(lines, list):
        field_error({"rule": "Les lignes de la règle forment une liste."})
    kept = []
    for line in lines:
        if not isinstance(line, dict):
            field_error({"rule": "Chaque ligne a un libellé et une valeur."})
        extra = set(line) - {"label", "value"}
        if extra:
            field_error({"rule": "Ligne de règle invalide."})
        label = line.get("label", "")
        value = line.get("value", "")
        if not isinstance(label, str) or not isinstance(value, str):
            field_error({"rule": "Chaque ligne a un libellé et une valeur."})
        label, value = label.strip(), value.strip()
        if not label and not value:
            continue
        if not label or not value:
            field_error({"rule": "Chaque ligne a un libellé et une valeur."})
        if len(label) > 300 or len(value) > 1000:
            field_error({"rule": "Une ligne de règle est trop longue."})
        kept.append({"label": label, "value": value})
    if not name and not kept:
        return None
    if not name or not kept:
        field_error({"rule": "La règle a un nom et au moins une ligne, ou elle est absente."})
    if len(kept) > 10:
        field_error({"rule": "Dix lignes au maximum."})
    return {"name": name, "lines": kept}


def sniff_mime(data):
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def original_filename(name):
    if not isinstance(name, str):
        field_error({"file": "Nom de fichier invalide."})
    base = name.replace("\\", "/").split("/")[-1].strip()
    if not base or base in {".", ".."} or len(base) > 180:
        field_error({"file": "Nom de fichier invalide."})
    if any(ord(ch) < 32 or ch in '<>:"|?*' for ch in base):
        field_error({"file": "Nom de fichier invalide."})
    if base.startswith(".") or base.lower().count(".") != 1:
        field_error({"file": "Le nom comporte une seule extension."})
    ext = "." + base.lower().rsplit(".", 1)[1]
    if ext not in MIME_BY_EXT:
        field_error({"file": "Extension non acceptée. Utilisez PDF, JPEG ou PNG."})
    return base, ext


def validate_file(data, filename):
    if not data:
        field_error({"file": "Le fichier est vide."})
    if len(data) > MAX_FILE_BYTES:
        raise AppError(413, "too_large", "Le fichier dépasse 20 Mio.")
    base, ext = original_filename(filename)
    mime = sniff_mime(data)
    if mime is None or mime != MIME_BY_EXT[ext]:
        raise AppError(415, "unsupported_type", "Le contenu ne correspond pas à un PDF, JPEG ou PNG autorisé.")
    return base, mime
