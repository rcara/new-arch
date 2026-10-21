BEGIN;

CREATE TABLE module_setting (
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  module_key TEXT NOT NULL CHECK(module_key IN (
    'accueil','foyer','finances','inventaire','calendrier','organisation',
    'coffre','decisions','mediatheque','reperes','recherche','parametres'
  )),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN(0,1)),
  PRIMARY KEY(household_id, module_key)
);

CREATE TABLE object_link (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  source_type TEXT NOT NULL CHECK(length(trim(source_type)) BETWEEN 1 AND 40),
  source_id INTEGER NOT NULL CHECK(typeof(source_id)='integer' AND source_id>0),
  target_type TEXT NOT NULL CHECK(length(trim(target_type)) BETWEEN 1 AND 40),
  target_id INTEGER NOT NULL CHECK(typeof(target_id)='integer' AND target_id>0),
  relation_type TEXT NOT NULL CHECK(length(trim(relation_type)) BETWEEN 1 AND 40),
  created_by INTEGER NOT NULL REFERENCES person(id),
  created_at TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  UNIQUE(household_id, source_type, source_id, target_type, target_id, relation_type)
);
CREATE INDEX object_link_source ON object_link(household_id, source_type, source_id) WHERE archived=0;
CREATE INDEX object_link_target ON object_link(household_id, target_type, target_id) WHERE archived=0;

CREATE TABLE task (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=4000),
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN('open','done','cancelled')),
  priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN('low','normal','high')),
  assignee_id INTEGER REFERENCES person(id),
  created_by INTEGER NOT NULL REFERENCES person(id),
  due_date TEXT CHECK(due_date IS NULL OR (length(due_date)=10 AND due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  recurrence TEXT NOT NULL DEFAULT 'none' CHECK(recurrence IN('none','daily','weekly','monthly','yearly')),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE INDEX task_open ON task(household_id, status, due_date) WHERE archived=0;
CREATE TRIGGER task_no_delete BEFORE DELETE ON task
BEGIN SELECT RAISE(ABORT,'archive task instead'); END;

CREATE TABLE calendar_event (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=4000),
  all_day INTEGER NOT NULL DEFAULT 1 CHECK(all_day IN(0,1)),
  start_date TEXT NOT NULL CHECK(length(start_date)=10 AND start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  end_date TEXT CHECK(end_date IS NULL OR (length(end_date)=10 AND end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  start_at TEXT,
  end_at TEXT,
  timezone TEXT NOT NULL DEFAULT 'Europe/Zurich',
  responsible_id INTEGER REFERENCES person(id),
  created_by INTEGER NOT NULL REFERENCES person(id),
  recurrence TEXT NOT NULL DEFAULT 'none' CHECK(recurrence IN('none','daily','weekly','monthly','yearly')),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK(end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX calendar_event_range ON calendar_event(household_id, start_date, archived);
CREATE TRIGGER calendar_event_no_delete BEFORE DELETE ON calendar_event
BEGIN SELECT RAISE(ABORT,'archive calendar event instead'); END;

INSERT OR IGNORE INTO module_setting(household_id, module_key, enabled)
SELECT 1, key, enabled FROM (
  SELECT 'accueil' AS key, 1 AS enabled UNION ALL
  SELECT 'foyer', 1 UNION ALL
  SELECT 'finances', 0 UNION ALL
  SELECT 'inventaire', 0 UNION ALL
  SELECT 'calendrier', 1 UNION ALL
  SELECT 'organisation', 1 UNION ALL
  SELECT 'coffre', 1 UNION ALL
  SELECT 'decisions', 1 UNION ALL
  SELECT 'mediatheque', 0 UNION ALL
  SELECT 'reperes', 1 UNION ALL
  SELECT 'recherche', 1 UNION ALL
  SELECT 'parametres', 1
)
WHERE EXISTS(SELECT 1 FROM household WHERE id=1);

PRAGMA user_version = 3;
COMMIT;
