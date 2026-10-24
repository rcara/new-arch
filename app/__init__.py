"""Application locale. Écoute prévue sur 127.0.0.1 seulement."""

import os
import traceback
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from .audit import audit
from .clock import SystemClock
from .db import any_household, connect, ensure_layout, household_row
from .errors import AppError
from .http import MESSAGES, cookie_message, guard_local, resolve_theme, safe_next
from .locks import OpLock
from .present import STATUS_LABEL, format_cents, format_date, format_timestamp
from .security import AttemptLimiter, hash_password, new_token
from .services.auth import load_session
from .services.vault import reconcile
from .validate import CATEGORIES

ROOT = Path(__file__).resolve().parents[1]


class Ctx:
    def __init__(
        self,
        conn,
        clock,
        home,
        lock,
        dummy_hash,
        actor_id=None,
        crypto=None,
        household_id=None,
        login_person_id=None,
    ):
        self.conn = conn
        self.clock = clock
        self.home = home
        self.lock = lock
        self.dummy_hash = dummy_hash
        self.actor_id = actor_id
        self.crypto = crypto
        self.household_id = household_id
        self.login_person_id = login_person_id


def create_app(home=None, clock=None, testing=False, port=8765):
    from .crypto import load_state

    home = Path(home or os.environ.get("FOYER_HOME") or ROOT)
    ensure_layout(home)
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.testing = testing
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 22 * 1024 * 1024
    app.config["HOME"] = home
    app.config["CLOCK"] = clock or SystemClock()
    app.config["LOCK"] = OpLock(home / "data" / "op.lock")
    app.config["LIMITER"] = AttemptLimiter()
    app.config["DUMMY_HASH"] = hash_password(new_token())
    app.config["CRYPTO"] = load_state(home)
    # Derrière Cloudflare Tunnel : Host/Origin publics (REMOTE_ADDR reste 127.0.0.1).
    public_host = (os.environ.get("FOYER_PUBLIC_HOST") or "").strip()
    public_origin = (os.environ.get("FOYER_PUBLIC_ORIGIN") or "").strip()
    app.config["EXPECTED_HOST"] = public_host or f"127.0.0.1:{port}"
    app.config["EXPECTED_ORIGIN"] = public_origin or f"http://127.0.0.1:{port}"
    app.config["PORT"] = port
    app.json.ensure_ascii = False
    app.secret_key = new_token()

    startup = connect(home / "data" / "metadata.sqlite")
    try:
        reconcile(home, startup)
    finally:
        startup.close()

    from .routes.api import api
    from .routes.pages import pages
    app.register_blueprint(pages)
    app.register_blueprint(api, url_prefix="/api")

    @app.before_request
    def prepare():
        g.db = connect(app.config["HOME"] / "data" / "metadata.sqlite")
        g.bootstrapped = any_household(g.db)
        row = load_session(g.db, app.config["CLOCK"], request.cookies.get("foyer_session"))
        if row is None:
            g.person = None
            g.csrf_token = ""
            g.household = None
        else:
            g.person = {
                "id": row["id"],
                "display_name": row["display_name"],
                "is_principal": bool(row["is_principal"]),
                "can_view_index": bool(row["can_view_index"]),
                "active": bool(row["active"]),
                "relationship": row["relationship"],
                "household_id": row["household_id"],
                "login_person_id": row["login_person_id"],
            }
            g.csrf_token = row["csrf_token"]
            active = household_row(g.db, row["household_id"])
            g.household = dict(active) if active is not None else None
        code = request.cookies.get("foyer_msg")
        g.message = MESSAGES.get(code, "")
        g.clear_message = bool(code)
        guard_local()
        endpoint = request.endpoint or ""
        public = {
            "pages.bootstrap_get",
            "pages.bootstrap_post",
            "pages.login_get",
            "pages.login_post",
            "api.bootstrap",
            "api.login",
            "static",
        }
        if not g.bootstrapped and endpoint not in public and endpoint != "static":
            if request.path.startswith("/api"):
                raise AppError(409, "conflict", "Le foyer n'est pas initialisé.")
            if endpoint != "pages.bootstrap_get":
                return redirect(url_for("pages.bootstrap_get"))
        if g.bootstrapped and endpoint in {"pages.bootstrap_get", "pages.bootstrap_post", "api.bootstrap"}:
            raise AppError(409, "conflict", "Le foyer existe déjà.")
        if g.person is not None and g.household is not None:
            from .services import modules as modules_svc
            module = modules_svc.module_for_path(request.path)
            if module:
                modules_svc.require_module(current_ctx(), module)

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def harden(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; font-src 'self'; script-src 'self'; "
            "img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if g.get("csrf_token"):
            response.headers["X-CSRF-Token"] = g.csrf_token
        if request.method == "GET" and g.get("clear_message"):
            response.delete_cookie("foyer_msg", path="/")
        return response

    @app.context_processor
    def shell():
        endpoint = request.endpoint or ""
        name = endpoint.split(".")[-1]
        sub = ""
        if name.startswith("milestone"):
            nav = "reperes"
        elif name.startswith("decision"):
            nav = "decisions"
        elif name.startswith("vault") or name.startswith("file"):
            nav = "coffre"
        elif name.startswith("people") or name.startswith("person") or name.startswith("account") or name.startswith("deactivate"):
            nav = "personnes"
        elif name.startswith("access"):
            nav = "acces"
        elif name.startswith("task"):
            nav = "organisation"
        elif name.startswith("event"):
            nav = "calendrier"
        elif name.startswith("sejour"):
            nav = "sejours"
        elif name.startswith("search"):
            nav = "recherche"
        elif name.startswith("foyer"):
            nav = "foyer"
        elif name.startswith("settings_advanced"):
            nav = "avance"
        elif name.startswith("settings"):
            nav = "parametres"
        elif name.startswith("profile"):
            nav = "profil"
        elif name.startswith("finance"):
            nav = "finances"
            if name == "finance_get":
                sub = request.args.get("vue") or "apercu"
            elif name.startswith("finance_budget"):
                sub = "budgets"
            else:
                sub = "transactions"
        elif name.startswith("inventory") or name.startswith("inventaire"):
            nav = "inventaire"
        elif name.startswith("media"):
            nav = "mediatheque"
        elif name.startswith("today"):
            nav = "today"
        else:
            nav = ""
        nav_modules = set()
        if g.get("household") is not None and g.get("person") is not None and g.get("db") is not None:
            from .services import modules as modules_svc
            nav_modules = modules_svc.enabled_keys(current_ctx())
        from .navigation import build as build_navigation
        return {
            "shell": build_navigation(g.get("person"), nav_modules, nav, request.path if request.method == "GET" else "/", sub),
            "today_iso": _today_iso(),
            "next_url": safe_next(request.values.get("next")) if request.values.get("next") else "",
            "person": g.get("person"),
            "household": g.get("household"),
            "csrf_token": g.get("setup_token") or g.get("csrf_token") or "",
            "message": g.get("message") or "",
            "nav": nav,
            "nav_modules": nav_modules,
            "theme": resolve_theme(request.cookies.get("foyer_theme")),
            "categories": CATEGORIES,
            "status_label": STATUS_LABEL,
            "format_date": format_date,
            "format_cents": format_cents,
        }

    @app.template_filter("frdate")
    def frdate(value):
        return format_date(value)

    @app.template_filter("frcents")
    def frcents(value):
        return format_cents(value)

    @app.template_filter("frtime")
    def frtime(value):
        timezone_name = (g.get("household") or {}).get("timezone", "Europe/Zurich")
        return format_timestamp(value, timezone_name) if value else ""

    @app.errorhandler(AppError)
    def on_app(exc):
        if request.path.startswith("/api"):
            return jsonify(exc.payload()), exc.status
        if exc.status == 401:
            return redirect(url_for("pages.login_get"))
        return render_template("error.html", status=exc.status, text=exc.message), exc.status

    @app.errorhandler(404)
    def on_404(_exc):
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": "not_found", "message": "Introuvable.", "fields": {}}}), 404
        return render_template("error.html", status=404, text="Introuvable."), 404

    @app.errorhandler(405)
    def on_405(_exc):
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": "validation", "message": "Méthode refusée.", "fields": {}}}), 405
        return render_template("error.html", status=405, text="Méthode refusée."), 405

    @app.errorhandler(RequestEntityTooLarge)
    def on_large(_exc):
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": "too_large", "message": "Le fichier dépasse 20 Mio.", "fields": {}}}), 413
        return render_template("error.html", status=413, text="Le fichier dépasse 20 Mio."), 413

    @app.errorhandler(Exception)
    def on_error(exc):
        if isinstance(exc, AppError):
            return on_app(exc)
        if app.testing:
            traceback.print_exc()
        audit(home, app.config["CLOCK"], "error", type(exc).__name__)
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": "storage", "message": "Opération impossible.", "fields": {}}}), 500
        return render_template("error.html", status=500, text="Opération impossible."), 500

    return app


def _today_iso():
    from flask import current_app
    from .clock import civil_today
    household = g.get("household")
    if not household:
        return ""
    return civil_today(current_app.config["CLOCK"], household.get("timezone", "Europe/Zurich")).isoformat()


def current_ctx():
    from flask import current_app
    person = g.get("person") or {}
    household = g.get("household") or {}
    return Ctx(
        g.db,
        current_app.config["CLOCK"],
        current_app.config["HOME"],
        current_app.config["LOCK"],
        current_app.config["DUMMY_HASH"],
        person.get("id"),
        current_app.config.get("CRYPTO"),
        person.get("household_id") or household.get("id"),
        person.get("login_person_id"),
    )
