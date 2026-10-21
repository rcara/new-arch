"""Six écrans et les états d'entrée."""

from flask import Blueprint, g, redirect, render_template, request, url_for

from .. import current_ctx
from ..errors import AppError
from ..http import cookie_message, cookie_session, cookie_setup, safe_next
from ..security import new_token
from ..services import auth, decisions, events, home, links, milestones, modules, people, search, tasks, vault
from ..validate import text_value

pages = Blueprint("pages", __name__)


def _limiter():
    from flask import current_app
    return current_app.config["LIMITER"]


def _go(code, endpoint, **kwargs):
    response = redirect(url_for(endpoint, **kwargs))
    return cookie_message(response, code)


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
        token, csrf, _profile = auth.bootstrap(
            current_ctx(), _limiter(), form.get("household_name"), form.get("timezone") or "Europe/Zurich",
            form.get("display_name"), form.get("username"), form.get("password"),
        )
    except AppError as exc:
        if exc.status == 400:
            g.setup_token = request.cookies.get("foyer_setup", "")
            return render_template("bootstrap.html", form=form, errors=exc.fields), 400
        raise
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
    return render_template("today.html", summary=summary)


@pages.get("/organisation")
def tasks_get():
    person = _need()
    modules.require_module(current_ctx(), "organisation")
    status = request.args.get("status", "open")
    listed = tasks.list_tasks(current_ctx(), person, status=status, q=request.args.get("q", ""))
    return render_template("tasks.html", listed=listed, args=request.args)


@pages.get("/organisation/nouvelle")
def task_new():
    _need()
    modules.require_module(current_ctx(), "organisation")
    return render_template(
        "task_form.html", form={"priority": "normal", "recurrence": "none"}, errors={}, people=_members(), editing=False,
    )


@pages.post("/organisation")
def task_create():
    person = _need()
    form = request.form.to_dict()
    try:
        tasks.create_task(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "task_form.html", form=form, errors=exc.fields, people=_members(), editing=False,
            ), 400
        raise
    return _go("task_saved", "pages.tasks_get")


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
    listed = events.list_events(
        current_ctx(), person,
        from_date=request.args.get("from") or None,
        to_date=request.args.get("to") or None,
        q=request.args.get("q", ""),
    )
    return render_template("events.html", listed=listed, args=request.args)


@pages.get("/calendrier/nouveau")
def event_new():
    _need()
    modules.require_module(current_ctx(), "calendrier")
    return render_template(
        "event_form.html",
        form={"all_day": "1", "recurrence": "none", "timezone": (g.household or {}).get("timezone", "Europe/Zurich")},
        errors={}, people=_members(), editing=False,
    )


@pages.post("/calendrier")
def event_create():
    person = _need()
    form = request.form.to_dict()
    form["all_day"] = "1" if request.form.get("all_day") == "1" else "0"
    try:
        events.create_event(current_ctx(), person, form)
    except AppError as exc:
        if exc.status == 400:
            return render_template(
                "event_form.html", form=form, errors=exc.fields, people=_members(), editing=False,
            ), 400
        raise
    return _go("event_saved", "pages.events_get")


@pages.get("/calendrier/<int:event_id>")
def event_get(event_id):
    person = _need()
    item = events.get_event(current_ctx(), person, event_id)
    return render_template("event.html", item=item)


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
                return render_template("search.html", results=results, errors=exc.fields), 400
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
    return render_template("settings.html", modules=modules.list_modules(current_ctx()), household=g.household)


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
    return _go("saved", "pages.milestone_get", milestone_id=new_id)


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
    items = decisions.list_decisions(current_ctx(), person)
    return render_template("decisions.html", items=items)


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
    person = _need()
    items = vault.list_files(current_ctx(), person)
    choices = _all_milestones(person) if person["is_principal"] and person["can_view_index"] else []
    return render_template("vault.html", items=items, choices=choices, errors={})


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
            items = vault.list_files(current_ctx(), person)
            return render_template(
                "vault.html", items=items, choices=_all_milestones(person), errors=exc.fields or {"form": exc.message},
            ), exc.status
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
    _need()
    return render_template("person_form.html", form={}, errors={})


@pages.post("/personnes")
def person_create():
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
    return _go("person", "pages.people_get")


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
