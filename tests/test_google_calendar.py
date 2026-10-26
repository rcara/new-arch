"""Google Calendar : OAuth foyer, mapping, sync LWW, overlay, pas de secrets en repo."""

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app import create_app
from app.clock import FrozenClock
from app.crypto import MAGIC, enable, is_ciphertext, load_state
from app.db import connect, init_db
from app.services import google_calendar as gcal
from tests.test_flows import HOST, ORIGIN, PASSWORD, Web

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = "rcara.home@gmail.com"


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def world(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("FOYER_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("FOYER_GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("FOYER_GOOGLE_REDIRECT_URI", f"{ORIGIN}/oauth/google/callback")
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    gcal.reset_http_transport()
    yield web, app, home, clock
    gcal.reset_http_transport()


def _ctx(app, home, clock):
    from app import Ctx
    from flask import g

    conn = connect(home / "data" / "metadata.sqlite")
    person = conn.execute("SELECT id FROM person WHERE is_principal=1").fetchone()
    return Ctx(
        conn, clock, home, app.config["LOCK"], app.config["DUMMY_HASH"],
        person["id"], app.config.get("CRYPTO"), 1, person["id"],
    ), {"id": person["id"], "is_principal": True}


class FakeGoogle:
    """Transport HTTP minimal pour OAuth + Calendar API."""

    def __init__(self):
        self.refresh = "refresh-token-xyz"
        self.access = "access-token-abc"
        self.email = ALLOWED
        self.mirror_id = "cal-new-arch"
        self.mirror_events = {}  # id -> event dict
        self.other_events = {}  # cal_id -> {id: event}
        self.calendars = [
            {"id": "primary", "summary": "Personnel"},
            {"id": self.mirror_id, "summary": "New Arch"},
        ]
        self.calls = []
        self._seq = 0

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, body))
        parsed = urlparse(url)
        path = parsed.path
        if path.endswith("/token") and method == "POST":
            form = parse_qs(body.decode() if body else "")
            grant = (form.get("grant_type") or [""])[0]
            payload = {
                "access_token": self.access,
                "expires_in": 3600,
                "token_type": "Bearer",
            }
            if grant == "authorization_code":
                payload["refresh_token"] = self.refresh
            return 200, {}, json.dumps(payload).encode()
        if path.endswith("/revoke"):
            return 200, {}, b""
        if path.endswith("/userinfo"):
            return 200, {}, json.dumps({"email": self.email}).encode()
        if path.endswith("/users/me/calendarList"):
            return 200, {}, json.dumps({"items": self.calendars}).encode()
        if path.endswith("/calendars") and method == "POST":
            self._seq += 1
            cid = f"cal-created-{self._seq}"
            summary = json.loads(body.decode()).get("summary")
            self.calendars.append({"id": cid, "summary": summary})
            self.mirror_id = cid
            return 200, {}, json.dumps({"id": cid, "summary": summary}).encode()
        m = re.search(r"/calendars/([^/]+)/events(?:/([^/]+))?$", path)
        if m:
            cal_id = m.group(1)
            event_id = m.group(2)
            store = self.mirror_events if cal_id == self.mirror_id else self.other_events.setdefault(cal_id, {})
            if method == "GET" and not event_id:
                return 200, {}, json.dumps({"items": list(store.values())}).encode()
            if method == "POST":
                self._seq += 1
                eid = f"gev-{self._seq}"
                data = json.loads(body.decode())
                data["id"] = eid
                data["etag"] = f"etag-{eid}"
                data["updated"] = "2027-02-20T08:00:00.000Z"
                data["status"] = "confirmed"
                store[eid] = data
                return 200, {}, json.dumps(data).encode()
            if method in ("PUT", "PATCH") and event_id:
                data = json.loads(body.decode())
                current = store.get(event_id, {"id": event_id})
                current.update(data)
                current["etag"] = f"etag-{event_id}-u"
                current["updated"] = "2027-02-20T09:00:00.000Z"
                current["status"] = current.get("status") or "confirmed"
                store[event_id] = current
                return 200, {}, json.dumps(current).encode()
            if method == "DELETE" and event_id:
                store.pop(event_id, None)
                return 204, {}, b""
            if method == "GET" and event_id:
                return 200, {}, json.dumps(store[event_id]).encode()
        if re.search(r"/calendars/[^/]+$", path) and method == "GET":
            cid = path.rsplit("/", 1)[-1]
            for cal in self.calendars:
                if cal["id"] == cid:
                    return 200, {}, json.dumps(cal).encode()
            return 404, {}, json.dumps({"error": {"message": "not found"}}).encode()
        return 500, {}, json.dumps({"error": {"message": f"unhandled {method} {url}"}}).encode()


def test_migration_google_calendar(tmp_path):
    db_path = tmp_path / "metadata.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "google_oauth_link", "google_oauth_pending", "google_event_map", "google_overlay_event",
    } <= tables
    conn.close()


def test_no_google_secrets_in_repo():
    forbidden = ("GOCSPX-", "client_secret", "ya29.", "1//")
    # Tracked sources only — ignore venv / local data if any.
    for path in list(ROOT.glob("app/**/*.py")) + list(ROOT.glob("deploy/**/*")) + [
        ROOT / "requirements.in", ROOT / "requirements.txt", ROOT / "DEPLOY.md",
    ]:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "FOYER_GOOGLE_CLIENT_SECRET=" not in text or "PASTE" in text or "…" in text or "Environment=" in text
        # Real-looking secret material must not appear.
        for needle in ("GOCSPX-", "ya29."):
            assert needle not in text


def test_connect_requires_csrf_and_principal(world):
    web, app, home, clock = world
    # CSRF missing
    bad = web.c.post(
        "/parametres/google/connect",
        data={},
        headers={"Host": HOST, "Origin": ORIGIN},
    )
    assert bad.status_code in (400, 403)
    # Secondary cannot connect
    web.get("/personnes/ajouter")
    web.submit("/personnes", {
        "display_name": "Léa",
        "relationship": "conjoint",
        "with_account": "oui",
        "username": "lea",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    })
    web.submit("/deconnexion", {})
    web2 = Web(app)
    web2.login("lea")
    denied = web2.submit("/parametres/google/connect", {}, follow=False)
    assert denied.status_code == 403


def test_oauth_start_and_email_allowlist(world):
    web, app, home, clock = world
    fake = FakeGoogle()
    gcal.set_http_transport(fake)

    started = web.submit("/parametres/google/connect", {}, follow=False)
    assert started.status_code == 302
    loc = started.headers["Location"]
    assert loc.startswith("https://accounts.google.com/")
    qs = parse_qs(urlparse(loc).query)
    assert "calendar" in qs["scope"][0]
    state = qs["state"][0]
    assert qs["access_type"] == ["offline"]

    # Wrong email refused
    fake.email = "intrus@gmail.com"
    refused = web.get(f"/oauth/google/callback?code=abc&state={state}")
    assert refused.status_code in (200, 302)
    page = web.get("/parametres").data.decode()
    assert "refusé" in page.lower() or "Connecter Google" in page
    ctx, person = _ctx(app, home, clock)
    assert not gcal.is_linked(ctx)
    ctx.conn.close()

    # Fresh state + allowed email
    fake.email = ALLOWED
    started = web.submit("/parametres/google/connect", {}, follow=False)
    state = parse_qs(urlparse(started.headers["Location"]).query)["state"][0]
    ok = web.get(f"/oauth/google/callback?code=ok&state={state}")
    assert ok.status_code in (200, 302)
    page = web.get("/parametres").data.decode()
    assert ALLOWED in page
    assert "Synchroniser maintenant" in page
    ctx, person = _ctx(app, home, clock)
    assert gcal.is_linked(ctx)
    row = gcal.link_row(ctx)
    token = gcal._open_token(ctx, row["refresh_token_enc"])
    assert token == fake.refresh
    ctx.conn.close()


def test_refresh_token_sealed_when_crypto_on(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("FOYER_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("FOYER_GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("FOYER_GOOGLE_REDIRECT_URI", f"{ORIGIN}/oauth/google/callback")
    home = tmp_path / "crypto-inst"
    enable(home, "phrase-secrete-12")
    monkeypatch.setenv("FOYER_PASSPHRASE", "phrase-secrete-12")
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    fake = FakeGoogle()
    gcal.set_http_transport(fake)
    started = web.submit("/parametres/google/connect", {}, follow=False)
    state = parse_qs(urlparse(started.headers["Location"]).query)["state"][0]
    web.get(f"/oauth/google/callback?code=ok&state={state}")
    ctx, person = _ctx(app, home, clock)
    row = gcal.link_row(ctx)
    assert is_ciphertext(bytes(row["refresh_token_enc"]))
    assert bytes(row["refresh_token_enc"])[:4] == MAGIC
    assert gcal._open_token(ctx, row["refresh_token_enc"]) == fake.refresh
    ctx.conn.close()
    gcal.reset_http_transport()


def test_sync_push_pull_conflict_birthdays_overlay(world):
    web, app, home, clock = world
    fake = FakeGoogle()
    gcal.set_http_transport(fake)

    # Link
    started = web.submit("/parametres/google/connect", {}, follow=False)
    state = parse_qs(urlparse(started.headers["Location"]).query)["state"][0]
    web.get(f"/oauth/google/callback?code=ok&state={state}")

    # Local event
    created = web.api("POST", "/api/events", {
        "title": "Dentiste", "start_date": "2027-03-01", "all_day": True, "recurrence": "none",
    })
    assert created.status_code == 201 or created.status_code == 200 or created.get_json()
    # API may return {id: ...} — accept either
    payload = created.get_json() or {}
    event_id = payload.get("id") or payload.get("event_id")
    if not event_id:
        # Some APIs return 200 with item
        conn = connect(home / "data" / "metadata.sqlite")
        event_id = conn.execute("SELECT id FROM calendar_event WHERE title='Dentiste'").fetchone()[0]
        conn.close()

    # Birthday seed-like event must not push
    conn = connect(home / "data" / "metadata.sqlite")
    t = "2027-02-20T08:00:00Z"
    conn.execute(
        """INSERT INTO calendar_event(
             household_id, public_id, title, notes, all_day, start_date, end_date,
             timezone, responsible_id, created_by, recurrence, archived, created_at, updated_at
           ) VALUES(1, ?, 'Anniversaire de Test', 'Anniversaire familial', 1, '2000-05-01', NULL,
                    'Europe/Berlin', NULL, 1, 'yearly', 0, ?, ?)""",
        ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", t, t),
    )
    conn.commit()
    conn.close()

    # External calendar event for overlay
    fake.other_events["primary"] = {
        "school-1": {
            "id": "school-1",
            "summary": "Réunion école",
            "status": "confirmed",
            "start": {"date": "2027-03-05"},
            "end": {"date": "2027-03-06"},
            "updated": "2027-02-19T10:00:00.000Z",
            "etag": "e1",
        }
    }

    # Google-side creation on mirror (phone)
    fake.mirror_events["phone-1"] = {
        "id": "phone-1",
        "summary": "Depuis le téléphone",
        "description": "",
        "status": "confirmed",
        "start": {"date": "2027-03-10"},
        "end": {"date": "2027-03-11"},
        "updated": "2027-02-20T07:00:00.000Z",
        "etag": "p1",
    }

    sync = web.submit("/parametres/google/sync-now", {})
    assert sync.status_code == 200
    assert any(title == "Dentiste" for ev in fake.mirror_events.values() for title in [ev.get("summary")])
    assert not any(ev.get("summary", "").startswith("Anniversaire") for ev in fake.mirror_events.values())

    conn = connect(home / "data" / "metadata.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM google_event_map").fetchone()[0] >= 2
    phone = conn.execute(
        "SELECT title FROM calendar_event WHERE title='Depuis le téléphone' AND archived=0"
    ).fetchone()
    assert phone is not None
    overlay = conn.execute(
        "SELECT title, calendar_name FROM google_overlay_event WHERE title='Réunion école'"
    ).fetchone()
    assert overlay is not None
    assert overlay["calendar_name"] == "Personnel"
    conn.close()

    agenda = web.get("/calendrier?vue=liste&date=2027-03-01").data.decode()
    assert "Réunion école" in agenda
    assert "Google" in agenda
    assert "lecture seule" in agenda

    # Conflict: both dirty → Google wins
    ctx, person = _ctx(app, home, clock)
    mapping = ctx.conn.execute(
        "SELECT * FROM google_event_map WHERE calendar_event_id=?", (event_id,)
    ).fetchone()
    gid = mapping["google_event_id"]
    # Mark last_sync in the past
    ctx.conn.execute(
        "UPDATE google_event_map SET last_synced_at='2027-02-20T07:00:00Z' WHERE id=?",
        (mapping["id"],),
    )
    ctx.conn.execute(
        "UPDATE calendar_event SET title='Local plus tard', updated_at='2027-02-20T08:30:00Z' WHERE id=?",
        (event_id,),
    )
    ctx.conn.commit()
    fake.mirror_events[gid]["summary"] = "Google gagne"
    fake.mirror_events[gid]["updated"] = "2027-02-20T08:45:00.000Z"
    fake.mirror_events[gid]["start"] = {"date": "2027-03-01"}
    fake.mirror_events[gid]["end"] = {"date": "2027-03-02"}
    gcal.sync_now(ctx, person, force=True)
    title = ctx.conn.execute("SELECT title FROM calendar_event WHERE id=?", (event_id,)).fetchone()[0]
    assert title == "Google gagne"
    log = (home / "logs" / "audit.log").read_text(encoding="utf-8")
    assert "google_sync_conflict" in log
    assert "test-client-secret" not in log
    assert fake.refresh not in log
    ctx.conn.close()


def test_disconnect_keeps_maps(world):
    web, app, home, clock = world
    fake = FakeGoogle()
    gcal.set_http_transport(fake)
    started = web.submit("/parametres/google/connect", {}, follow=False)
    state = parse_qs(urlparse(started.headers["Location"]).query)["state"][0]
    web.get(f"/oauth/google/callback?code=ok&state={state}")
    web.api("POST", "/api/events", {"title": "A", "start_date": "2027-04-01", "all_day": True})
    web.submit("/parametres/google/sync-now", {})
    conn = connect(home / "data" / "metadata.sqlite")
    maps_before = conn.execute("SELECT COUNT(*) FROM google_event_map").fetchone()[0]
    conn.close()
    assert maps_before >= 1
    web.submit("/parametres/google/disconnect", {})
    ctx, person = _ctx(app, home, clock)
    assert not gcal.is_linked(ctx)
    assert ctx.conn.execute("SELECT COUNT(*) FROM google_event_map").fetchone()[0] == maps_before
    ctx.conn.close()


def test_archive_event_helper(world):
    web, app, home, clock = world
    web.api("POST", "/api/events", {"title": "Temp", "start_date": "2027-05-01", "all_day": True})
    ctx, person = _ctx(app, home, clock)
    from app.services import events as events_svc
    eid = ctx.conn.execute("SELECT id FROM calendar_event WHERE title='Temp'").fetchone()[0]
    events_svc.archive_event(ctx, person, eid)
    assert ctx.conn.execute("SELECT archived FROM calendar_event WHERE id=?", (eid,)).fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        ctx.conn.execute("DELETE FROM calendar_event WHERE id=?", (eid,))
    ctx.conn.close()
