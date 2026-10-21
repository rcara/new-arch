BEGIN;

CREATE TABLE inventory_place (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=2000),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX inventory_place_hh ON inventory_place(household_id, archived);
CREATE TRIGGER inventory_place_no_delete BEFORE DELETE ON inventory_place
BEGIN SELECT RAISE(ABORT,'archive place instead'); END;

CREATE TABLE inventory_item (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 200),
  category TEXT NOT NULL DEFAULT '' CHECK(length(category)<=120),
  place_id INTEGER REFERENCES inventory_place(id),
  condition TEXT NOT NULL DEFAULT 'good' CHECK(condition IN('new','good','fair','poor','broken','disposed')),
  serial_number TEXT NOT NULL DEFAULT '' CHECK(length(serial_number)<=120),
  purchase_date TEXT CHECK(purchase_date IS NULL OR (length(purchase_date)=10 AND purchase_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  purchase_price_minor INTEGER CHECK(purchase_price_minor IS NULL OR (typeof(purchase_price_minor)='integer' AND purchase_price_minor>=0)),
  purchase_currency TEXT CHECK(purchase_currency IS NULL OR purchase_currency IN('CHF','EUR')),
  estimated_value_minor INTEGER CHECK(estimated_value_minor IS NULL OR (typeof(estimated_value_minor)='integer' AND estimated_value_minor>=0)),
  estimated_currency TEXT CHECK(estimated_currency IS NULL OR estimated_currency IN('CHF','EUR')),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=4000),
  visibility TEXT NOT NULL DEFAULT 'household' CHECK(visibility IN('household','private')),
  purchase_transaction_id INTEGER REFERENCES finance_transaction(id),
  invoice_file_id INTEGER REFERENCES stored_file(id),
  created_by INTEGER NOT NULL REFERENCES person(id),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK(
    (purchase_price_minor IS NULL AND purchase_currency IS NULL)
    OR (purchase_price_minor IS NOT NULL AND purchase_currency IS NOT NULL)
  ),
  CHECK(
    (estimated_value_minor IS NULL AND estimated_currency IS NULL)
    OR (estimated_value_minor IS NOT NULL AND estimated_currency IS NOT NULL)
  )
);
CREATE INDEX inventory_item_hh ON inventory_item(household_id, archived, place_id);
CREATE TRIGGER inventory_item_no_delete BEFORE DELETE ON inventory_item
BEGIN SELECT RAISE(ABORT,'archive item instead'); END;

CREATE TABLE inventory_item_owner (
  item_id INTEGER NOT NULL REFERENCES inventory_item(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  PRIMARY KEY(item_id, person_id)
);

CREATE TABLE inventory_warranty (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES inventory_item(id),
  label TEXT NOT NULL CHECK(length(trim(label)) BETWEEN 1 AND 200),
  starts_on TEXT CHECK(starts_on IS NULL OR (length(starts_on)=10 AND starts_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  ends_on TEXT CHECK(ends_on IS NULL OR (length(ends_on)=10 AND ends_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  provider TEXT NOT NULL DEFAULT '' CHECK(length(provider)<=200),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=2000),
  calendar_event_id INTEGER REFERENCES calendar_event(id),
  created_at TEXT NOT NULL,
  CHECK(ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on)
);
CREATE INDEX inventory_warranty_item ON inventory_warranty(item_id, ends_on);

CREATE TABLE inventory_maintenance (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES inventory_item(id),
  performed_on TEXT NOT NULL CHECK(length(performed_on)=10 AND performed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  label TEXT NOT NULL CHECK(length(trim(label)) BETWEEN 1 AND 200),
  cost_minor INTEGER CHECK(cost_minor IS NULL OR (typeof(cost_minor)='integer' AND cost_minor>=0)),
  currency TEXT CHECK(currency IS NULL OR currency IN('CHF','EUR')),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=2000),
  created_by INTEGER NOT NULL REFERENCES person(id),
  created_at TEXT NOT NULL,
  CHECK(
    (cost_minor IS NULL AND currency IS NULL)
    OR (cost_minor IS NOT NULL AND currency IS NOT NULL)
  )
);

CREATE TABLE inventory_history (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES inventory_item(id),
  event_type TEXT NOT NULL CHECK(event_type IN(
    'created','updated','transferred','disposed','condition_changed','linked','maintenance','warranty'
  )),
  body TEXT NOT NULL DEFAULT '' CHECK(length(body)<=2000),
  actor_id INTEGER NOT NULL REFERENCES person(id),
  created_at TEXT NOT NULL
);
CREATE INDEX inventory_history_item ON inventory_history(item_id, id);

UPDATE module_setting SET enabled=1 WHERE module_key='inventaire';
INSERT OR IGNORE INTO module_setting(household_id, module_key, enabled)
SELECT 1, 'inventaire', 1 WHERE EXISTS(SELECT 1 FROM household WHERE id=1);

PRAGMA user_version = 5;
COMMIT;
