PRAGMA foreign_keys=OFF;
BEGIN;

-- Autoriser plusieurs foyers (supprime CHECK id=1)
CREATE TABLE household_new (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL CHECK(length(trim(name))>0),
  timezone TEXT NOT NULL DEFAULT 'Europe/Zurich',
  created_at TEXT NOT NULL
);
INSERT INTO household_new(id, name, timezone, created_at)
SELECT id, name, timezone, created_at FROM household;
DROP TABLE household;
ALTER TABLE household_new RENAME TO household;

-- Un seul principal par foyer (plus un seul principal global)
DROP INDEX IF EXISTS one_principal;
CREATE UNIQUE INDEX one_principal_per_household ON person(household_id) WHERE is_principal=1;

-- Appartenances : un compte peut ouvrir plusieurs foyers (persona locale)
CREATE TABLE household_membership (
  login_person_id INTEGER NOT NULL REFERENCES account(person_id),
  household_id INTEGER NOT NULL REFERENCES household(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (login_person_id, household_id),
  UNIQUE(person_id)
);
INSERT INTO household_membership(login_person_id, household_id, person_id, created_at)
SELECT a.person_id, p.household_id, p.id, a.created_at
FROM account a
JOIN person p ON p.id=a.person_id;

-- Session : conserve login + persona active
DROP TRIGGER IF EXISTS revoke_person_sessions;
CREATE TABLE session_new (
  token_hash TEXT PRIMARY KEY,
  login_person_id INTEGER NOT NULL REFERENCES account(person_id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  csrf_token TEXT NOT NULL DEFAULT ''
);
INSERT INTO session_new(token_hash, login_person_id, person_id, expires_at, revoked_at, csrf_token)
SELECT token_hash, person_id, person_id, expires_at, revoked_at, csrf_token FROM session;
DROP TABLE session;
ALTER TABLE session_new RENAME TO session;

CREATE TRIGGER revoke_person_sessions_v7 AFTER UPDATE OF active ON person
WHEN NEW.active=0 AND OLD.active=1
BEGIN
  UPDATE session SET revoked_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
  WHERE (person_id=NEW.id OR login_person_id=NEW.id) AND revoked_at IS NULL;
END;

PRAGMA user_version=7;
COMMIT;
PRAGMA foreign_keys=ON;
