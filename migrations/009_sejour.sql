-- Séjours du foyer : page Agenda, enveloppe par poste, dépenses rattachées.
-- L'enveloppe n'est pas un finance_budget (catégorie + mois/année).
-- Le rattachement vit ici (poste d'enveloppe) et non dans object_link, qui n'a pas de charge utile.
-- La visibilité des montants dépensés reste celle de finance_transaction.
BEGIN;

CREATE TABLE sejour (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
  destination TEXT NOT NULL DEFAULT '' CHECK(length(destination)<=200),
  start_date TEXT NOT NULL CHECK(length(start_date)=10 AND start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  end_date TEXT NOT NULL CHECK(length(end_date)=10 AND end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  currency TEXT NOT NULL CHECK(currency IN('CHF','EUR')),
  created_by INTEGER NOT NULL REFERENCES person(id),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK(end_date >= start_date)
);
CREATE INDEX sejour_range ON sejour(household_id, start_date, end_date) WHERE archived=0;
CREATE TRIGGER sejour_no_delete BEFORE DELETE ON sejour
BEGIN SELECT RAISE(ABORT,'archive sejour instead'); END;

CREATE TABLE sejour_participant (
  sejour_id INTEGER NOT NULL REFERENCES sejour(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  PRIMARY KEY(sejour_id, person_id)
);

CREATE TABLE sejour_envelope_line (
  id INTEGER PRIMARY KEY,
  sejour_id INTEGER NOT NULL REFERENCES sejour(id),
  line_key TEXT NOT NULL CHECK(line_key IN('transport','logement','repas','activites','divers')),
  amount_minor INTEGER NOT NULL CHECK(typeof(amount_minor)='integer' AND amount_minor>=0),
  UNIQUE(sejour_id, line_key)
);

CREATE TABLE sejour_expense (
  id INTEGER PRIMARY KEY,
  sejour_id INTEGER NOT NULL REFERENCES sejour(id),
  transaction_id INTEGER NOT NULL REFERENCES finance_transaction(id),
  line_key TEXT NOT NULL CHECK(line_key IN('transport','logement','repas','activites','divers')),
  created_by INTEGER NOT NULL REFERENCES person(id),
  created_at TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1))
);
CREATE INDEX sejour_expense_sejour ON sejour_expense(sejour_id) WHERE archived=0;
CREATE UNIQUE INDEX sejour_expense_active ON sejour_expense(sejour_id, transaction_id) WHERE archived=0;
CREATE UNIQUE INDEX sejour_expense_one_trip ON sejour_expense(transaction_id) WHERE archived=0;
CREATE TRIGGER sejour_expense_no_delete BEFORE DELETE ON sejour_expense
BEGIN SELECT RAISE(ABORT,'archive sejour expense instead'); END;

PRAGMA user_version = 9;
COMMIT;
