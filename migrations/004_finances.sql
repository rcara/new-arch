BEGIN;

CREATE TABLE finance_ledger_account (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
  currency TEXT NOT NULL CHECK(currency IN('CHF','EUR')),
  account_kind TEXT NOT NULL DEFAULT 'checking' CHECK(account_kind IN('checking','cash','savings','credit','other')),
  owner_id INTEGER REFERENCES person(id),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX finance_ledger_account_hh ON finance_ledger_account(household_id, archived);
CREATE TRIGGER finance_ledger_account_no_delete BEFORE DELETE ON finance_ledger_account
BEGIN SELECT RAISE(ABORT,'archive ledger account instead'); END;

CREATE TABLE finance_category (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
  kind TEXT NOT NULL CHECK(kind IN('expense','income')),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  UNIQUE(household_id, name, kind)
);
CREATE TRIGGER finance_category_no_delete BEFORE DELETE ON finance_category
BEGIN SELECT RAISE(ABORT,'archive category instead'); END;

CREATE TABLE finance_income_share (
  person_id INTEGER PRIMARY KEY REFERENCES person(id),
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  income_minor INTEGER NOT NULL DEFAULT 0 CHECK(typeof(income_minor)='integer' AND income_minor>=0),
  currency TEXT NOT NULL DEFAULT 'CHF' CHECK(currency IN('CHF','EUR')),
  updated_at TEXT NOT NULL
);

CREATE TABLE finance_transaction (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  kind TEXT NOT NULL CHECK(kind IN('expense','income','transfer','reimbursement')),
  amount_minor INTEGER NOT NULL CHECK(typeof(amount_minor)='integer' AND amount_minor>0),
  currency TEXT NOT NULL CHECK(currency IN('CHF','EUR')),
  txn_date TEXT NOT NULL CHECK(length(txn_date)=10 AND txn_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  label TEXT NOT NULL CHECK(length(trim(label)) BETWEEN 1 AND 200),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=4000),
  category_id INTEGER REFERENCES finance_category(id),
  ledger_account_id INTEGER NOT NULL REFERENCES finance_ledger_account(id),
  counterparty_account_id INTEGER REFERENCES finance_ledger_account(id),
  payer_id INTEGER NOT NULL REFERENCES person(id),
  beneficiary_id INTEGER REFERENCES person(id),
  created_by INTEGER NOT NULL REFERENCES person(id),
  visibility TEXT NOT NULL DEFAULT 'household' CHECK(visibility IN('household','private')),
  settles_transaction_id INTEGER REFERENCES finance_transaction(id),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK(counterparty_account_id IS NULL OR counterparty_account_id<>ledger_account_id),
  CHECK(kind<>'transfer' OR counterparty_account_id IS NOT NULL),
  CHECK(kind<>'reimbursement' OR beneficiary_id IS NOT NULL),
  CHECK(kind NOT IN('expense','income') OR category_id IS NOT NULL)
);
CREATE INDEX finance_txn_date ON finance_transaction(household_id, txn_date, archived);
CREATE INDEX finance_txn_kind ON finance_transaction(household_id, kind, archived);
CREATE TRIGGER finance_transaction_no_delete BEFORE DELETE ON finance_transaction
BEGIN SELECT RAISE(ABORT,'archive transaction instead'); END;

CREATE TABLE finance_split (
  id INTEGER PRIMARY KEY,
  transaction_id INTEGER NOT NULL REFERENCES finance_transaction(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  share_minor INTEGER NOT NULL CHECK(typeof(share_minor)='integer' AND share_minor>=0),
  method TEXT NOT NULL CHECK(method IN('equal','percent','fixed','income_prorata')),
  UNIQUE(transaction_id, person_id)
);
CREATE INDEX finance_split_person ON finance_split(person_id);

CREATE TABLE finance_budget (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  category_id INTEGER NOT NULL REFERENCES finance_category(id),
  period TEXT NOT NULL CHECK(period IN('month','year')),
  year INTEGER NOT NULL CHECK(typeof(year)='integer' AND year BETWEEN 2000 AND 2100),
  month INTEGER CHECK(month IS NULL OR (typeof(month)='integer' AND month BETWEEN 1 AND 12)),
  amount_minor INTEGER NOT NULL CHECK(typeof(amount_minor)='integer' AND amount_minor>=0),
  currency TEXT NOT NULL CHECK(currency IN('CHF','EUR')),
  created_by INTEGER NOT NULL REFERENCES person(id),
  created_at TEXT NOT NULL,
  CHECK((period='month' AND month IS NOT NULL) OR (period='year' AND month IS NULL)),
  UNIQUE(household_id, category_id, period, year, month, currency)
);

UPDATE module_setting SET enabled=1 WHERE module_key='finances';
INSERT OR IGNORE INTO module_setting(household_id, module_key, enabled)
SELECT 1, 'finances', 1 WHERE EXISTS(SELECT 1 FROM household WHERE id=1);

PRAGMA user_version = 4;
COMMIT;
