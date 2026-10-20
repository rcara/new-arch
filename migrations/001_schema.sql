PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE household (
 id INTEGER PRIMARY KEY CHECK(id=1),
 name TEXT NOT NULL CHECK(length(trim(name))>0),
 timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',
 created_at TEXT NOT NULL
);
CREATE TABLE person (
 id INTEGER PRIMARY KEY,
 household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
 display_name TEXT NOT NULL CHECK(length(trim(display_name))>0),
 relationship TEXT NOT NULL DEFAULT '',
 is_principal INTEGER NOT NULL DEFAULT 0 CHECK(is_principal IN(0,1)),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)),
 can_view_index INTEGER NOT NULL DEFAULT 1 CHECK(can_view_index IN(0,1)),
 created_at TEXT NOT NULL,
 CHECK(is_principal=0 OR (active=1 AND can_view_index=1))
);
CREATE UNIQUE INDEX one_principal ON person(is_principal) WHERE is_principal=1;
CREATE TRIGGER principal_fixed BEFORE UPDATE OF is_principal ON person
WHEN NEW.is_principal<>OLD.is_principal BEGIN SELECT RAISE(ABORT,'principal immutable'); END;
CREATE TRIGGER person_no_delete BEFORE DELETE ON person
BEGIN SELECT RAISE(ABORT,'deactivate person instead'); END;
CREATE TABLE account (
 person_id INTEGER PRIMARY KEY REFERENCES person(id),
 username TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK(length(trim(username))>0),
 password_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE session (
 token_hash TEXT PRIMARY KEY,
 person_id INTEGER NOT NULL REFERENCES account(person_id),
 expires_at TEXT NOT NULL,
 revoked_at TEXT
);
CREATE TRIGGER revoke_person_sessions AFTER UPDATE OF active ON person
WHEN NEW.active=0 AND OLD.active=1
BEGIN UPDATE session SET revoked_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
WHERE person_id=NEW.id AND revoked_at IS NULL; END;
CREATE TABLE milestone (
 id INTEGER PRIMARY KEY,
 household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
 name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 160),
 category TEXT NOT NULL CHECK(category IN('Identité','Logement','Véhicule','Santé','Argent et assurances','Travail et formation','Impôts')),
 holder_id INTEGER NOT NULL REFERENCES person(id),
 responsible_id INTEGER REFERENCES person(id),
 location TEXT NOT NULL DEFAULT '' CHECK(length(location)<=250),
 amount_cents INTEGER CHECK(amount_cents IS NULL OR (typeof(amount_cents)='integer' AND amount_cents>=0)),
 due_date TEXT CHECK(due_date IS NULL OR (length(due_date)=10 AND due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
 notice_days INTEGER NOT NULL DEFAULT 0 CHECK(typeof(notice_days)='integer' AND notice_days BETWEEN 0 AND 3650),
 note TEXT NOT NULL DEFAULT '' CHECK(length(note)<=2000),
 archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK(responsible_id IS NULL OR responsible_id<>holder_id)
);
CREATE TRIGGER milestone_no_delete BEFORE DELETE ON milestone
BEGIN SELECT RAISE(ABORT,'archive milestone instead'); END;
CREATE TABLE decision (
 id INTEGER PRIMARY KEY,
 milestone_id INTEGER NOT NULL REFERENCES milestone(id),
 author_id INTEGER NOT NULL REFERENCES person(id),
 choice TEXT NOT NULL DEFAULT '' CHECK(length(choice)<=1000),
 options_json TEXT NOT NULL DEFAULT '["Ne rien faire"]' CHECK(json_valid(options_json) AND json_type(options_json)='array'),
 expected TEXT NOT NULL DEFAULT '' CHECK(length(expected)<=2000),
 reconsider_if TEXT NOT NULL DEFAULT '' CHECK(length(reconsider_if)<=2000),
 rule_json TEXT CHECK(rule_json IS NULL OR (json_valid(rule_json) AND json_type(rule_json)='object')),
 created_at TEXT NOT NULL,
 sealed_at TEXT
);
CREATE TRIGGER decision_fixed_link BEFORE UPDATE ON decision
WHEN NEW.milestone_id<>OLD.milestone_id OR NEW.author_id<>OLD.author_id OR NEW.created_at<>OLD.created_at
BEGIN SELECT RAISE(ABORT,'decision origin immutable'); END;
CREATE TRIGGER decision_sealed_immutable BEFORE UPDATE ON decision
WHEN OLD.sealed_at IS NOT NULL
BEGIN SELECT RAISE(ABORT,'sealed decision immutable'); END;
CREATE TRIGGER decision_no_delete BEFORE DELETE ON decision
BEGIN SELECT RAISE(ABORT,'decision retained'); END;
CREATE TRIGGER decision_insert_draft BEFORE INSERT ON decision
WHEN NEW.sealed_at IS NOT NULL
BEGIN SELECT RAISE(ABORT,'create draft before sealing'); END;
CREATE TRIGGER decision_seal_valid BEFORE UPDATE OF sealed_at ON decision
WHEN NEW.sealed_at IS NOT NULL AND (
 length(trim(NEW.choice))=0 OR length(trim(NEW.expected))=0 OR length(trim(NEW.reconsider_if))=0
 OR json_array_length(NEW.options_json) NOT BETWEEN 1 AND 20
 OR (SELECT count(*) FROM json_each(NEW.options_json) WHERE type='text' AND value='Ne rien faire')<>1
 OR EXISTS(SELECT 1 FROM json_each(NEW.options_json) WHERE type<>'text' OR length(trim(value))=0)
)
BEGIN SELECT RAISE(ABORT,'incomplete decision'); END;
CREATE TABLE decision_result (
 decision_id INTEGER PRIMARY KEY REFERENCES decision(id),
 author_id INTEGER NOT NULL REFERENCES person(id),
 body TEXT NOT NULL CHECK(length(trim(body)) BETWEEN 1 AND 4000),
 created_at TEXT NOT NULL
);
CREATE TRIGGER result_requires_seal BEFORE INSERT ON decision_result
WHEN (SELECT sealed_at FROM decision WHERE id=NEW.decision_id) IS NULL
BEGIN SELECT RAISE(ABORT,'result requires sealed decision'); END;
CREATE TRIGGER result_no_update BEFORE UPDATE ON decision_result
BEGIN SELECT RAISE(ABORT,'result immutable'); END;
CREATE TRIGGER result_no_delete BEFORE DELETE ON decision_result
BEGIN SELECT RAISE(ABORT,'result retained'); END;
CREATE TABLE stored_file (
 id INTEGER PRIMARY KEY,
 milestone_id INTEGER NOT NULL UNIQUE REFERENCES milestone(id),
 original_name TEXT NOT NULL,
 storage_key TEXT NOT NULL UNIQUE CHECK(length(storage_key)=64 AND storage_key NOT GLOB '*[^a-f0-9]*'),
 mime_type TEXT NOT NULL CHECK(mime_type IN('application/pdf','image/jpeg','image/png')),
 size_bytes INTEGER NOT NULL CHECK(size_bytes BETWEEN 1 AND 20971520),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^a-f0-9]*'),
 uploaded_by INTEGER NOT NULL REFERENCES person(id),
 created_at TEXT NOT NULL
);
CREATE TABLE decision_access (
 decision_id INTEGER NOT NULL REFERENCES decision(id),
 person_id INTEGER NOT NULL REFERENCES person(id),
 granted_by INTEGER NOT NULL REFERENCES person(id),
 granted_at TEXT NOT NULL,
 PRIMARY KEY(decision_id, person_id)
);
CREATE TABLE file_access (
 file_id INTEGER NOT NULL REFERENCES stored_file(id) ON DELETE CASCADE,
 person_id INTEGER NOT NULL REFERENCES person(id),
 granted_by INTEGER NOT NULL REFERENCES person(id),
 granted_at TEXT NOT NULL,
 PRIMARY KEY(file_id, person_id)
);
CREATE INDEX milestone_due ON milestone(archived,due_date);
CREATE INDEX decision_milestone ON decision(milestone_id,created_at);
CREATE INDEX decision_access_person ON decision_access(person_id);
CREATE INDEX file_access_person ON file_access(person_id);
CREATE VIEW index_projection AS
 SELECT m.*, EXISTS(SELECT 1 FROM stored_file f WHERE f.milestone_id=m.id) AS has_file
 FROM milestone m;
PRAGMA user_version = 1;
COMMIT;
