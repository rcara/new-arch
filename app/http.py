"""Requêtes locales : hôte, origine, CSRF, cookies."""

import secrets
from urllib.parse import quote

from flask import g, request

from .errors import AppError

MESSAGES = {
    "ready": "Le foyer est créé.",
    "saved": "Enregistrement effectué.",
    "sealed": "La page est scellée.",
    "result": "Le résultat est enregistré.",
    "uploaded": "La pièce est déposée.",
    "replaced": "La pièce est remplacée. Les accès précédents sont retirés.",
    "removed": "La pièce est retirée.",
    "access": "Les accès sont enregistrés.",
    "person": "La personne est ajoutée.",
    "account": "Le compte est créé.",
    "deactivated": "La personne est retirée du foyer. Son historique est conservé.",
    "archived": "Le repère est archivé.",
    "restored": "Le repère est restauré.",
    "task_saved": "La tâche est enregistrée.",
    "task_done": "La tâche est marquée faite.",
    "event_saved": "L'événement est enregistré.",
    "link_saved": "Le lien est enregistré.",
    "finance_saved": "Enregistrement financier effectué.",
    "finance_imported": "Import CSV terminé.",
}


def expected_host():
    return request.environ.get("HTTP_HOST", "")


def _public_https_origin(expected_origin):
    """True si EXPECTED_ORIGIN est en HTTPS public (Tunnel Cloudflare)."""
    return str(expected_origin).startswith("https:")


def _cookie_secure():
    from flask import current_app
    return _public_https_origin(current_app.config.get("EXPECTED_ORIGIN", ""))


def _origin_allowed(expected_origin, origin, referer):
    """Origin exacte OK ; en HTTPS public, Origin vide/null accepté sans Referer.

    Origin literal ``null`` (privacy / Referrer-Policy: no-referrer) is treated
    like empty. Host is already validated by the caller; CSRF remains required.
    ``referer`` is unused but kept for call-site compatibility.
    """
    if origin == expected_origin:
        return True
    if origin not in ("", "null"):
        return False
    # Public HTTPS: Host already checked; empty/null Origin is fine without Referer
    # (browsers send no Referer under Referrer-Policy: no-referrer).
    return _public_https_origin(expected_origin)


def guard_local():
    from flask import current_app
    remote = request.remote_addr or ""
    if remote != "127.0.0.1":
        raise AppError(403, "forbidden", "Accès uniquement local.")
    host = request.environ.get("HTTP_HOST", "")
    if host != current_app.config["EXPECTED_HOST"]:
        raise AppError(400, "validation", "Hôte refusé.")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected_origin = current_app.config["EXPECTED_ORIGIN"]
        origin = request.headers.get("Origin", "")
        referer = request.headers.get("Referer", "")
        if not _origin_allowed(expected_origin, origin, referer):
            raise AppError(400, "validation", "Origine refusée.")
        submitted = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
        if g.get("person"):
            expected = g.get("csrf_token") or ""
        else:
            expected = request.cookies.get("foyer_setup") or ""
        if not submitted or not expected or not secrets.compare_digest(str(submitted), str(expected)):
            raise AppError(400, "validation", "Jeton de sécurité invalide. Rechargez la page.")


def json_body(allowed):
    if not request.is_json:
        raise AppError(400, "validation", "Le corps doit être du JSON.")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AppError(400, "validation", "Le corps doit être un objet JSON.")
    extra = sorted(set(data) - set(allowed))
    if extra:
        raise AppError(400, "validation", "Champ non accepté.", {key: "Champ non accepté." for key in extra})
    return data


def safe_next(value):
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if any(ord(ch) < 32 for ch in value):
        return "/"
    return value.split("?", 1)[0]


def content_disposition(name):
    cleaned = "".join(ch for ch in name if ord(ch) >= 32 and ch not in '"\\')
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in cleaned) or "document"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(cleaned)}"


def cookie_session(response, token):
    secure = _cookie_secure()
    response.set_cookie(
        "foyer_session", token, max_age=8 * 3600, httponly=True, samesite="Strict", path="/", secure=secure,
    )
    response.delete_cookie("foyer_setup", path="/", secure=secure, samesite="Strict")
    return response


def cookie_setup(response, token):
    secure = _cookie_secure()
    response.set_cookie(
        "foyer_setup", token, max_age=1800, httponly=True, samesite="Strict", path="/", secure=secure,
    )
    return response


def cookie_message(response, code):
    secure = _cookie_secure()
    response.set_cookie(
        "foyer_msg", code, max_age=30, httponly=True, samesite="Strict", path="/", secure=secure,
    )
    return response
