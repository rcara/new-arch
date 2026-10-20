"""Application locale. Écoute prévue sur 127.0.0.1 seulement."""

import os
import traceback
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from .audit import audit
from .clock import SystemClock
from .db import connect, ensure_layout, household_row
from .errors import AppError
from .http import MESSAGES, cookie_message, guard_local
from .locks import OpLock
from .present import STATUS_LABEL, format_cents, format_date, format_timestamp
from .security import AttemptLimiter, hash_password, new_token
from .services.auth import load_session
from .services.vault import reconcile
from .validate import CATEGORIES

ROOT = Path(__file__).resolve().parents[1]


class Ctx:
    def __init__(self, conn, clock, home, lock, dummy_hash, actor_id=None):
        self.conn = conn
        self.clock = clock
        self.home = home
        self.lock = lock
        self.dummy_hash = dummy_hash
        self.actor_id = actor_id


def create_app(home=None, clock=None, testing=False, port=8765):
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
    app.config["EXPECTED_HOST"] = f"127.0.0.1:{port}"
    app.config["EXPECTED_ORIGIN"] = f"http://127.0.0.1:{port}"
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
        g.household = household_row(g.db)
        if g.household is not None:
            g.household = dict(g.household)
        row = load_session(g.db, app.config["CLOCK"], request.cookies.get("foyer_session"))
        if row is None:
            g.person = None
            g.csrf_token = ""
        else:
            g.person = {
                "id": row["id"],
                "display_name": row["display_name"],
                "is_principal": bool(row["is_principal"]),
                "can_view_index": bool(row["can_view_index"]),
                "active": bool(row["active"]),
                "relationship": row["relationship"],
            }
            g.csrf_token = row["csrf_token"]
        code = request.cookies.get("foyer_msg")
        g.message = MESSAGES.get(code, "")
        g.clear_message = bool(code)
        guard_local()
        endpoint = request.endpoint or ""
        public = {"pages.bootstrap_get", "pages.bootstrap_post", "pages.login_get", "pages.login_post", "api.bootstrap", "api.login", "static"}
        if g.household is None and endpoint not in public and endpoint != "static":
            if request.path.startswith("/api"):
                raise AppError(409, "conflict", "Le foyer n'est pas initialisé.")
            if endpoint != "pages.bootstrap_get":
                return redirect(url_for("pages.bootstrap_get"))
        if g.household is not None and endpoint in {"pages.bootstrap_get", "pages.bootstrap_post", "api.bootstrap"}:
            raise AppError(409, "conflict", "Le foyer existe déjà.")

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def harden(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'none'; img-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
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
        elif name.startswith("today"):
            nav = "today"
        else:
            nav = ""
        return {
            "person": g.get("person"),
            "household": g.get("household"),
            "csrf_token": g.get("setup_token") or g.get("csrf_token") or "",
            "message": g.get("message") or "",
            "nav": nav,
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
        timezone_name = (g.get("household") or {}).get("timezone", "Europe/Berlin")
        return format_timestamp(value, timezone_name) if value else ""

    @app.errorhandler(AppError)
    def on_app(exc):
        if request.path.startswith("/api"):
            return jsonify(exc.payload()), exc.status
        if exc.status == 401:
            return redirect(url_for("pages.login_get"))
        return render_template("error.html", title="Information", text=exc.message), exc.status

    @app.errorhandler(404)
    def on_404(_exc):
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": "not_found", "message": "Introuvable.", "fields": {}}}), 404
        return render_template("error.html", title="Introuvable", text="Introuvable."), 404

    @app.errorhandler(405)
    def on_405(_exc):
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": "validation", "message": "Méthode refusée.", "fields": {}}}), 405
        return render_template("error.html", title="Information", text="Méthode refusée."), 405

    @app.errorhandler(RequestEntityTooLarge)
    def on_large(_exc):
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": "too_large", "message": "Le fichier dépasse 20 Mio.", "fields": {}}}), 413
        return render_template("error.html", title="Information", text="Le fichier dépasse 20 Mio."), 413

    @app.errorhandler(Exception)
    def on_error(exc):
        if isinstance(exc, AppError):
            return on_app(exc)
        if app.testing:
            traceback.print_exc()
        audit(home, app.config["CLOCK"], "error", type(exc).__name__)
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": "storage", "message": "Opération impossible.", "fields": {}}}), 500
        return render_template("error.html", title="Information", text="Opération impossible."), 500

    return app


def current_ctx():
    from flask import current_app
    person = g.get("person") or {}
    return Ctx(
        g.db,
        current_app.config["CLOCK"],
        current_app.config["HOME"],
        current_app.config["LOCK"],
        current_app.config["DUMMY_HASH"],
        person.get("id"),
    )
