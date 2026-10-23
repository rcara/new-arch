"""Six écrans et les états d'entrée."""

from datetime import date

from flask import Blueprint, current_app, g, redirect, render_template, request, url_for

from .. import current_ctx
from ..errors import AppError
from ..money import format_minor
from ..http import THEMES, cookie_message, cookie_onboarding, cookie_session, cookie_setup, cookie_theme, safe_next
from ..security import new_token
from ..services import agenda, auth, decisions, events, finance, home, inventory, links, media, milestones, modules, people, photos, search, sejours, tasks, vault
from ..validate import text_value

pages = Blueprint("pages", __name__)


def _limiter():
    from flask import current_app
    return current_app.config["LIMITER"]


def _go(code, endpoint, **kwargs):
    response = redirect(url_for(endpoint, **kwargs))
    return cookie_message(response, code)


def _next_target():
    raw = request.values.get("next") or ""
    return safe_next(raw) if raw else ""


def _done(code, endpoint, **kwargs):
    """Retour à la page d'origine (`next`, même site) sinon vers `endpoint`."""
    response = redirect(_next_target() or url_for(endpoint, **kwargs))
    return cookie_message(response, code)


def _today_iso():
    from ..clock import civil_today
    return civil_today(current_app.config["CLOCK"], (g.household or {}).get("timezone", "Europe/Zurich")).isoformat()


def _account_for_currency(person, form):
    """Compte choisi, sinon le premier compte actif de la devise saisie."""
    if form.get("ledger_account_id"):
        return form["ledger_account_id"]
    for account in finance.list_ledger_accounts(current_ctx(), person)["items"]:
        if account["currency"] == form.get("currency") and not account.get("archived"):
            return str(account["id"])
    return ""


CONTEXT_TYPES = {"calendar_event": "pages.event_get", "inventory_item": "pages.inventory_item_get"}


def _context(person, values):
    """Objet d'origine d'une création contextuelle, après contrôle de visibilité."""
    kind = values.get("link_type") or ""
    raw_id = str(values.get("link_id") or "")
    if kind not in CONTEXT_TYPES or not raw_id.isdigit():
        return None
    links.require_object(current_ctx(), person, kind, int(raw_id))
    if kind == "calendar_event":
        title = events.get_event(current_ctx(), person, int(raw_id))["title"]
    else:
        title = inventory.get_item(current_ctx(), person, int(raw_id))["name"]
    return {"type": kind, "id": int(raw_id), "title": title, "href": url_for(CONTEXT_TYPES[kind], **{
        "event_id" if kind == "calendar_event" else "item_id": int(raw_id)})}


def _linked_tasks(person, target_type, target_id):
    found = []
    for link in links.list_links(current_ctx(), person, source_type="task", target_type=target_type, target_id=target_id)["items"]:
        try:
            found.append(tasks.get_task(current_ctx(), person, link["source_id"]))
        except AppError:
            continue
    return found


def _need():
    if g.person is None:
        raise AppError(401, "unauthorized", "Connexion requise.")
    return g.person


def _form_options(form):
    return [form.get(f"option_{index}", "") for index in range(19)]


def _form_rule(form):
    lines = [
        {"label": form.get(f"rule_label_{index}", ""), "value": form.get(f"rule_value_{index}", "")}
        for index in range(10)
    ]
    return {"name": form.get("rule_name", ""), "lines": lines}


def _decision_fields(form, milestone_id):
    return {
        "milestone_id": milestone_id,
        "choice": form.get("choice", ""),
        "options": _form_options(form),
        "expected": form.get("expected", ""),
        "reconsider_if": form.get("reconsider_if", ""),
        "rule": _form_rule(form),
    }


@pages.get("/initialisation")
def bootstrap_get():
    token = new_token()
    g.setup_token = token
    response = render_template("bootstrap.html", form={}, errors={})
    return cookie_setup(_response(response), token)


@pages.post("/initialisation")
def bootstrap_post():
    form = request.form.to_dict()
    if form.get("password") != form.get("password_confirm"):
        g.setup_token = request.cookies.get("foyer_setup", "")
        return render_template("bootstrap.html", form=form, errors={"password_confirm": "Les deux saisies diffèrent."}), 400
    try:
        token, csrf, profile = auth.bootstrap(
            current_ctx(), _limiter(), form.get("household_name"), form.get("timezone") or "Europe/Zurich",
            form.get("display_name"), form.get("username"), form.get("password"),
        )
    except AppError as exc:
        if exc.status == 400:
            g.setup_token = request.cookies.get("foyer_setup", "")
            return render_template("bootstrap.html", form=form, errors=exc.fields), 400
        raise
    if not current_app.testing:
        from ..services.birthdays import ensure_family_birthdays
        ensure_family_birthdays(current_ctx(), {"id": profile["person_id"]})
    g.csrf_token = csrf
    response = redirect(url_for("pages.today"))
    cookie_session(response, token)
    return cookie_message(response, "ready")


@pages.get("/connexion")
def login_get():
    token = new_token()
    g.setup_token = token
    response = render_template("login.html", form={}, errors={}, next_url=safe_next(request.args.get("next", "/")))
    return cookie_setup(_response(response), token)


@pages.post("/connexion")
def login_post():
    form = request.form.to_dict()
    try:
        token, csrf, _profile = auth.open_session(current_ctx(), _limiter(), form.get("username"), form.get("password"))
    except AppError as exc:
        token = new_token()
        g.setup_token = token
        body = render_template(
            "login.html", form=form, errors={"form": exc.message}, next_url=safe_next(form.get("next", "/")),
        )
        return cookie_setup(_response(body, exc.status), token)
    g.csrf_token = csrf
    response = redirect(safe_next(form.get("next", "/")))
    cookie_session(response, token)
    return response


@pages.post("/deconnexion")
def logout():
    _need()
    auth.close_session(current_ctx(), request.cookies.get("foyer_session"))
    response = redirect(url_for("pages.login_get"))
    response.delete_cookie("foyer_session", path="/")
    return response


@pages.get("/")
def today():
    person = _need()
    summary = home.dashboard(current_ctx(), person)
    hidden = request.cookies.get("foyer_onboarding") == "hidden"
    return render_template("today.html", summary=summary, onboarding_hidden=hidden)


@pages.post("/accueil/demarrage")
def onboarding_post():
    _need()
    hidden = request.form.get("action") == "masquer"
    target = "pages.settings_get" if request.form.get("from") == "parametres" else "pages.today"
    response = redirect(url_for(target))
    cookie_onboarding(response, hidden)
    return cookie_message(response, "onboarding_hidden" if hidden else "onboarding_shown")


@pages.get("/profil")
def profile_get():
    person = _need()
    profile = auth.self_profile(current_ctx(), person)
    return render_template(
        "profile.html",
        profile=profile,
        form={"display_name": profile["display_name"]},
        password_form={},
        errors={},
        password_errors={},
    )


@pages.post("/profil")
def profile_post():
    person = _need()
    form = request.form.to_dict()
    try:
        profile = auth.update_own_display_name(current_ctx(), person, form.get("display_name"))
    except AppError as exc:
        if exc.status == 400:
            profile = auth.self_profile(current_ctx(), person)
            return render_template(
                "profile.html",
                profile=profile,
                form=form,
                password_form={},
                errors=exc.fields or {"display_name": exc.message},
                password_errors={},
            ), 400
        raise
    g.person = {**person, "display_name": profile["display_name"]}
    return _go("profile_saved", "pages.profile_get")


@pages.post("/profil/mot-de-passe")
def profile_password_post():
    person = _need()
    form = request.form.to_dict()
    profile = auth.self_profile(current_ctx(), person)
    if form.get("new_password") != form.get("new_password_confirm"):
        return render_template(
            "profile.html",
            profile=profile,
            form={"display_name": profile["display_name"]},
            password_form=form,
            errors={},
            password_errors={"new_password_confirm": "Les deux saisies diffèrent."},
        ), 400
    try:
        auth.change_password(
            current_ctx(),
            person,
            form.get("current_password", ""),
            form.get("new_password", ""),
            session_token=request.cookies.get("foyer_session"),
        )
    except AppError as exc:
        if exc.status in {400, 409}:
            return render_template(
                "profile.html",
                profile=profile,
                form={"display_name": profile["display_name"]},
                password_form=form,
                errors={},
                password_errors=exc.fields or {"form": exc.message},
            ), exc.status
        raise
    return _go("password_changed", "pages.profile_get")


@pages.get("/organisation")
def tasks_get():
    person = _need()
    modules.require_module(current_ctx(), "organisation")
    status = request.args.get("status", "open")
    assignee = request.args.get("pour", "")
    listed = tasks.list_tasks(
        current_ctx(), person, status=status, q=request.args.get("q", ""),
        assignee=assignee if assignee in ("moi", "partage") else "",
        page=int(request.args["page"]) if request.args.get("page", "").isdigit() else 1,
    )
    return render_template("tasks.html", listed=listed, args=request.args, status=status)


@pages.get("/organisation/nouvelle")
def task_new():
    person = _need()
    modules.require_module(current_ctx(), "organisation")
    form = {"priority": "normal", "recurrence": "none"}
    for key in ("title", "due_date", "link_type", "link_id"):
        if request.args.get(key):
            form[key] = request.args[key]
    return render_template(
        "task_form.html", form=form, errors={}, people=_members(), editing=False,
        context=_context(person, form),
    )


@pages.post("/organisation")
def task_create():
    person = _need()
    form = request.form.to_dict()
    if form.get("for_me") == "1" and not form.get("assignee_id"):
        form["assignee_id"] = str(person["id"])
    context = _context(person, form)
    try:
        task_id = tasks.create_task(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "task_form.html", form=form, errors=exc.fields, people=_members(), editing=False,
                context=context,
            ), 400
        raise
    if context:
        links.create_link(current_ctx(), person, {
            "source_type": "task", "source_id": task_id,
            "target_type": context["type"], "target_id": context["id"], "relation_type": "concerns",
        })
    return _done("task_saved", "pages.tasks_get")


@pages.get("/organisation/<int:task_id>")
def task_get(task_id):
    person = _need()
    item = tasks.get_task(current_ctx(), person, task_id)
    related = links.list_links(current_ctx(), person, source_type="task", source_id=task_id)
    return render_template("task.html", item=item, links=related["items"], people=_members())


@pages.get("/organisation/<int:task_id>/modifier")
def task_edit(task_id):
    person = _need()
    item = tasks.get_task(current_ctx(), person, task_id)
    form = {
        "title": item["title"],
        "notes": item["notes"],
        "priority": item["priority"],
        "recurrence": item["recurrence"],
        "due_date": item["due_date"] or "",
        "assignee_id": "" if item["assignee_id"] is None else str(item["assignee_id"]),
        "status": item["status"],
    }
    return render_template("task_form.html", form=form, errors={}, people=_members(), editing=True, task_id=task_id)


@pages.post("/organisation/<int:task_id>")
def task_update(task_id):
    person = _need()
    form = request.form.to_dict()
    try:
        tasks.update_task(current_ctx(), person, task_id, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "task_form.html", form=form, errors=exc.fields, people=_members(), editing=True, task_id=task_id,
            ), 400
        raise
    code = "task_done" if form.get("status") == "done" else "task_saved"
    return _go(code, "pages.task_get", task_id=task_id)


@pages.post("/organisation/<int:task_id>/terminer")
def task_complete(task_id):
    person = _need()
    tasks.update_task(current_ctx(), person, task_id, {"status": "done"})
    response = redirect(safe_next(request.form.get("next") or url_for("pages.tasks_get")))
    return cookie_message(response, "task_done")


@pages.post("/organisation/<int:task_id>/rouvrir")
def task_reopen(task_id):
    person = _need()
    tasks.update_task(current_ctx(), person, task_id, {"status": "open"})
    response = redirect(safe_next(request.form.get("next") or url_for("pages.tasks_get")))
    return cookie_message(response, "task_reopened")


@pages.post("/organisation/<int:task_id>/lien")
def task_link(task_id):
    person = _need()
    form = request.form.to_dict()
    links.create_link(current_ctx(), person, {
        "source_type": "task",
        "source_id": task_id,
        "target_type": form.get("target_type") or "milestone",
        "target_id": form.get("target_id"),
        "relation_type": form.get("relation_type") or "relates_to",
    })
    return _go("link_saved", "pages.task_get", task_id=task_id)


@pages.get("/calendrier")
def events_get():
    person = _need()
    modules.require_module(current_ctx(), "calendrier")
    legacy_from = request.args.get("from")
    view = request.args.get("vue") or ("liste" if legacy_from or request.args.get("q") else "mois")
    member = request.args.get("membre", "")
    cal = agenda.build(
        current_ctx(), person,
        view=view,
        anchor=request.args.get("date") or legacy_from or "",
        member_id=int(member) if member.isdigit() else None,
        q=request.args.get("q", ""),
    )
    return render_template("events.html", cal=cal, people=_members(), args=request.args)


@pages.get("/calendrier/nouveau")
def event_new():
    _need()
    modules.require_module(current_ctx(), "calendrier")
    return render_template(
        "event_form.html",
        form={
            "all_day": "1", "recurrence": "none", "timezone": (g.household or {}).get("timezone", "Europe/Zurich"),
            "title": request.args.get("title", ""), "start_date": request.args.get("start_date", ""),
        },
        errors={}, people=_members(), editing=False,
    )


@pages.post("/calendrier")
def event_create():
    person = _need()
    form = request.form.to_dict()
    if "all_day_present" in request.form:
        form["all_day"] = "1" if request.form.get("all_day") == "1" else "0"
    else:
        form["all_day"] = "1"
    form.setdefault("timezone", (g.household or {}).get("timezone", "Europe/Zurich"))
    try:
        events.create_event(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "event_form.html", form=form, errors=exc.fields, people=_members(), editing=False,
            ), 400
        raise
    return _done("event_saved", "pages.events_get")


@pages.get("/calendrier/<int:event_id>")
def event_get(event_id):
    person = _need()
    item = events.get_event(current_ctx(), person, event_id)
    raw = request.args.get("occurrence", "")
    occurrence = raw if item["recurrence"] != "none" and events.is_occurrence(item, raw) else None
    return render_template(
        "event.html", item=item, occurrence=occurrence,
        linked_tasks=_linked_tasks(person, "calendar_event", event_id),
    )


@pages.get("/calendrier/<int:event_id>/modifier")
def event_edit(event_id):
    person = _need()
    item = events.get_event(current_ctx(), person, event_id)
    form = {
        "title": item["title"],
        "notes": item["notes"],
        "start_date": item["start_date"],
        "end_date": item["end_date"] or "",
        "all_day": "1" if item["all_day"] else "0",
        "timezone": item["timezone"],
        "recurrence": item["recurrence"],
        "responsible_id": "" if item["responsible_id"] is None else str(item["responsible_id"]),
    }
    return render_template("event_form.html", form=form, errors={}, people=_members(), editing=True, event_id=event_id)


@pages.post("/calendrier/<int:event_id>")
def event_update(event_id):
    person = _need()
    form = request.form.to_dict()
    form["all_day"] = "1" if request.form.get("all_day") == "1" else "0"
    try:
        events.update_event(current_ctx(), person, event_id, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "event_form.html", form=form, errors=exc.fields, people=_members(), editing=True, event_id=event_id,
            ), 400
        raise
    return _go("event_saved", "pages.event_get", event_id=event_id)


def _sejour_payload(form):
    form = dict(form)
    form["participant_ids"] = request.form.getlist("participant_ids")
    return form


def _sejour_form_from_item(item):
    form = {
        "title": item["title"],
        "destination": item["destination"],
        "start_date": item["start_date"],
        "end_date": item["end_date"],
        "currency": item["currency"],
        "participant_ids": [str(person["id"]) for person in item["participants"]],
    }
    for line in item["lines"]:
        form[f"envelope_{line['key']}"] = _minor_form(line["amount_minor"]) if line["amount_minor"] else ""
    return form


def _all_expenses(person, currency):
    found, page = [], 1
    while page <= 20:
        listed = finance.list_transactions(
            current_ctx(), person, kind="expense", currency=currency, page=page,
        )
        found.extend(listed["items"])
        if page * listed["page_size"] >= listed["total"] or not listed["items"]:
            break
        page += 1
    return found


def _sejour_detail(person, item, *, spend_form=None, errors=None, status=200):
    finances_on = "finances" in modules.enabled_keys(current_ctx())
    attachable, categories = [], []
    if finances_on:
        finance.seed_defaults(current_ctx(), person)
        linked = {expense["id"] for expense in item["expenses"]}
        attachable = [txn for txn in _all_expenses(person, item["currency"]) if txn["id"] not in linked]
        categories = finance.list_categories(current_ctx(), person, kind="expense")["items"]
    if spend_form is None:
        spend_form = {
            "txn_date": _today_iso(),
            "visibility": "household",
            "currency": item["currency"],
            "payer_id": str(person["id"]),
        }
    body = render_template(
        "sejour.html",
        item=item,
        people=_members(),
        finances_on=finances_on,
        attachable=attachable,
        categories=categories,
        spend_form=spend_form,
        errors=errors or {},
    )
    return body if status == 200 else (body, status)


def _sejour_error(exc):
    fields = dict(exc.fields)
    fields.setdefault("form", exc.message)
    return fields


@pages.get("/sejours")
def sejours_get():
    person = _need()
    modules.require_module(current_ctx(), "calendrier")
    listed = sejours.list_sejours(current_ctx(), person)
    return render_template("sejours.html", items=listed["items"])


@pages.get("/sejours/nouveau")
def sejour_new():
    _need()
    modules.require_module(current_ctx(), "calendrier")
    return render_template(
        "sejour_form.html",
        form={"currency": "CHF", "participant_ids": []},
        errors={}, people=_members(), editing=False,
    )


@pages.post("/sejours")
def sejour_create():
    person = _need()
    form = _sejour_payload(request.form.to_dict())
    try:
        sejour_id = sejours.create_sejour(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "sejour_form.html", form=form, errors=exc.fields, people=_members(), editing=False,
            ), 400
        raise
    return _go("sejour_saved", "pages.sejour_get", sejour_id=sejour_id)


@pages.get("/sejours/<int:sejour_id>")
def sejour_get(sejour_id):
    person = _need()
    item = sejours.get_sejour(current_ctx(), person, sejour_id)
    return _sejour_detail(person, item)


@pages.get("/sejours/<int:sejour_id>/modifier")
def sejour_edit(sejour_id):
    person = _need()
    item = sejours.get_sejour(current_ctx(), person, sejour_id)
    return render_template(
        "sejour_form.html",
        form=_sejour_form_from_item(item),
        errors={}, people=_members(), editing=True, sejour_id=sejour_id,
    )


@pages.post("/sejours/<int:sejour_id>")
def sejour_update(sejour_id):
    person = _need()
    form = _sejour_payload(request.form.to_dict())
    try:
        sejours.update_sejour(current_ctx(), person, sejour_id, form)
    except AppError as exc:
        if exc.status == 400:
            current = sejours.get_sejour(current_ctx(), person, sejour_id)
            form["currency"] = current["currency"]
            return render_template(
                "sejour_form.html", form=form, errors=exc.fields, people=_members(),
                editing=True, sejour_id=sejour_id,
            ), 400
        raise
    return _go("sejour_saved", "pages.sejour_get", sejour_id=sejour_id)


@pages.post("/sejours/<int:sejour_id>/rattacher")
def sejour_attach(sejour_id):
    person = _need()
    modules.require_module(current_ctx(), "finances")
    try:
        sejours.attach_expense(
            current_ctx(), person, sejour_id,
            request.form.get("transaction_id"), request.form.get("line_key"),
        )
    except AppError as exc:
        if exc.status in {400, 409}:
            item = sejours.get_sejour(current_ctx(), person, sejour_id)
            return _sejour_detail(person, item, errors=_sejour_error(exc), status=exc.status)
        raise
    return _go("sejour_expense", "pages.sejour_get", sejour_id=sejour_id)


@pages.post("/sejours/<int:sejour_id>/depense")
def sejour_spend(sejour_id):
    person = _need()
    modules.require_module(current_ctx(), "finances")
    form = request.form.to_dict()
    form["split_person_ids"] = request.form.getlist("split_person_ids")
    item = sejours.get_sejour(current_ctx(), person, sejour_id)
    form["currency"] = item["currency"]
    form["ledger_account_id"] = _account_for_currency(person, form)
    try:
        sejours.record_expense(current_ctx(), person, sejour_id, form)
    except AppError as exc:
        if exc.status in {400, 409}:
            item = sejours.get_sejour(current_ctx(), person, sejour_id)
            return _sejour_detail(person, item, spend_form=form, errors=_sejour_error(exc), status=exc.status)
        raise
    return _go("sejour_expense", "pages.sejour_get", sejour_id=sejour_id)


@pages.post("/sejours/<int:sejour_id>/retirer")
def sejour_detach(sejour_id):
    person = _need()
    modules.require_module(current_ctx(), "finances")
    sejours.detach_expense(current_ctx(), person, sejour_id, request.form.get("attachment_id"))
    return _go("sejour_detached", "pages.sejour_get", sejour_id=sejour_id)


@pages.get("/recherche")
def search_get():
    person = _need()
    modules.require_module(current_ctx(), "recherche")
    q = request.args.get("q", "")
    results = {"q": q, "items": [], "total": 0}
    if q.strip():
        try:
            results = search.search(current_ctx(), person, q)
        except AppError as exc:
            if exc.status == 400:
                return render_template("search.html", results=results, errors={"q": exc.message}), 400
            raise
    return render_template("search.html", results=results, errors={})


@pages.get("/foyer")
def foyer_get():
    person = _need()
    modules.require_module(current_ctx(), "foyer")
    return render_template("people.html", items=people.list_people(current_ctx(), person))


@pages.get("/parametres")
def settings_get():
    person = _need()
    modules.require_module(current_ctx(), "parametres")
    from ..http import resolve_theme
    return render_template(
        "settings.html",
        modules=modules.list_modules(current_ctx()),
        household=g.household,
        theme=resolve_theme(request.cookies.get("foyer_theme")),
        onboarding_hidden=request.cookies.get("foyer_onboarding") == "hidden",
    )


@pages.get("/parametres/avance")
def settings_advanced_get():
    person = _need()
    modules.require_module(current_ctx(), "parametres")
    if not person["is_principal"]:
        raise AppError(403, "forbidden", "Réservé au compte principal.")
    from ..crypto import status as crypto_status
    return render_template("settings_advanced.html", crypto=crypto_status(current_app.config["HOME"]))


@pages.get("/agenda")
def alias_agenda():
    return redirect(url_for("pages.events_get"))


@pages.get("/a-faire")
def alias_afaire():
    return redirect(url_for("pages.tasks_get"))


@pages.get("/maison")
def alias_maison():
    return redirect(url_for("pages.inventory_get"))


@pages.get("/bibliotheque")
def alias_bibliotheque():
    _need()
    enabled = modules.enabled_keys(current_ctx())
    for key, endpoint in (("coffre", "pages.vault_get"), ("mediatheque", "pages.media_get"), ("decisions", "pages.decisions_get")):
        if key in enabled:
            return redirect(url_for(endpoint))
    raise AppError(404, "not_found", "Module indisponible.")


@pages.post("/parametres/modules")
def settings_modules_post():
    person = _need()
    modules.set_enabled(current_ctx(), person, request.form.getlist("module"))
    return _go("modules_saved", "pages.settings_get")


@pages.post("/parametres/theme")
def settings_theme_post():
    _need()
    modules.require_module(current_ctx(), "parametres")
    theme = (request.form.get("theme") or "").strip()
    if theme not in THEMES:
        raise AppError(400, "validation", "Thème inconnu.")
    response = redirect(_next_target() or url_for("pages.settings_get"))
    cookie_theme(response, theme)
    return cookie_message(response, "theme_saved")


FINANCE_VIEWS = ("apercu", "transactions", "budgets", "comptes", "repartition")


@pages.get("/finances")
def finance_get():
    person = _need()
    ctx = current_ctx()
    currency = request.args.get("currency", "CHF")
    view = request.args.get("vue", "apercu")
    view = view if view in FINANCE_VIEWS else "apercu"
    finance.seed_defaults(ctx, person)
    today = date.fromisoformat(_today_iso())
    data = {"view": view, "currency": currency, "currencies": ("CHF", "EUR"), "today": today}
    if view == "apercu":
        months = []
        for back in range(5, -1, -1):
            index = today.year * 12 + today.month - 1 - back
            year, month = divmod(index, 12)
            spent = next((s for s in finance.month_spending(ctx, person, year=year, month=month + 1)
                          if s["currency"] == currency), None)
            months.append({"year": year, "month": month + 1, "minor": spent["spent_minor"] if spent else 0,
                           "label": spent["spent_label"] if spent else format_minor(0, currency)})
        peak = max([m["minor"] for m in months] + [1])
        for m in months:
            m["percent"] = round(100 * m["minor"] / peak)
        data.update(
            months=months,
            current=months[-1],
            budgets=finance.list_budgets(ctx, person, currency=currency, year=today.year, month=today.month)["items"],
            balances=finance.person_balances(ctx, person, currency=currency),
            transactions=finance.list_transactions(ctx, person, currency=currency)["items"][:8],
        )
    elif view == "transactions":
        kind = request.args.get("type", "")
        page = int(request.args["page"]) if request.args.get("page", "").isdigit() else 1
        listed = finance.list_transactions(ctx, person, currency=currency, kind=kind if kind in finance.TXN_KINDS else "", page=page)
        data.update(listed=listed, kind=kind)
    elif view == "budgets":
        data.update(budgets=finance.list_budgets(ctx, person, currency=currency)["items"])
    elif view == "comptes":
        data.update(accounts=finance.list_ledger_accounts(ctx, person)["items"])
    else:
        data.update(balances=finance.person_balances(ctx, person, currency=currency))
    return render_template("finance.html", **data)


@pages.get("/finances/depense")
def finance_expense_new():
    person = _need()
    finance.seed_defaults(current_ctx(), person)
    return render_template(
        "finance_expense_form.html",
        form={
            "currency": "CHF",
            "visibility": "household",
            "split_method": "equal",
            "txn_date": _today_iso(),
        },
        errors={},
        accounts=finance.list_ledger_accounts(current_ctx(), person)["items"],
        categories=finance.list_categories(current_ctx(), person, kind="expense")["items"],
        people=_members(),
    )


@pages.post("/finances/depense")
def finance_expense_create():
    person = _need()
    form = request.form.to_dict()
    form["kind"] = "expense"
    form["split_person_ids"] = request.form.getlist("split_person_ids")
    form["ledger_account_id"] = _account_for_currency(person, form)
    try:
        finance.create_transaction(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            finance.seed_defaults(current_ctx(), person)
            return render_template(
                "finance_expense_form.html",
                form=form,
                errors=exc.fields or {"form": exc.message},
                accounts=finance.list_ledger_accounts(current_ctx(), person)["items"],
                categories=finance.list_categories(current_ctx(), person, kind="expense")["items"],
                people=_members(),
            ), 400
        raise
    return _done("finance_saved", "pages.finance_get")


@pages.get("/finances/remboursement")
def finance_reimburse_new():
    person = _need()
    finance.seed_defaults(current_ctx(), person)
    return render_template(
        "finance_reimburse_form.html",
        form={"currency": "CHF", "txn_date": "", "visibility": "household"},
        errors={},
        accounts=finance.list_ledger_accounts(current_ctx(), person)["items"],
        people=_members(),
        expenses=[
            item for item in finance.list_transactions(current_ctx(), person, kind="expense")["items"]
        ],
    )


@pages.post("/finances/remboursement")
def finance_reimburse_create():
    person = _need()
    form = request.form.to_dict()
    form["kind"] = "reimbursement"
    try:
        finance.create_transaction(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            finance.seed_defaults(current_ctx(), person)
            return render_template(
                "finance_reimburse_form.html",
                form=form,
                errors=exc.fields or {"form": exc.message},
                accounts=finance.list_ledger_accounts(current_ctx(), person)["items"],
                people=_members(),
                expenses=finance.list_transactions(current_ctx(), person, kind="expense")["items"],
            ), 400
        raise
    return _go("finance_saved", "pages.finance_get")


@pages.get("/finances/budget")
def finance_budget_new():
    person = _need()
    finance.seed_defaults(current_ctx(), person)
    return render_template(
        "finance_budget_form.html",
        form={"currency": "CHF", "period": "month"},
        errors={},
        categories=finance.list_categories(current_ctx(), person, kind="expense")["items"],
    )


@pages.post("/finances/budget")
def finance_budget_create():
    person = _need()
    form = request.form.to_dict()
    try:
        finance.create_budget(current_ctx(), person, form)
    except AppError as exc:
        if exc.status in {400, 409}:
            return render_template(
                "finance_budget_form.html",
                form=form,
                errors=exc.fields or {"form": exc.message},
                categories=finance.list_categories(current_ctx(), person, kind="expense")["items"],
            ), exc.status
        raise
    return _go("finance_saved", "pages.finance_get")


@pages.get("/finances/export.csv")
def finance_export_page():
    from flask import Response
    person = _need()
    body = finance.export_csv(current_ctx(), person, currency=request.args.get("currency", ""))
    return Response(body, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="finances.csv"',
    })


@pages.get("/finances/import")
def finance_import_get():
    _need()
    return render_template("finance_import.html", errors={}, result=None)


@pages.post("/finances/import")
def finance_import_post():
    person = _need()
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return render_template("finance_import.html", errors={"file": "Fichier requis."}, result=None), 400
    result = finance.import_csv(current_ctx(), person, upload.read())
    return render_template("finance_import.html", errors={}, result=result)


@pages.get("/inventaire")
def inventory_get():
    person = _need()
    place_id = request.args.get("place_id", "")
    listed = inventory.list_items(
        current_ctx(), person,
        q=request.args.get("q", ""),
        place_id=place_id if place_id.isdigit() else None,
        category=request.args.get("categorie", ""),
        page=int(request.args["page"]) if request.args.get("page", "").isdigit() else 1,
    )
    first = inventory.list_items(current_ctx(), person)
    found = {item["category"] for item in first["items"] if item["category"]}
    for page in range(2, (first["total"] + first["page_size"] - 1) // first["page_size"] + 1):
        found |= {item["category"] for item in inventory.list_items(current_ctx(), person, page=page)["items"] if item["category"]}
    return render_template(
        "inventory.html",
        listed=listed,
        view="liste" if request.args.get("vue") == "liste" else "galerie",
        has_items=first["total"] > 0,
        categories=sorted(found, key=str.lower),
        places=inventory.list_places(current_ctx(), person)["items"],
        warranties=inventory.upcoming_warranties(current_ctx(), person),
        args=request.args,
    )


@pages.get("/inventaire/export.csv")
def inventory_export_page():
    from flask import Response
    person = _need()
    body = inventory.export_csv(current_ctx(), person)
    return Response(body, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="inventaire.csv"',
    })


@pages.get("/inventaire/lieux/nouveau")
def inventory_place_new():
    _need()
    return render_template("inventory_place_form.html", form={}, errors={})


@pages.post("/inventaire/lieux")
def inventory_place_create():
    person = _need()
    form = request.form.to_dict()
    try:
        inventory.create_place(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template("inventory_place_form.html", form=form, errors=exc.fields), 400
        raise
    return _go("inventory_saved", "pages.inventory_get")


@pages.get("/inventaire/nouveau")
def inventory_item_new():
    person = _need()
    return render_template(
        "inventory_item_form.html",
        form={"condition": "good", "visibility": "household", "purchase_currency": "CHF", "estimated_currency": "CHF"},
        errors={},
        places=inventory.list_places(current_ctx(), person)["items"],
        people=_members(),
        editing=False,
    )


@pages.post("/inventaire")
def inventory_item_create():
    person = _need()
    form = request.form.to_dict()
    form["owner_ids"] = request.form.getlist("owner_ids")
    try:
        item_id = inventory.create_item(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "inventory_item_form.html",
                form=form,
                errors=exc.fields or {"form": exc.message},
                places=inventory.list_places(current_ctx(), person)["items"],
                people=_members(),
                editing=False,
            ), 400
        raise
    return _done("inventory_saved", "pages.inventory_item_get", item_id=item_id)


def _inventory_item_page(person, item_id, photo_error=""):
    item = inventory.get_item(current_ctx(), person, item_id)
    related = links.list_links(current_ctx(), person, source_type="inventory_item", source_id=item_id)
    return render_template(
        "inventory_item.html", item=item, links=related["items"],
        linked_tasks=_linked_tasks(person, "inventory_item", item_id),
        photo_error=photo_error,
    )


@pages.get("/inventaire/<int:item_id>")
def inventory_item_get(item_id):
    return _inventory_item_page(_need(), item_id)


def _photo_response(object_type, object_id):
    from flask import Response
    data, mime = photos.read_photo(current_ctx(), _need(), object_type, object_id)
    response = Response(data, mimetype=mime)
    response.headers["Content-Disposition"] = "inline"
    return response


@pages.get("/inventaire/<int:item_id>/photo")
def inventory_photo_get(item_id):
    return _photo_response("inventory_item", item_id)


@pages.post("/inventaire/<int:item_id>/photo")
def inventory_photo_post(item_id):
    person = _need()
    try:
        photos.store_photo(current_ctx(), person, "inventory_item", item_id, request.files.get("photo"))
    except AppError as exc:
        if exc.status in {400, 413, 415}:
            return _inventory_item_page(person, item_id, exc.message), exc.status
        raise
    return _go("photo_saved", "pages.inventory_item_get", item_id=item_id)


@pages.post("/inventaire/<int:item_id>/photo/retirer")
def inventory_photo_remove(item_id):
    photos.remove_photo(current_ctx(), _need(), "inventory_item", item_id)
    return _go("photo_removed", "pages.inventory_item_get", item_id=item_id)


@pages.get("/inventaire/<int:item_id>/modifier")
def inventory_item_edit(item_id):
    person = _need()
    item = inventory.get_item(current_ctx(), person, item_id)
    form = {
        "name": item["name"],
        "category": item["category"],
        "place_id": "" if item["place_id"] is None else str(item["place_id"]),
        "condition": item["condition"],
        "serial_number": item["serial_number"],
        "purchase_date": item["purchase_date"] or "",
        "purchase_price": _minor_form(item["purchase_price_minor"]),
        "purchase_currency": item["purchase_currency"] or "CHF",
        "estimated_value": _minor_form(item["estimated_value_minor"]),
        "estimated_currency": item["estimated_currency"] or "CHF",
        "notes": item["notes"],
        "visibility": item["visibility"],
        "owner_ids": [str(o["id"]) for o in item["owners"]],
    }
    return render_template(
        "inventory_item_form.html",
        form=form,
        errors={},
        places=inventory.list_places(current_ctx(), person)["items"],
        people=_members(),
        editing=True,
        item_id=item_id,
    )


@pages.post("/inventaire/<int:item_id>")
def inventory_item_update(item_id):
    person = _need()
    form = request.form.to_dict()
    form["owner_ids"] = request.form.getlist("owner_ids")
    try:
        inventory.update_item(current_ctx(), person, item_id, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "inventory_item_form.html",
                form=form,
                errors=exc.fields or {"form": exc.message},
                places=inventory.list_places(current_ctx(), person)["items"],
                people=_members(),
                editing=True,
                item_id=item_id,
            ), 400
        raise
    return _go("inventory_saved", "pages.inventory_item_get", item_id=item_id)


@pages.post("/inventaire/<int:item_id>/garantie")
def inventory_warranty_create(item_id):
    person = _need()
    form = request.form.to_dict()
    inventory.add_warranty(current_ctx(), person, item_id, form)
    return _go("inventory_saved", "pages.inventory_item_get", item_id=item_id)


@pages.post("/inventaire/<int:item_id>/maintenance")
def inventory_maintenance_create(item_id):
    person = _need()
    form = request.form.to_dict()
    inventory.add_maintenance(current_ctx(), person, item_id, form)
    return _go("inventory_saved", "pages.inventory_item_get", item_id=item_id)


@pages.post("/inventaire/<int:item_id>/lien-facture")
def inventory_link_invoice(item_id):
    person = _need()
    inventory.link_invoice(current_ctx(), person, item_id, request.form.get("invoice_file_id"))
    return _go("inventory_saved", "pages.inventory_item_get", item_id=item_id)


@pages.post("/inventaire/<int:item_id>/lien-achat")
def inventory_link_purchase(item_id):
    person = _need()
    inventory.link_purchase(current_ctx(), person, item_id, request.form.get("purchase_transaction_id"))
    return _go("inventory_saved", "pages.inventory_item_get", item_id=item_id)


@pages.get("/mediatheque")
def media_get():
    person = _need()
    dash = media.dashboard(current_ctx(), person)
    tab = request.args.get("onglet", "catalogue")
    status = {"en-cours": "in_progress", "envies": "wishlist"}.get(tab, request.args.get("status", ""))
    works = media.list_works(
        current_ctx(), person,
        kind=request.args.get("kind", ""),
        q=request.args.get("q", ""),
        status=status,
    )
    return render_template(
        "media.html",
        tab=tab if tab in ("catalogue", "en-cours", "envies", "fichiers", "listes") else "catalogue",
        dash=dash,
        works=works,
        assets=media.list_assets(current_ctx(), person)["items"],
        lists=media.list_lists(current_ctx(), person)["items"],
        args=request.args,
        kinds=media.WORK_KIND_LABEL,
        statuses=media.PROGRESS_LABEL,
    )


@pages.get("/mediatheque/oeuvre/nouvelle")
def media_work_new():
    _need()
    return render_template(
        "media_work_form.html",
        form={"kind": "book", "status": "wishlist", "visibility": "household"},
        errors={},
        kinds=media.WORK_KIND_LABEL,
    )


@pages.post("/mediatheque/oeuvres")
def media_work_create():
    person = _need()
    form = request.form.to_dict()
    try:
        work_id = media.create_work(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "media_work_form.html", form=form, errors=exc.fields or {"form": exc.message}, kinds=media.WORK_KIND_LABEL,
            ), 400
        raise
    return _done("media_saved", "pages.media_work_get", work_id=work_id)


def _media_work_page(person, work_id, photo_error=""):
    item = media.get_work(current_ctx(), person, work_id)
    related = links.list_links(current_ctx(), person, source_type="media_work", source_id=work_id)
    return render_template(
        "media_work.html",
        item=item,
        links=related["items"],
        statuses=media.PROGRESS_LABEL,
        photo_error=photo_error,
    )


@pages.get("/mediatheque/oeuvres/<int:work_id>")
def media_work_get(work_id):
    return _media_work_page(_need(), work_id)


@pages.get("/mediatheque/oeuvres/<int:work_id>/affiche")
def media_work_photo_get(work_id):
    return _photo_response("media_work", work_id)


@pages.post("/mediatheque/oeuvres/<int:work_id>/affiche")
def media_work_photo_post(work_id):
    person = _need()
    try:
        photos.store_photo(current_ctx(), person, "media_work", work_id, request.files.get("photo"))
    except AppError as exc:
        if exc.status in {400, 413, 415}:
            return _media_work_page(person, work_id, exc.message), exc.status
        raise
    return _go("photo_saved", "pages.media_work_get", work_id=work_id)


@pages.post("/mediatheque/oeuvres/<int:work_id>/affiche/retirer")
def media_work_photo_remove(work_id):
    photos.remove_photo(current_ctx(), _need(), "media_work", work_id)
    return _go("photo_removed", "pages.media_work_get", work_id=work_id)


@pages.post("/mediatheque/oeuvres/<int:work_id>/progression")
def media_progress_post(work_id):
    person = _need()
    media.set_progress(current_ctx(), person, work_id, request.form.to_dict())
    return _go("media_saved", "pages.media_work_get", work_id=work_id)


@pages.post("/mediatheque/oeuvres/<int:work_id>/lien-decision")
def media_link_decision(work_id):
    person = _need()
    links.create_link(current_ctx(), person, {
        "source_type": "media_work",
        "source_id": work_id,
        "target_type": "decision",
        "target_id": request.form.get("decision_id"),
        "relation_type": "about_work",
    })
    return _go("media_saved", "pages.media_work_get", work_id=work_id)


@pages.get("/mediatheque/listes/nouvelle")
def media_list_new():
    _need()
    return render_template("media_list_form.html", form={"list_kind": "wishlist", "visibility": "private"}, errors={})


@pages.post("/mediatheque/listes")
def media_list_create():
    person = _need()
    form = request.form.to_dict()
    try:
        media.create_list(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template("media_list_form.html", form=form, errors=exc.fields), 400
        raise
    return _go("media_saved", "pages.media_get")


@pages.post("/mediatheque/listes/<int:list_id>/ajouter")
def media_list_add(list_id):
    person = _need()
    media.add_to_list(current_ctx(), person, list_id, int(request.form.get("work_id")))
    return _go("media_saved", "pages.media_get")


@pages.get("/mediatheque/bibliotheque/depot")
def media_asset_new():
    person = _need()
    return render_template(
        "media_asset_form.html",
        form={"visibility": "private"},
        errors={},
        works=media.list_works(current_ctx(), person)["items"],
    )


@pages.post("/mediatheque/bibliotheque")
def media_asset_create():
    person = _need()
    form = request.form.to_dict()
    try:
        asset_id = media.store_asset(current_ctx(), person, form, request.files.get("file"))
    except AppError as exc:
        if exc.status in {400, 413, 415}:
            return render_template(
                "media_asset_form.html",
                form=form,
                errors=exc.fields or {"form": exc.message},
                works=media.list_works(current_ctx(), person)["items"],
            ), exc.status
        raise
    return _go("media_saved", "pages.media_asset_get", asset_id=asset_id)


@pages.get("/mediatheque/bibliotheque/<int:asset_id>")
def media_asset_get(asset_id):
    person = _need()
    item = media.get_asset(current_ctx(), person, asset_id)
    return render_template("media_asset.html", item=item)


@pages.get("/mediatheque/bibliotheque/<int:asset_id>/ouvrir")
def media_asset_open(asset_id):
    from flask import Response
    from ..http import content_disposition
    person = _need()
    data, name, mime = media.read_asset(current_ctx(), person, asset_id)
    response = Response(data, mimetype=mime)
    response.headers["Content-Disposition"] = content_disposition(name)
    return response


@pages.get("/reperes")
def milestones_get():
    person = _need()
    page = request.args.get("page", "1")
    listed = milestones.list_milestones(
        current_ctx(), person,
        q=request.args.get("q", ""),
        category=request.args.get("category", ""),
        statut=request.args.get("statut", ""),
        archives=request.args.get("archives") == "1",
        page=int(page) if str(page).isdigit() else 1,
    )
    return render_template("milestones.html", listed=listed, args=request.args)


@pages.get("/reperes/nouveau")
def milestone_new():
    _need()
    return render_template("milestone_form.html", form={"notice_days": "0"}, errors={}, people=_people(), editing=False)


@pages.post("/reperes")
def milestone_create():
    person = _need()
    form = request.form.to_dict()
    form["_from_form"] = True
    try:
        new_id = milestones.create_milestone(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template("milestone_form.html", form=form, errors=exc.fields, people=_people(), editing=False), 400
        raise
    return _done("saved", "pages.milestone_get", milestone_id=new_id)


@pages.get("/reperes/<int:milestone_id>")
def milestone_get(milestone_id):
    person = _need()
    item = milestones.get_milestone(current_ctx(), person, milestone_id)
    return render_template("milestone.html", item=item)


@pages.get("/reperes/<int:milestone_id>/modifier")
def milestone_edit(milestone_id):
    person = _need()
    item = milestones.get_milestone(current_ctx(), person, milestone_id)
    form = _milestone_form(item)
    return render_template("milestone_form.html", form=form, errors={}, people=_people(), editing=True, item=item)


@pages.post("/reperes/<int:milestone_id>")
def milestone_update(milestone_id):
    person = _need()
    form = request.form.to_dict()
    form["_from_form"] = True
    try:
        milestones.update_milestone(current_ctx(), person, milestone_id, form, form.get("updated_at"))
    except AppError as exc:
        if exc.status == 400:
            return render_template("milestone_form.html", form=form, errors=exc.fields, people=_people(), editing=True), 400
        raise
    return _go("saved", "pages.milestone_get", milestone_id=milestone_id)


@pages.get("/reperes/<int:milestone_id>/archiver")
def milestone_archive_get(milestone_id):
    person = _need()
    item = milestones.get_milestone(current_ctx(), person, milestone_id)
    return _confirm(
        "Archiver ce repère",
        "Il quitte les compteurs du jour. Ses pages et sa pièce restent.",
        "Archiver",
        url_for("pages.milestone_archive_post", milestone_id=milestone_id),
        url_for("pages.milestone_get", milestone_id=milestone_id),
        {"updated_at": item["updated_at"]},
    )


@pages.post("/reperes/<int:milestone_id>/archiver")
def milestone_archive_post(milestone_id):
    person = _need()
    if request.form.get("confirm") != "oui":
        raise AppError(400, "validation", "Confirmation requise.")
    milestones.update_milestone(
        current_ctx(), person, milestone_id, {}, request.form.get("updated_at"), archive=True,
    )
    return _go("archived", "pages.milestone_get", milestone_id=milestone_id)


@pages.get("/reperes/<int:milestone_id>/restaurer")
def milestone_restore_get(milestone_id):
    person = _need()
    item = milestones.get_milestone(current_ctx(), person, milestone_id)
    return _confirm(
        "Restaurer ce repère",
        "Il revient dans les compteurs du jour.",
        "Restaurer",
        url_for("pages.milestone_restore_post", milestone_id=milestone_id),
        url_for("pages.milestone_get", milestone_id=milestone_id),
        {"updated_at": item["updated_at"]},
    )


@pages.post("/reperes/<int:milestone_id>/restaurer")
def milestone_restore_post(milestone_id):
    person = _need()
    if request.form.get("confirm") != "oui":
        raise AppError(400, "validation", "Confirmation requise.")
    milestones.update_milestone(
        current_ctx(), person, milestone_id, {}, request.form.get("updated_at"), archive=False,
    )
    return _go("restored", "pages.milestone_get", milestone_id=milestone_id)


@pages.get("/decisions")
def decisions_get():
    person = _need()
    items = sorted(decisions.list_decisions(current_ctx(), person), key=lambda d: (d["created_at"], d["id"]), reverse=True)
    can_create = bool(person["is_principal"] and person["can_view_index"] and "reperes" in modules.enabled_keys(current_ctx()))
    choices = [m for m in _all_milestones(person) if not m["archived"]] if can_create else []
    return render_template("decisions.html", items=items, can_create=can_create, choices=choices)


@pages.get("/decisions/nouvelle")
def decision_new():
    person = _need()
    milestone_id = request.args.get("repere", "")
    if not str(milestone_id).isdigit():
        raise AppError(400, "validation", "Choisissez un repère.")
    item = milestones.get_milestone(current_ctx(), person, int(milestone_id))
    form = {"milestone_id": item["id"], "milestone_name": item["name"]}
    return render_template("decision_form.html", form=form, errors={}, editing=False)


@pages.post("/decisions")
def decision_create():
    person = _need()
    form = request.form.to_dict()
    try:
        new_id = decisions.create_decision(current_ctx(), person, _decision_fields(form, form.get("milestone_id")))
    except AppError as exc:
        if exc.status == 400:
            return render_template("decision_form.html", form=form, errors=exc.fields, editing=False), 400
        raise
    return _go("saved", "pages.decision_get", decision_id=new_id)


@pages.get("/decisions/<int:decision_id>")
def decision_get(decision_id):
    person = _need()
    item = decisions.decision_payload(current_ctx(), person, decision_id)
    return render_template("decision.html", item=item)


@pages.get("/decisions/<int:decision_id>/modifier")
def decision_edit(decision_id):
    person = _need()
    item = decisions.decision_payload(current_ctx(), person, decision_id)
    if item["sealed_at"]:
        raise AppError(409, "conflict", "La page scellée ne peut plus être modifiée.")
    return render_template("decision_form.html", form=_decision_form(item), errors={}, editing=True, item=item)


@pages.post("/decisions/<int:decision_id>")
def decision_update(decision_id):
    person = _need()
    form = request.form.to_dict()
    version = int(form["draft_version"]) if str(form.get("draft_version", "")).isdigit() else None
    try:
        decisions.update_decision(current_ctx(), person, decision_id, _decision_fields(form, None), version)
    except AppError as exc:
        if exc.status == 400:
            form["draft_version"] = form.get("draft_version", "")
            return render_template("decision_form.html", form=form, errors=exc.fields, editing=True), 400
        raise
    return _go("saved", "pages.decision_get", decision_id=decision_id)


@pages.get("/decisions/<int:decision_id>/sceller")
def decision_seal_get(decision_id):
    person = _need()
    item = decisions.decision_payload(current_ctx(), person, decision_id)
    return render_template("decision_seal.html", item=item)


@pages.post("/decisions/<int:decision_id>/sceller")
def decision_seal_post(decision_id):
    person = _need()
    version = int(request.form["draft_version"]) if str(request.form.get("draft_version", "")).isdigit() else None
    decisions.seal_decision(current_ctx(), person, decision_id, version, request.form.get("confirm") == "oui")
    return _go("sealed", "pages.decision_get", decision_id=decision_id)


@pages.get("/decisions/<int:decision_id>/resultat")
def decision_result_get(decision_id):
    person = _need()
    item = decisions.decision_payload(current_ctx(), person, decision_id)
    return render_template("decision_result.html", item=item, form={}, errors={}, review=False)


@pages.post("/decisions/<int:decision_id>/resultat")
def decision_result_post(decision_id):
    person = _need()
    item = decisions.decision_payload(current_ctx(), person, decision_id)
    form = request.form.to_dict()
    if form.get("step") != "commit":
        try:
            text_value(form.get("body"), "body", 4000, required=True, label="Le résultat")
        except AppError as exc:
            return render_template("decision_result.html", item=item, form=form, errors=exc.fields, review=False), 400
        return render_template("decision_result.html", item=item, form=form, errors={}, review=True)
    decisions.add_result(current_ctx(), person, decision_id, form.get("body"), form.get("confirm") == "oui")
    return _go("result", "pages.decision_get", decision_id=decision_id)


@pages.get("/coffre")
def vault_get():
    return _vault_page(_need(), {})


VAULT_KINDS = {"pdf": "PDF", "png": "Image", "jpg": "Image", "jpeg": "Image"}


def _vault_page(person, errors, status=200):
    """Explorateur : filtres appliqués sur la liste déjà restreinte par `vault.list_files`."""
    every = vault.list_files(current_ctx(), person)
    for item in every:
        extension = item["original_name"].rsplit(".", 1)[-1].lower() if "." in item["original_name"] else ""
        item["kind"] = VAULT_KINDS.get(extension, "Fichier")
    q = request.args.get("q", "").strip().lower()
    kind = request.args.get("type", "")
    repere = request.args.get("repere", "")
    items = [
        item for item in every
        if (not q or q in item["original_name"].lower() or q in (item.get("milestone_name") or "").lower())
        and (not kind or item["kind"] == kind)
        and (not repere or str(item.get("milestone_id", "")) == repere)
    ]
    items.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    choices = _all_milestones(person) if person["is_principal"] and person["can_view_index"] else []
    linked = sorted({(item["milestone_id"], item["milestone_name"]) for item in every if "milestone_id" in item},
                    key=lambda pair: pair[1].lower())
    return render_template(
        "vault.html", items=items, total=len(every), choices=choices, errors=errors,
        reperes=linked, args=request.args, filtered=bool(q or kind or repere),
    ), status


@pages.post("/coffre")
def vault_post():
    person = _need()
    try:
        vault.store_file(
            current_ctx(), person, request.form.get("milestone_id"), request.files.get("file"),
            request.form.get("confirm") == "oui",
        )
    except AppError as exc:
        if exc.status in {400, 413, 415, 409}:
            return _vault_page(person, exc.fields or {"form": exc.message}, exc.status)
        raise
    return _go("uploaded", "pages.vault_get")


@pages.get("/coffre/<int:file_id>/remplacer")
def file_replace_get(file_id):
    person = _need()
    item = _own_file(person, file_id)
    return render_template("file_replace.html", item=item, errors={})


@pages.post("/coffre/<int:file_id>/remplacer")
def file_replace_post(file_id):
    person = _need()
    try:
        vault.replace_file(
            current_ctx(), person, file_id, request.files.get("file"),
            request.form.get("version"), request.form.get("confirm") == "oui",
        )
    except AppError as exc:
        if exc.status in {400, 413, 415}:
            item = _own_file(person, file_id)
            return render_template("file_replace.html", item=item, errors=exc.fields or {"form": exc.message}), exc.status
        raise
    return _go("replaced", "pages.vault_get")


@pages.get("/coffre/<int:file_id>/retirer")
def file_delete_get(file_id):
    person = _need()
    item = _own_file(person, file_id)
    return _confirm(
        "Retirer cette pièce",
        "Le repère indiquera qu'aucune pièce n'est au coffre. Les sauvegardes déjà faites peuvent encore la contenir.",
        "Retirer",
        url_for("pages.file_delete_post", file_id=file_id),
        url_for("pages.vault_get"),
        {},
    )


@pages.post("/coffre/<int:file_id>/retirer")
def file_delete_post(file_id):
    person = _need()
    vault.delete_file(current_ctx(), person, file_id, request.form.get("confirm") == "oui")
    return _go("removed", "pages.vault_get")


@pages.get("/coffre/<int:file_id>/ouvrir")
def file_open(file_id):
    from flask import Response
    from ..http import content_disposition
    person = _need()
    data, name, mime = vault.read_file(current_ctx(), person, file_id)
    response = Response(data, mimetype=mime)
    response.headers["Content-Disposition"] = content_disposition(name)
    return response


@pages.get("/personnes")
def people_get():
    person = _need()
    return render_template("people.html", items=people.list_people(current_ctx(), person))


@pages.get("/personnes/ajouter")
def person_new():
    person = _need()
    from ..services.auth import require_principal
    require_principal(person)
    return render_template("person_form.html", form={}, errors={})


@pages.post("/personnes/ajouter")
@pages.post("/personnes")
def person_create():
    """POST on /personnes (canonical, url_for) and /personnes/ajouter (same-URL submit / old clients)."""
    person = _need()
    form = request.form.to_dict()
    username = password = None
    errors = {}
    if form.get("with_account") == "oui":
        username = form.get("username")
        password = form.get("password")
        if password != form.get("password_confirm"):
            errors["password_confirm"] = "Les deux saisies diffèrent."
    elif form.get("username") or form.get("password"):
        errors["with_account"] = "Cochez la création du compte, ou effacez l'identifiant."
    if errors:
        return render_template("person_form.html", form=form, errors=errors), 400
    try:
        people.add_person(current_ctx(), person, form.get("display_name"), form.get("relationship") or "", username, password)
    except AppError as exc:
        if exc.status in {400, 409}:
            fields = exc.fields or {"form": exc.message}
            return render_template("person_form.html", form=form, errors=fields), exc.status
        raise
    return _go("person", "pages.foyer_get")


@pages.get("/personnes/<int:person_id>/compte")
def account_get(person_id):
    _need()
    target = _person(person_id)
    return render_template("account_form.html", target=target, form={}, errors={})


@pages.post("/personnes/<int:person_id>/compte")
def account_post(person_id):
    person = _need()
    form = request.form.to_dict()
    if form.get("password") != form.get("password_confirm"):
        target = _person(person_id)
        return render_template(
            "account_form.html", target=target, form=form, errors={"password_confirm": "Les deux saisies diffèrent."},
        ), 400
    try:
        people.create_account(current_ctx(), person, person_id, form.get("username"), form.get("password"))
    except AppError as exc:
        if exc.status in {400, 409}:
            target = _person(person_id)
            return render_template(
                "account_form.html", target=target, form=form, errors=exc.fields or {"form": exc.message},
            ), exc.status
        raise
    return _go("account", "pages.people_get")


@pages.get("/personnes/<int:person_id>/retirer")
def deactivate_get(person_id):
    _need()
    target = _person(person_id)
    return _confirm(
        "Retirer cette personne",
        "Son accès est fermé immédiatement. Les pages et repères qui la citent restent.",
        "Retirer du foyer",
        url_for("pages.deactivate_post", person_id=person_id),
        url_for("pages.people_get"),
        {},
    )


@pages.post("/personnes/<int:person_id>/retirer")
def deactivate_post(person_id):
    person = _need()
    people.deactivate_person(current_ctx(), person, person_id, request.form.get("confirm") == "oui")
    return _go("deactivated", "pages.people_get")


@pages.get("/acces")
def access_index():
    person = _need()
    items = [item for item in people.list_people(current_ctx(), person) if not item["is_principal"] and item["active"] and item["has_account"]]
    return render_template("access_index.html", items=items)


@pages.get("/acces/<int:person_id>")
def access_get(person_id):
    person = _need()
    state = people.access_state(current_ctx(), person, person_id)
    target = _person(person_id)
    return render_template("access.html", state=state, target=target)


@pages.post("/acces/<int:person_id>")
def access_post(person_id):
    person = _need()
    decision_ids = _ints(request.form.getlist("decision"))
    file_ids = _ints(request.form.getlist("file"))
    people.apply_access_form(
        current_ctx(), person, person_id, request.form.get("index") == "oui", decision_ids, file_ids,
    )
    return _go("access", "pages.access_get", person_id=person_id)


def _people():
    return people.list_people(current_ctx(), g.person)


def _members():
    return people.list_active_members(current_ctx(), g.person)


def _minor_form(minor):
    if minor is None:
        return ""
    whole, cents = divmod(int(minor), 100)
    return f"{whole},{cents:02d}"


def _person(person_id):
    for item in _people():
        if item["id"] == person_id:
            return item
    raise AppError(404, "not_found", "Introuvable.")


def _all_milestones(person):
    found = []
    page = 1
    while True:
        batch = milestones.list_milestones(current_ctx(), person, archives=True, page=page)
        found.extend(batch["items"])
        if page * 50 >= batch["total"]:
            break
        page += 1
    return found


def _own_file(person, file_id):
    for item in vault.list_files(current_ctx(), person):
        if item["id"] == file_id:
            return item
    raise AppError(404, "not_found", "Introuvable.")


def _milestone_form(item):
    amount = ""
    if item["amount_cents"] is not None:
        euros, cents = divmod(item["amount_cents"], 100)
        amount = f"{euros},{cents:02d}"
    return {
        "name": item["name"],
        "category": item["category"],
        "holder_id": str(item["holder_id"]),
        "responsible_id": "" if item["responsible_id"] is None else str(item["responsible_id"]),
        "location": item["location"],
        "amount": amount,
        "due_date": item["due_date"] or "",
        "notice_days": str(item["notice_days"]),
        "note": item["note"],
        "updated_at": item["updated_at"],
        "milestone_id": item["id"],
    }


def _decision_form(item):
    options = [option for option in item["options"] if option != "Ne rien faire"]
    form = {
        "choice": item["choice"],
        "expected": item["expected"],
        "reconsider_if": item["reconsider_if"],
        "draft_version": str(item["draft_version"]),
        "rule_name": (item["rule"] or {}).get("name", ""),
        "milestone_id": item.get("milestone_id", ""),
        "milestone_name": item.get("milestone_name", ""),
    }
    for index, option in enumerate(options):
        form[f"option_{index}"] = option
    lines = (item["rule"] or {}).get("lines", [])
    for index, line in enumerate(lines):
        form[f"rule_label_{index}"] = line["label"]
        form[f"rule_value_{index}"] = line["value"]
    return form


def _ints(values):
    found = []
    for value in values:
        if not str(value).isdigit():
            raise AppError(404, "not_found", "Introuvable.")
        found.append(int(value))
    return found


def _confirm(heading, text, label, action, cancel, hidden):
    return render_template("confirm.html", heading=heading, text=text, label=label, action=action, cancel=cancel, hidden=hidden)


def _response(body, status=200):
    from flask import make_response
    return make_response(body, status)
