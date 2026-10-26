"""Sync bidirectionnel Google Calendar (compte foyer) + overlay lecture seule.

Secrets client OAuth : FOYER_GOOGLE_CLIENT_ID / FOYER_GOOGLE_CLIENT_SECRET /
FOYER_GOOGLE_REDIRECT_URI — jamais en dépôt. Jetons refresh/access scellés via
crypto.seal lorsque le chiffrement foyer est actif.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from ..audit import audit
from ..clock import iso_utc
from ..crypto import CryptoState, open_blob, seal
from ..db import require_household, write_tx
from ..errors import AppError
from ..security import hash_token, new_token
from ..tenancy import hh
from . import events as events_svc
from .auth import require_principal

ALLOWED_EMAIL = "rcara.home@gmail.com"
MIRROR_CALENDAR_NAME = "New Arch"
BIRTHDAY_NOTES = "Anniversaire familial"
SCOPES = "openid email https://www.googleapis.com/auth/calendar"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CAL_API = "https://www.googleapis.com/calendar/v3"
SYNC_INTERVAL = timedelta(minutes=10)
STATE_TTL = timedelta(minutes=10)
OVERLAY_PAST_DAYS = 30
OVERLAY_FUTURE_DAYS = 180
OAUTH_TIMEOUT = 30

# Injectable HTTP for tests: (method, url, headers, body_bytes) -> (status, headers, body_bytes)
_http_transport = None


def set_http_transport(fn):
    global _http_transport
    _http_transport = fn


def reset_http_transport():
    set_http_transport(None)


def client_configured():
    return bool(_client_id() and _client_secret())


def _client_id():
    return (os.environ.get("FOYER_GOOGLE_CLIENT_ID") or "").strip()


def _client_secret():
    return (os.environ.get("FOYER_GOOGLE_CLIENT_SECRET") or "").strip()


def _redirect_uri(origin=None):
    explicit = (os.environ.get("FOYER_GOOGLE_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    if origin:
        return f"{origin.rstrip('/')}/oauth/google/callback"
    return "http://127.0.0.1:8765/oauth/google/callback"


def _crypto(ctx) -> CryptoState:
    state = getattr(ctx, "crypto", None)
    if state is None:
        return CryptoState(enabled=False, dek=None)
    return state


def _seal_token(ctx, token: str) -> bytes:
    return seal(_crypto(ctx), token.encode("utf-8"))


def _open_token(ctx, blob) -> str:
    if blob is None:
        return ""
    raw = bytes(blob) if not isinstance(blob, (bytes, bytearray)) else bytes(blob)
    return open_blob(_crypto(ctx), raw).decode("utf-8")


def _http(method, url, *, headers=None, body=None, form=None, json_body=None):
    headers = dict(headers or {})
    data = body
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    if _http_transport is not None:
        status, resp_headers, resp_body = _http_transport(method, url, headers, data)
        return status, dict(resp_headers or {}), resp_body or b""
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=OAUTH_TIMEOUT) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read() or b""


def _json_response(status, body, *, ok=(200, 201, 204)):
    text = body.decode("utf-8") if body else ""
    payload = json.loads(text) if text.strip() else {}
    if status not in ok:
        err = payload.get("error")
        if isinstance(err, dict):
            message = payload.get("error_description") or err.get("message") or err.get("status")
        else:
            message = payload.get("error_description") or err
        raise AppError(502, "storage", f"Google Calendar : {message or f'HTTP {status}'}.")
    return payload


def link_row(ctx):
    return ctx.conn.execute(
        f"SELECT gol.* FROM google_oauth_link gol WHERE gol.household_id={hh(ctx)}"
    ).fetchone()


def is_linked(ctx):
    row = link_row(ctx)
    return bool(row and row["refresh_token_enc"] and not row["disconnected_at"])


def status(ctx, person=None):
    """État pour Paramètres (sans secrets)."""
    require_household(ctx.conn, hh(ctx))
    row = link_row(ctx)
    skips = ctx.conn.execute(
        f"SELECT COUNT(*) AS n FROM google_event_map WHERE household_id={hh(ctx)} AND sync_skip=1"
    ).fetchone()["n"]
    linked = bool(row and row["refresh_token_enc"] and not row["disconnected_at"])
    return {
        "configured": client_configured(),
        "linked": linked,
        "email": (row["email"] if row else "") or "",
        "allowed_email": ALLOWED_EMAIL,
        "mirror_calendar_id": (row["mirror_calendar_id"] if row else None),
        "last_sync_at": (row["last_sync_at"] if row else None),
        "last_sync_error": (row["last_sync_error"] if row else "") or "",
        "sync_skip_count": skips,
        "can_manage": bool(person and person.get("is_principal")),
    }


def start_connect(ctx, person, *, origin=None):
    require_principal(person)
    if not client_configured():
        raise AppError(503, "storage", "Google OAuth non configuré (variables FOYER_GOOGLE_*).")
    state = new_token()
    now = ctx.clock.now()
    created = iso_utc(now)
    expires = iso_utc(now + STATE_TTL)
    with write_tx(ctx):
        ctx.conn.execute(
            f"DELETE FROM google_oauth_pending WHERE household_id={hh(ctx)} OR expires_at < ?",
            (created,),
        )
        ctx.conn.execute(
            """INSERT INTO google_oauth_pending(state_hash, household_id, person_id, created_at, expires_at)
               VALUES(?,?,?,?,?)""",
            (hash_token(state), int(hh(ctx)), person["id"], created, expires),
        )
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(origin),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def complete_connect(ctx, person, *, code, state, origin=None):
    require_principal(person)
    if not code or not state:
        raise AppError(400, "validation", "Callback Google incomplet.")
    now = iso_utc(ctx.clock.now())
    pending = ctx.conn.execute(
        f"""SELECT p.* FROM google_oauth_pending p
            WHERE p.state_hash=? AND p.household_id={hh(ctx)} AND p.person_id=? AND p.expires_at >= ?""",
        (hash_token(state), person["id"], now),
    ).fetchone()
    if pending is None:
        raise AppError(400, "validation", "État OAuth invalide ou expiré. Recommencez la connexion.")
    with write_tx(ctx):
        ctx.conn.execute("DELETE FROM google_oauth_pending WHERE state_hash=?", (hash_token(state),))

    tokens = _exchange_code(code, origin=origin)
    refresh = tokens.get("refresh_token")
    access = tokens.get("access_token")
    if not access:
        raise AppError(502, "storage", "Google n'a pas renvoyé de jeton d'accès.")
    email = _fetch_email(access)
    if email.lower() != ALLOWED_EMAIL.lower():
        if refresh:
            _revoke(refresh)
        elif access:
            _revoke(access)
        audit(ctx.home, ctx.clock, "google_oauth_link", "email_refused", person["id"])
        raise AppError(
            403,
            "forbidden",
            f"Compte Google refusé. Utilisez {ALLOWED_EMAIL}.",
        )
    if not refresh:
        # Re-consent may omit refresh if already granted; keep previous if any.
        existing = link_row(ctx)
        if existing and existing["refresh_token_enc"] and not existing["disconnected_at"]:
            refresh = _open_token(ctx, existing["refresh_token_enc"])
        else:
            raise AppError(
                502,
                "storage",
                "Google n'a pas renvoyé de refresh token. Déconnectez l'app dans le compte Google puis réessayez.",
            )

    expires_at = _access_expiry(tokens, ctx.clock.now())
    existing_link = link_row(ctx)
    existing_mirror = existing_link["mirror_calendar_id"] if existing_link else None
    mirror_id = _ensure_mirror_calendar(access, existing_id=existing_mirror)
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""INSERT INTO google_oauth_link(
                  household_id, email, refresh_token_enc, access_token_enc, access_expires_at,
                  mirror_calendar_id, linked_by, linked_at, last_sync_at, last_sync_error, disconnected_at
                ) VALUES({hh(ctx)},?,?,?,?,?,?,?,NULL,'',NULL)
                ON CONFLICT(household_id) DO UPDATE SET
                  email=excluded.email,
                  refresh_token_enc=excluded.refresh_token_enc,
                  access_token_enc=excluded.access_token_enc,
                  access_expires_at=excluded.access_expires_at,
                  mirror_calendar_id=COALESCE(excluded.mirror_calendar_id, google_oauth_link.mirror_calendar_id),
                  linked_by=excluded.linked_by,
                  linked_at=excluded.linked_at,
                  last_sync_error='',
                  disconnected_at=NULL""",
            (
                email,
                _seal_token(ctx, refresh),
                _seal_token(ctx, access),
                expires_at,
                mirror_id,
                person["id"],
                moment,
            ),
        )
    audit(ctx.home, ctx.clock, "google_oauth_link", "ok", person["id"])
    return status(ctx, person)


def disconnect(ctx, person):
    require_principal(person)
    row = link_row(ctx)
    if row and row["refresh_token_enc"]:
        try:
            _revoke(_open_token(ctx, row["refresh_token_enc"]))
        except AppError:
            pass
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        if row:
            ctx.conn.execute(
                f"""UPDATE google_oauth_link SET refresh_token_enc=NULL, access_token_enc=NULL,
                     access_expires_at=NULL, disconnected_at=?, last_sync_error=''
                     WHERE household_id={hh(ctx)}""",
                (moment,),
            )
        else:
            ctx.conn.execute(
                f"""INSERT INTO google_oauth_link(household_id, disconnected_at, last_sync_error)
                    VALUES({hh(ctx)}, ?, '')""",
                (moment,),
            )
    audit(ctx.home, ctx.clock, "google_oauth_unlink", "ok", person["id"])
    return status(ctx, person)


def sync_now(ctx, person, *, force=True):
    """Synchronisation manuelle (principal) ou poll opportuniste."""
    if force:
        require_principal(person)
    if not is_linked(ctx):
        if force:
            raise AppError(409, "conflict", "Google Calendar n'est pas connecté.")
        return {"synced": False, "reason": "not_linked"}
    row = link_row(ctx)
    if not force and row["last_sync_at"]:
        try:
            last = datetime.fromisoformat(row["last_sync_at"].replace("Z", "+00:00"))
            if ctx.clock.now() - last < SYNC_INTERVAL:
                return {"synced": False, "reason": "fresh"}
        except ValueError:
            pass
    try:
        result = _run_sync(ctx, person)
        with write_tx(ctx):
            ctx.conn.execute(
                f"""UPDATE google_oauth_link SET last_sync_at=?, last_sync_error=''
                    WHERE household_id={hh(ctx)}""",
                (iso_utc(ctx.clock.now()),),
            )
        audit(ctx.home, ctx.clock, "google_sync", "ok", person["id"])
        return {"synced": True, **result}
    except AppError as exc:
        with write_tx(ctx):
            ctx.conn.execute(
                f"UPDATE google_oauth_link SET last_sync_error=? WHERE household_id={hh(ctx)}",
                (exc.message[:2000],),
            )
        audit(ctx.home, ctx.clock, "google_sync_error", exc.code, person["id"])
        if force:
            raise
        return {"synced": False, "reason": "error", "error": exc.message}


def maybe_sync(ctx, person):
    """Poll léger (Agenda) : sync si le miroir est lié et périmé."""
    if not is_linked(ctx):
        return None
    return sync_now(ctx, person, force=False)


def overlay_entries(ctx, *, start: date, end: date, q=""):
    if not is_linked(ctx):
        return []
    rows = ctx.conn.execute(
        f"""SELECT o.* FROM google_overlay_event o
            WHERE o.household_id={hh(ctx)}
              AND o.start_date <= ? AND o.end_date >= ?
            ORDER BY o.start_date, o.title""",
        (end.isoformat(), start.isoformat()),
    ).fetchall()
    needle = (q or "").strip().lower()
    entries = []
    for row in rows:
        if needle and needle not in (row["title"] or "").lower():
            continue
        entries.append({
            "kind": "google-external",
            "id": f"g:{row['google_calendar_id']}:{row['google_event_id']}",
            "title": row["title"],
            "start": row["start_date"],
            "end": row["end_date"],
            "who": row["calendar_name"],
            "people": set(),
            "calendar_name": row["calendar_name"],
            "readonly": True,
        })
    return entries


# --- OAuth / HTTP helpers -------------------------------------------------


def _exchange_code(code, *, origin=None):
    status, _headers, body = _http(
        "POST",
        TOKEN_URL,
        form={
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": _redirect_uri(origin),
            "grant_type": "authorization_code",
        },
    )
    return _json_response(status, body)


def _refresh_access(ctx, refresh_token):
    status, _headers, body = _http(
        "POST",
        TOKEN_URL,
        form={
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    return _json_response(status, body)


def _revoke(token):
    status, _headers, body = _http("POST", REVOKE_URL, form={"token": token})
    if status not in (200, 400):
        _json_response(status, body)


def _fetch_email(access_token):
    status, _headers, body = _http(
        "GET",
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    data = _json_response(status, body)
    email = (data.get("email") or "").strip()
    if not email:
        raise AppError(502, "storage", "Google n'a pas renvoyé d'adresse e-mail.")
    return email


def _access_expiry(tokens, now):
    expires_in = int(tokens.get("expires_in") or 3600)
    return iso_utc(now + timedelta(seconds=max(60, expires_in - 60)))


def _ensure_access(ctx):
    row = link_row(ctx)
    if not row or not row["refresh_token_enc"] or row["disconnected_at"]:
        raise AppError(409, "conflict", "Google Calendar n'est pas connecté.")
    access = _open_token(ctx, row["access_token_enc"]) if row["access_token_enc"] else ""
    expires = row["access_expires_at"] or ""
    now = iso_utc(ctx.clock.now())
    if access and expires and expires > now:
        return access, row
    refresh = _open_token(ctx, row["refresh_token_enc"])
    tokens = _refresh_access(ctx, refresh)
    access = tokens["access_token"]
    expires_at = _access_expiry(tokens, ctx.clock.now())
    with write_tx(ctx):
        ctx.conn.execute(
            f"""UPDATE google_oauth_link SET access_token_enc=?, access_expires_at=?
                WHERE household_id={hh(ctx)}""",
            (_seal_token(ctx, access), expires_at),
        )
    return access, link_row(ctx)


def _cal(method, path, access, *, query=None, json_body=None):
    url = CAL_API + path
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    status, _headers, body = _http(
        method,
        url,
        headers={"Authorization": f"Bearer {access}"},
        json_body=json_body,
    )
    if status == 204:
        return {}
    return _json_response(status, body, ok=(200, 201))


def _ensure_mirror_calendar(access, existing_id=None):
    if existing_id:
        try:
            cal = _cal("GET", f"/calendars/{urllib.parse.quote(existing_id, safe='')}", access)
            if cal.get("id"):
                return cal["id"]
        except AppError:
            pass
    listed = _cal("GET", "/users/me/calendarList", access, query={"maxResults": "250"})
    for item in listed.get("items") or []:
        if (item.get("summary") or "").strip() == MIRROR_CALENDAR_NAME:
            return item["id"]
    created = _cal("POST", "/calendars", access, json_body={"summary": MIRROR_CALENDAR_NAME})
    return created["id"]


# --- Mapping --------------------------------------------------------------


def _is_birthday(row):
    return (row["notes"] or "") == BIRTHDAY_NOTES


def _rrule_for(recurrence):
    return {
        "daily": "RRULE:FREQ=DAILY",
        "weekly": "RRULE:FREQ=WEEKLY",
        "monthly": "RRULE:FREQ=MONTHLY",
        "yearly": "RRULE:FREQ=YEARLY",
    }.get(recurrence)


def _parse_rrule(recurrence_list):
    if not recurrence_list:
        return "none", False
    if len(recurrence_list) != 1:
        return None, True
    raw = recurrence_list[0].upper().replace(" ", "")
    if not raw.startswith("RRULE:"):
        return None, True
    body = raw[6:]
    parts = dict(part.split("=", 1) for part in body.split(";") if "=" in part)
    freq = parts.get("FREQ")
    # Reject rich rules (exceptions / BY* / COUNT / UNTIL) in v1.
    if any(k.startswith("BY") or k in ("COUNT", "UNTIL", "INTERVAL") for k in parts if k != "FREQ"):
        if parts.get("INTERVAL") and parts.get("INTERVAL") != "1":
            return None, True
        if any(k.startswith("BY") or k in ("COUNT", "UNTIL") for k in parts):
            return None, True
    mapping = {"DAILY": "daily", "WEEKLY": "weekly", "MONTHLY": "monthly", "YEARLY": "yearly"}
    if freq not in mapping:
        return None, True
    return mapping[freq], False


def _to_google_body(local):
    start_date = local["start_date"]
    end_date = local["end_date"] or local["start_date"]
    # Google all-day end is exclusive.
    end_exclusive = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
    body = {
        "summary": local["title"],
        "description": local.get("notes") or "",
        "extendedProperties": {"private": {"new_arch_id": local["public_id"]}},
    }
    if local.get("all_day", True):
        body["start"] = {"date": start_date}
        body["end"] = {"date": end_exclusive}
    else:
        tz = local.get("timezone") or "Europe/Zurich"
        body["start"] = {"dateTime": f"{start_date}T09:00:00", "timeZone": tz}
        body["end"] = {"dateTime": f"{end_date}T10:00:00", "timeZone": tz}
    rrule = _rrule_for(local.get("recurrence") or "none")
    if rrule:
        body["recurrence"] = [rrule]
    return body


def _from_google_event(gevent, household_tz):
    start = gevent.get("start") or {}
    end = gevent.get("end") or {}
    if "date" in start:
        start_date = start["date"]
        end_excl = end.get("date") or start_date
        end_incl = (date.fromisoformat(end_excl) - timedelta(days=1)).isoformat()
        if end_incl < start_date:
            end_incl = start_date
        all_day = 1
        end_date = None if end_incl == start_date else end_incl
    else:
        start_dt = start.get("dateTime") or ""
        end_dt = end.get("dateTime") or start_dt
        start_date = start_dt[:10]
        end_date = end_dt[:10]
        if end_date == start_date:
            end_date = None
        all_day = 0
    recurrence, rich = _parse_rrule(gevent.get("recurrence") or [])
    return {
        "title": (gevent.get("summary") or "Sans titre")[:200],
        "notes": (gevent.get("description") or "")[:4000],
        "all_day": all_day,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": (start.get("timeZone") or end.get("timeZone") or household_tz),
        "recurrence": recurrence or "none",
        "rich_recurrence": rich or (recurrence is None and bool(gevent.get("recurrence"))),
        "public_id": ((gevent.get("extendedProperties") or {}).get("private") or {}).get("new_arch_id"),
        "etag": gevent.get("etag") or "",
        "updated": gevent.get("updated") or "",
        "status": gevent.get("status") or "confirmed",
        "google_id": gevent.get("id"),
    }


def _parse_updated(value):
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return datetime.min.replace(tzinfo=timezone.utc)


# --- Sync engine ----------------------------------------------------------


def _run_sync(ctx, person):
    access, row = _ensure_access(ctx)
    mirror_id = row["mirror_calendar_id"] or _ensure_mirror_calendar(access)
    if mirror_id != row["mirror_calendar_id"]:
        with write_tx(ctx):
            ctx.conn.execute(
                f"UPDATE google_oauth_link SET mirror_calendar_id=? WHERE household_id={hh(ctx)}",
                (mirror_id,),
            )
    household = require_household(ctx.conn, hh(ctx))
    pushed = _push_local(ctx, person, access, mirror_id)
    pulled = _pull_mirror(ctx, person, access, mirror_id, household["timezone"])
    overlay = _refresh_overlay(ctx, access, mirror_id, household["timezone"])
    return {"pushed": pushed, "pulled": pulled, "overlay": overlay}


def _push_local(ctx, person, access, mirror_id):
    rows = ctx.conn.execute(
        f"""SELECT e.* FROM calendar_event e
            WHERE e.household_id={hh(ctx)} AND e.archived=0
            ORDER BY e.id"""
    ).fetchall()
    count = 0
    for row in rows:
        if _is_birthday(row):
            continue
        mapping = ctx.conn.execute(
            f"""SELECT m.* FROM google_event_map m
                WHERE m.household_id={hh(ctx)} AND m.calendar_event_id=?""",
            (row["id"],),
        ).fetchone()
        if mapping and mapping["sync_skip"]:
            continue
        local = dict(row)
        body = _to_google_body(local)
        if mapping is None:
            created = _cal(
                "POST",
                f"/calendars/{urllib.parse.quote(mirror_id, safe='')}/events",
                access,
                json_body=body,
            )
            _upsert_map(
                ctx,
                calendar_event_id=row["id"],
                google_event_id=created["id"],
                etag=created.get("etag") or "",
                google_updated=created.get("updated") or "",
            )
            count += 1
            continue
        # Update if local is newer than last sync marker.
        # Si Google a aussi bougé depuis le dernier sync → conflit : Google gagne (pull).
        local_updated = _parse_updated(row["updated_at"])
        last_sync = _parse_updated(mapping["last_synced_at"])
        google_updated = _parse_updated(mapping["google_updated"])
        if local_updated <= last_sync:
            continue
        if google_updated > last_sync:
            continue
        updated = _cal(
            "PUT",
            f"/calendars/{urllib.parse.quote(mirror_id, safe='')}/events/{urllib.parse.quote(mapping['google_event_id'], safe='')}",
            access,
            json_body=body,
        )
        _upsert_map(
            ctx,
            calendar_event_id=row["id"],
            google_event_id=updated.get("id") or mapping["google_event_id"],
            etag=updated.get("etag") or "",
            google_updated=updated.get("updated") or "",
        )
        count += 1
    # Local archives → delete Google
    archived = ctx.conn.execute(
        f"""SELECT e.id, m.google_event_id FROM calendar_event e
            JOIN google_event_map m ON m.calendar_event_id=e.id AND m.household_id=e.household_id
            WHERE e.household_id={hh(ctx)} AND e.archived=1 AND m.sync_skip=0"""
    ).fetchall()
    for row in archived:
        try:
            _cal(
                "DELETE",
                f"/calendars/{urllib.parse.quote(mirror_id, safe='')}/events/{urllib.parse.quote(row['google_event_id'], safe='')}",
                access,
            )
        except AppError:
            pass
        with write_tx(ctx):
            ctx.conn.execute(
                f"DELETE FROM google_event_map WHERE household_id={hh(ctx)} AND calendar_event_id=?",
                (row["id"],),
            )
        count += 1
    return count


def _pull_mirror(ctx, person, access, mirror_id, household_tz):
    items = []
    page_token = None
    while True:
        data = _cal(
            "GET",
            f"/calendars/{urllib.parse.quote(mirror_id, safe='')}/events",
            access,
            query={
                "maxResults": "250",
                "singleEvents": "false",
                "showDeleted": "true",
                "pageToken": page_token,
            },
        )
        items.extend(data.get("items") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    count = 0
    seen_google_ids = set()
    for gevent in items:
        gid = gevent.get("id")
        if not gid:
            continue
        seen_google_ids.add(gid)
        parsed = _from_google_event(gevent, household_tz)
        mapping = ctx.conn.execute(
            f"""SELECT m.* FROM google_event_map m
                WHERE m.household_id={hh(ctx)} AND m.google_event_id=?""",
            (gid,),
        ).fetchone()
        if parsed["status"] == "cancelled":
            if mapping:
                try:
                    events_svc.archive_event(ctx, person, mapping["calendar_event_id"], check_module=False)
                except AppError:
                    pass
                with write_tx(ctx):
                    ctx.conn.execute(
                        f"DELETE FROM google_event_map WHERE household_id={hh(ctx)} AND google_event_id=?",
                        (gid,),
                    )
                count += 1
            continue
        if parsed["rich_recurrence"]:
            if mapping:
                with write_tx(ctx):
                    ctx.conn.execute(
                        f"""UPDATE google_event_map SET sync_skip=1, etag=?, google_updated=?, last_synced_at=?
                            WHERE household_id={hh(ctx)} AND google_event_id=?""",
                        (parsed["etag"], parsed["updated"], iso_utc(ctx.clock.now()), gid),
                    )
            continue
        if mapping is None and parsed["public_id"]:
            local = ctx.conn.execute(
                f"""SELECT id FROM calendar_event
                    WHERE household_id={hh(ctx)} AND public_id=? AND archived=0""",
                (parsed["public_id"],),
            ).fetchone()
            if local:
                _upsert_map(
                    ctx,
                    calendar_event_id=local["id"],
                    google_event_id=gid,
                    etag=parsed["etag"],
                    google_updated=parsed["updated"],
                )
                mapping = ctx.conn.execute(
                    f"""SELECT m.* FROM google_event_map m
                        WHERE m.household_id={hh(ctx)} AND m.google_event_id=?""",
                    (gid,),
                ).fetchone()
        if mapping is None:
            event_id = events_svc.create_event(
                ctx,
                person,
                {
                    "title": parsed["title"],
                    "notes": parsed["notes"],
                    "all_day": parsed["all_day"],
                    "start_date": parsed["start_date"],
                    "end_date": parsed["end_date"],
                    "timezone": parsed["timezone"],
                    "recurrence": parsed["recurrence"],
                },
                check_module=False,
            )
            local = ctx.conn.execute(
                f"SELECT public_id FROM calendar_event WHERE id=? AND household_id={hh(ctx)}",
                (event_id,),
            ).fetchone()
            try:
                _cal(
                    "PATCH",
                    f"/calendars/{urllib.parse.quote(mirror_id, safe='')}/events/{urllib.parse.quote(gid, safe='')}",
                    access,
                    json_body={
                        "extendedProperties": {"private": {"new_arch_id": local["public_id"]}},
                    },
                )
            except AppError:
                pass
            _upsert_map(
                ctx,
                calendar_event_id=event_id,
                google_event_id=gid,
                etag=parsed["etag"],
                google_updated=parsed["updated"],
            )
            count += 1
            continue
        if mapping["sync_skip"]:
            continue
        local = ctx.conn.execute(
            f"""SELECT e.* FROM calendar_event e
                WHERE e.id=? AND e.household_id={hh(ctx)} AND e.archived=0""",
            (mapping["calendar_event_id"],),
        ).fetchone()
        if local is None:
            continue
        google_updated = _parse_updated(parsed["updated"])
        local_updated = _parse_updated(local["updated_at"])
        last_sync = _parse_updated(mapping["last_synced_at"])
        both_dirty = local_updated > last_sync and google_updated > last_sync
        google_newer = google_updated > local_updated
        if both_dirty:
            audit(
                ctx.home, ctx.clock, "google_sync_conflict", "google_wins",
                person["id"], "calendar_event", local["id"],
            )
        if google_newer or both_dirty:
            events_svc.update_event(
                ctx,
                person,
                local["id"],
                {
                    "title": parsed["title"],
                    "notes": parsed["notes"],
                    "all_day": parsed["all_day"],
                    "start_date": parsed["start_date"],
                    "end_date": parsed["end_date"],
                    "timezone": parsed["timezone"],
                    "recurrence": parsed["recurrence"],
                },
                check_module=False,
            )
            _upsert_map(
                ctx,
                calendar_event_id=local["id"],
                google_event_id=gid,
                etag=parsed["etag"],
                google_updated=parsed["updated"],
            )
            count += 1
        else:
            _upsert_map(
                ctx,
                calendar_event_id=local["id"],
                google_event_id=gid,
                etag=parsed["etag"],
                google_updated=parsed["updated"],
            )
    return count


def _refresh_overlay(ctx, access, mirror_id, household_tz):
    today = date.fromisoformat(iso_utc(ctx.clock.now())[:10])
    window_start = (today - timedelta(days=OVERLAY_PAST_DAYS)).isoformat()
    window_end = (today + timedelta(days=OVERLAY_FUTURE_DAYS)).isoformat()
    calendars = _cal("GET", "/users/me/calendarList", access, query={"maxResults": "250"})
    refreshed = iso_utc(ctx.clock.now())
    count = 0
    with write_tx(ctx):
        ctx.conn.execute(f"DELETE FROM google_overlay_event WHERE household_id={hh(ctx)}")
    for cal in calendars.get("items") or []:
        cid = cal.get("id")
        if not cid or cid == mirror_id:
            continue
        name = (cal.get("summary") or "Google")[:200]
        page_token = None
        while True:
            data = _cal(
                "GET",
                f"/calendars/{urllib.parse.quote(cid, safe='')}/events",
                access,
                query={
                    "maxResults": "250",
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "timeMin": f"{window_start}T00:00:00Z",
                    "timeMax": f"{window_end}T23:59:59Z",
                    "pageToken": page_token,
                },
            )
            for gevent in data.get("items") or []:
                if (gevent.get("status") or "") == "cancelled":
                    continue
                parsed = _from_google_event(gevent, household_tz)
                end_date = parsed["end_date"] or parsed["start_date"]
                with write_tx(ctx):
                    ctx.conn.execute(
                        f"""INSERT INTO google_overlay_event(
                              household_id, google_calendar_id, calendar_name, google_event_id,
                              title, start_date, end_date, all_day, refreshed_at
                            ) VALUES({hh(ctx)},?,?,?,?,?,?,?,?)
                            ON CONFLICT(household_id, google_calendar_id, google_event_id) DO UPDATE SET
                              calendar_name=excluded.calendar_name,
                              title=excluded.title,
                              start_date=excluded.start_date,
                              end_date=excluded.end_date,
                              all_day=excluded.all_day,
                              refreshed_at=excluded.refreshed_at""",
                        (
                            cid,
                            name,
                            parsed["google_id"],
                            parsed["title"],
                            parsed["start_date"],
                            end_date,
                            parsed["all_day"],
                            refreshed,
                        ),
                    )
                count += 1
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return count


def _upsert_map(ctx, *, calendar_event_id, google_event_id, etag, google_updated):
    moment = iso_utc(ctx.clock.now())
    with write_tx(ctx):
        existing = ctx.conn.execute(
            f"""SELECT id FROM google_event_map
                WHERE household_id={hh(ctx)} AND calendar_event_id=?""",
            (calendar_event_id,),
        ).fetchone()
        if existing:
            ctx.conn.execute(
                """UPDATE google_event_map
                   SET google_event_id=?, etag=?, google_updated=?, last_synced_at=?, sync_skip=0
                   WHERE id=?""",
                (google_event_id, etag, google_updated, moment, existing["id"]),
            )
        else:
            ctx.conn.execute(
                f"""INSERT INTO google_event_map(
                      household_id, calendar_event_id, google_event_id, etag, google_updated,
                      last_synced_at, sync_skip
                    ) VALUES({hh(ctx)},?,?,?,?,?,0)""",
                (calendar_event_id, google_event_id, etag, google_updated, moment),
            )
