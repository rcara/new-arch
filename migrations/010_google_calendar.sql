-- Google Calendar (foyer) : OAuth compte rcara.home@gmail.com, miroir « New Arch »,
-- cartes d'événements et cache overlay lecture seule des autres calendriers.
-- Migration additive : tables nouvelles uniquement.
-- Retour arrière : migrations/rollback/010_google_calendar_down.sql.
BEGIN;

CREATE TABLE google_oauth_link (
  household_id INTEGER PRIMARY KEY REFERENCES household(id),
  email TEXT NOT NULL DEFAULT '' CHECK(length(email)<=320),
  refresh_token_enc BLOB,
  access_token_enc BLOB,
  access_expires_at TEXT,
  mirror_calendar_id TEXT CHECK(mirror_calendar_id IS NULL OR length(trim(mirror_calendar_id)) BETWEEN 1 AND 1024),
  linked_by INTEGER REFERENCES person(id),
  linked_at TEXT,
  last_sync_at TEXT,
  last_sync_error TEXT NOT NULL DEFAULT '' CHECK(length(last_sync_error)<=2000),
  disconnected_at TEXT
);

CREATE TABLE google_oauth_pending (
  state_hash TEXT PRIMARY KEY CHECK(length(state_hash)=64 AND state_hash NOT GLOB '*[^a-f0-9]*'),
  household_id INTEGER NOT NULL REFERENCES household(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX google_oauth_pending_expires ON google_oauth_pending(expires_at);

CREATE TABLE google_event_map (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL REFERENCES household(id),
  calendar_event_id INTEGER NOT NULL REFERENCES calendar_event(id),
  google_event_id TEXT NOT NULL CHECK(length(trim(google_event_id)) BETWEEN 1 AND 1024),
  etag TEXT NOT NULL DEFAULT '' CHECK(length(etag)<=512),
  google_updated TEXT NOT NULL DEFAULT '' CHECK(length(google_updated)<=64),
  last_synced_at TEXT NOT NULL DEFAULT '' CHECK(length(last_synced_at)<=64),
  sync_skip INTEGER NOT NULL DEFAULT 0 CHECK(sync_skip IN(0,1)),
  UNIQUE(household_id, calendar_event_id),
  UNIQUE(household_id, google_event_id)
);
CREATE INDEX google_event_map_hh ON google_event_map(household_id);

CREATE TABLE google_overlay_event (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL REFERENCES household(id),
  google_calendar_id TEXT NOT NULL CHECK(length(trim(google_calendar_id)) BETWEEN 1 AND 1024),
  calendar_name TEXT NOT NULL CHECK(length(trim(calendar_name)) BETWEEN 1 AND 200),
  google_event_id TEXT NOT NULL CHECK(length(trim(google_event_id)) BETWEEN 1 AND 1024),
  title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
  start_date TEXT NOT NULL CHECK(length(start_date)=10 AND start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  end_date TEXT NOT NULL CHECK(length(end_date)=10 AND end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  all_day INTEGER NOT NULL DEFAULT 1 CHECK(all_day IN(0,1)),
  refreshed_at TEXT NOT NULL,
  CHECK(end_date >= start_date),
  UNIQUE(household_id, google_calendar_id, google_event_id)
);
CREATE INDEX google_overlay_range ON google_overlay_event(household_id, start_date, end_date);

PRAGMA user_version = 10;
COMMIT;
