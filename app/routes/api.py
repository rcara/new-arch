"""Contrats JSON sous /api."""

from flask import Blueprint, g, jsonify, request

from .. import current_ctx
from ..errors import AppError
from ..http import json_body
from ..services import auth, decisions, events, finance, home, links, milestones, modules, people, search, tasks, vault

api = Blueprint("api", __name__)


def actor():
    if g.person is None:
        raise AppError(401, "unauthorized", "Connexion requise.")
    return g.person


def confirm(data):
    return data.get("confirm") is True


def version_of(data, key):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AppError(409, "conflict", "Rechargez la page avant de confirmer.")
    return value


@api.post("/bootstrap")
def bootstrap():
    data = json_body({"household_name", "timezone", "display_name", "username", "password"})
    token, csrf, profile = auth.bootstrap(
        current_ctx(), g.get("limiter") or _limiter(),
        data.get("household_name"), data.get("timezone"), data.get("display_name"),
        data.get("username"), data.get("password"),
    )
    from ..http import cookie_session
    response = jsonify(profile)
    response.status_code = 201
    g.csrf_token = csrf
    cookie_session(response, token)
    return response


@api.post("/session")
def login():
    data = json_body({"username", "password"})
    token, csrf, profile = auth.open_session(current_ctx(), _limiter(), data.get("username"), data.get("password"))
    from ..http import cookie_session
    response = jsonify(profile)
    g.csrf_token = csrf
    g.person = {"id": profile["person_id"]}
    cookie_session(response, token)
    return response


@api.delete("/session")
def logout():
    actor()
    auth.close_session(current_ctx(), request.cookies.get("foyer_session"))
    response = jsonify({})
    response.status_code = 204
    response.delete_cookie("foyer_session", path="/")
    return response


@api.get("/me")
def me():
    return jsonify(auth.profile(actor()))


@api.get("/today")
def today():
    return jsonify(milestones.today_items(current_ctx(), actor()))


@api.get("/milestones")
def milestone_list():
    archives = request.args.get("archives") == "1"
    page = request.args.get("page", "1")
    page = int(page) if page.isdigit() else 1
    return jsonify(milestones.list_milestones(
        current_ctx(), actor(),
        q=request.args.get("q", ""),
        category=request.args.get("category", ""),
        statut=request.args.get("statut", ""),
        archives=archives,
        page=page,
    ))


@api.post("/milestones")
def milestone_create():
    data = json_body({
        "name", "category", "holder_id", "responsible_id", "location",
        "amount_cents", "due_date", "notice_days", "note",
    })
    new_id = milestones.create_milestone(current_ctx(), actor(), data)
    item = milestones.get_milestone(current_ctx(), actor(), new_id)
    return jsonify(item), 201


@api.get("/milestones/<int:milestone_id>")
def milestone_get(milestone_id):
    return jsonify(milestones.get_milestone(current_ctx(), actor(), milestone_id))


@api.patch("/milestones/<int:milestone_id>")
def milestone_patch(milestone_id):
    data = json_body({
        "name", "category", "holder_id", "responsible_id", "location",
        "amount_cents", "due_date", "notice_days", "note", "archived", "updated_at",
    })
    if "updated_at" not in data:
        raise AppError(409, "conflict", "Rechargez le repère avant de l'enregistrer.")
    archive = None
    if "archived" in data:
        if not isinstance(data["archived"], bool):
            raise AppError(400, "validation", "Archive invalide.", {"archived": "Indiquez vrai ou faux."})
        archive = data["archived"]
    milestones.update_milestone(current_ctx(), actor(), milestone_id, data, data["updated_at"], archive=archive)
    return jsonify(milestones.get_milestone(current_ctx(), actor(), milestone_id))


@api.get("/decisions")
def decision_list():
    return jsonify({"items": decisions.list_decisions(current_ctx(), actor())})


@api.post("/decisions")
def decision_create():
    data = json_body({"milestone_id", "choice", "options", "expected", "reconsider_if", "rule"})
    new_id = decisions.create_decision(current_ctx(), actor(), data)
    return jsonify(decisions.decision_payload(current_ctx(), actor(), new_id)), 201


@api.get("/decisions/<int:decision_id>")
def decision_get(decision_id):
    return jsonify(decisions.decision_payload(current_ctx(), actor(), decision_id))


@api.patch("/decisions/<int:decision_id>")
def decision_patch(decision_id):
    data = json_body({"choice", "options", "expected", "reconsider_if", "rule", "draft_version"})
    decisions.update_decision(current_ctx(), actor(), decision_id, data, version_of(data, "draft_version"))
    return jsonify(decisions.decision_payload(current_ctx(), actor(), decision_id))


@api.post("/decisions/<int:decision_id>/seal")
def decision_seal(decision_id):
    data = json_body({"confirm", "draft_version"})
    decisions.seal_decision(current_ctx(), actor(), decision_id, version_of(data, "draft_version"), confirm(data))
    return jsonify(decisions.decision_payload(current_ctx(), actor(), decision_id))


@api.post("/decisions/<int:decision_id>/result")
def decision_result(decision_id):
    data = json_body({"confirm", "body"})
    decisions.add_result(current_ctx(), actor(), decision_id, data.get("body"), confirm(data))
    return jsonify(decisions.decision_payload(current_ctx(), actor(), decision_id)), 201


@api.get("/files")
def file_list():
    return jsonify({"items": vault.list_files(current_ctx(), actor())})


@api.post("/files")
def file_store():
    milestone_id = request.form.get("milestone_id")
    confirm_value = request.form.get("confirm") == "true"
    item = vault.store_file(current_ctx(), actor(), milestone_id, request.files.get("file"), confirm_value)
    return jsonify(item), 201


@api.post("/files/<int:file_id>/replace")
def file_replace(file_id):
    item = vault.replace_file(
        current_ctx(), actor(), file_id, request.files.get("file"),
        request.form.get("version"), request.form.get("confirm") == "true",
    )
    return jsonify(item)


@api.get("/files/<int:file_id>/content")
def file_content(file_id):
    from flask import Response
    from ..http import content_disposition
    data, name, mime = vault.read_file(current_ctx(), actor(), file_id)
    response = Response(data, mimetype=mime)
    response.headers["Content-Disposition"] = content_disposition(name)
    return response


@api.delete("/files/<int:file_id>")
def file_delete(file_id):
    data = json_body({"confirm"})
    vault.delete_file(current_ctx(), actor(), file_id, confirm(data))
    return "", 204


@api.get("/people")
def people_list():
    return jsonify({"items": people.list_people(current_ctx(), actor())})


@api.post("/people")
def people_create():
    data = json_body({"display_name", "relationship", "username", "password"})
    new_id = people.add_person(
        current_ctx(), actor(), data.get("display_name"), data.get("relationship") or "",
        data.get("username"), data.get("password"),
    )
    return jsonify({"id": new_id}), 201


@api.patch("/people/<int:person_id>")
def people_patch(person_id):
    data = json_body({"display_name", "relationship"})
    people.update_person(current_ctx(), actor(), person_id, data.get("display_name"), data.get("relationship") or "")
    return jsonify({"id": person_id})


@api.post("/people/<int:person_id>/account")
def people_account(person_id):
    data = json_body({"username", "password"})
    people.create_account(current_ctx(), actor(), person_id, data.get("username"), data.get("password"))
    return "", 201


@api.post("/people/<int:person_id>/deactivate")
def people_deactivate(person_id):
    data = json_body({"confirm"})
    people.deactivate_person(current_ctx(), actor(), person_id, confirm(data))
    return "", 204


@api.get("/people/<int:person_id>/access")
def people_access(person_id):
    return jsonify(people.access_state(current_ctx(), actor(), person_id))


@api.put("/people/<int:person_id>/index-access")
def people_index(person_id):
    data = json_body({"allowed"})
    people.set_index_access(current_ctx(), actor(), person_id, data.get("allowed"))
    return "", 204


@api.put("/people/<int:person_id>/decisions/<int:decision_id>")
def people_grant_decision(person_id, decision_id):
    actor()
    people.grant_decision(current_ctx(), g.person, person_id, decision_id)
    return "", 204


@api.delete("/people/<int:person_id>/decisions/<int:decision_id>")
def people_revoke_decision(person_id, decision_id):
    actor()
    people.revoke_decision(current_ctx(), g.person, person_id, decision_id)
    return "", 204


@api.put("/people/<int:person_id>/files/<int:file_id>")
def people_grant_file(person_id, file_id):
    actor()
    people.grant_file(current_ctx(), g.person, person_id, file_id)
    return "", 204


@api.delete("/people/<int:person_id>/files/<int:file_id>")
def people_revoke_file(person_id, file_id):
    actor()
    people.revoke_file(current_ctx(), g.person, person_id, file_id)
    return "", 204


@api.get("/home")
def home_get():
    return jsonify(home.dashboard(current_ctx(), actor()))


@api.get("/modules")
def modules_get():
    actor()
    return jsonify({"items": modules.list_modules(current_ctx())})


@api.get("/tasks")
def task_list():
    page = request.args.get("page", "1")
    page = int(page) if page.isdigit() else 1
    return jsonify(tasks.list_tasks(
        current_ctx(), actor(),
        status=request.args.get("status", "open"),
        q=request.args.get("q", ""),
        page=page,
    ))


@api.post("/tasks")
def task_create():
    data = json_body({"title", "notes", "priority", "assignee_id", "due_date", "recurrence"})
    new_id = tasks.create_task(current_ctx(), actor(), data)
    return jsonify(tasks.get_task(current_ctx(), actor(), new_id)), 201


@api.get("/tasks/<int:task_id>")
def task_get(task_id):
    return jsonify(tasks.get_task(current_ctx(), actor(), task_id))


@api.patch("/tasks/<int:task_id>")
def task_patch(task_id):
    data = json_body({"title", "notes", "priority", "assignee_id", "due_date", "recurrence", "status"})
    return jsonify(tasks.update_task(current_ctx(), actor(), task_id, data))


@api.get("/events")
def event_list():
    page = request.args.get("page", "1")
    page = int(page) if page.isdigit() else 1
    return jsonify(events.list_events(
        current_ctx(), actor(),
        from_date=request.args.get("from") or None,
        to_date=request.args.get("to") or None,
        q=request.args.get("q", ""),
        page=page,
    ))


@api.post("/events")
def event_create():
    data = json_body({
        "title", "notes", "all_day", "start_date", "end_date",
        "timezone", "responsible_id", "recurrence",
    })
    new_id = events.create_event(current_ctx(), actor(), data)
    return jsonify(events.get_event(current_ctx(), actor(), new_id)), 201


@api.get("/events/<int:event_id>")
def event_get(event_id):
    return jsonify(events.get_event(current_ctx(), actor(), event_id))


@api.patch("/events/<int:event_id>")
def event_patch(event_id):
    data = json_body({
        "title", "notes", "all_day", "start_date", "end_date",
        "timezone", "responsible_id", "recurrence",
    })
    return jsonify(events.update_event(current_ctx(), actor(), event_id, data))


@api.get("/links")
def link_list():
    source_id = request.args.get("source_id")
    target_id = request.args.get("target_id")
    return jsonify(links.list_links(
        current_ctx(), actor(),
        source_type=request.args.get("source_type", ""),
        source_id=int(source_id) if source_id and source_id.isdigit() else None,
        target_type=request.args.get("target_type", ""),
        target_id=int(target_id) if target_id and target_id.isdigit() else None,
    ))


@api.post("/links")
def link_create():
    data = json_body({"source_type", "source_id", "target_type", "target_id", "relation_type"})
    new_id = links.create_link(current_ctx(), actor(), data)
    listed = links.list_links(current_ctx(), actor())
    item = next((row for row in listed["items"] if row["id"] == new_id), {"id": new_id})
    return jsonify(item), 201


@api.delete("/links/<int:link_id>")
def link_delete(link_id):
    links.archive_link(current_ctx(), actor(), link_id)
    return "", 204


@api.get("/search")
def search_get():
    return jsonify(search.search(current_ctx(), actor(), request.args.get("q", "")))


@api.get("/finance/accounts")
def finance_accounts():
    return jsonify(finance.list_ledger_accounts(current_ctx(), actor()))


@api.post("/finance/accounts")
def finance_account_create():
    data = json_body({"name", "currency", "account_kind", "owner_id"})
    new_id = finance.create_ledger_account(current_ctx(), actor(), data)
    items = finance.list_ledger_accounts(current_ctx(), actor())["items"]
    item = next(row for row in items if row["id"] == new_id)
    return jsonify(item), 201


@api.get("/finance/categories")
def finance_categories():
    return jsonify(finance.list_categories(current_ctx(), actor(), kind=request.args.get("kind", "")))


@api.get("/finance/transactions")
def finance_transactions():
    page = request.args.get("page", "1")
    page = int(page) if page.isdigit() else 1
    return jsonify(finance.list_transactions(
        current_ctx(), actor(),
        kind=request.args.get("kind", ""),
        currency=request.args.get("currency", ""),
        page=page,
    ))


@api.post("/finance/transactions")
def finance_transaction_create():
    data = json_body({
        "kind", "amount", "amount_minor", "currency", "txn_date", "label", "notes",
        "category_id", "ledger_account_id", "counterparty_account_id", "payer_id",
        "beneficiary_id", "visibility", "settles_transaction_id", "split_method",
        "split_person_ids", "person_ids", "splits",
    })
    new_id = finance.create_transaction(current_ctx(), actor(), data)
    return jsonify(finance.get_transaction(current_ctx(), actor(), new_id)), 201


@api.get("/finance/transactions/<int:txn_id>")
def finance_transaction_get(txn_id):
    return jsonify(finance.get_transaction(current_ctx(), actor(), txn_id))


@api.get("/finance/balances")
def finance_balances():
    return jsonify(finance.person_balances(current_ctx(), actor(), currency=request.args.get("currency", "CHF")))


@api.get("/finance/budgets")
def finance_budgets():
    year = request.args.get("year")
    month = request.args.get("month")
    return jsonify(finance.list_budgets(
        current_ctx(), actor(),
        year=int(year) if year and year.isdigit() else None,
        month=int(month) if month and month.isdigit() else None,
        currency=request.args.get("currency", "CHF"),
    ))


@api.post("/finance/budgets")
def finance_budget_create():
    data = json_body({"category_id", "period", "year", "month", "amount", "amount_minor", "currency"})
    new_id = finance.create_budget(current_ctx(), actor(), data)
    return jsonify({"id": new_id}), 201


@api.get("/finance/income-shares")
def finance_income_shares():
    return jsonify(finance.list_income_shares(current_ctx(), actor()))


@api.put("/finance/income-shares/<int:person_id>")
def finance_income_share_put(person_id):
    data = json_body({"income", "income_minor", "currency"})
    raw = data.get("income_minor", data.get("income"))
    return jsonify(finance.set_income_share(current_ctx(), actor(), person_id, raw, data.get("currency") or "CHF"))


@api.get("/finance/export.csv")
def finance_export():
    from flask import Response
    body = finance.export_csv(current_ctx(), actor(), currency=request.args.get("currency", ""))
    return Response(body, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="finances.csv"',
    })


@api.post("/finance/import.csv")
def finance_import():
    upload = request.files.get("file")
    if upload is None:
        raise AppError(400, "validation", "Fichier CSV requis.")
    result = finance.import_csv(current_ctx(), actor(), upload.read())
    return jsonify(result)


def _limiter():
    from flask import current_app
    return current_app.config["LIMITER"]
