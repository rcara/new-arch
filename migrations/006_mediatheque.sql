BEGIN;

CREATE TABLE media_work (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  kind TEXT NOT NULL CHECK(kind IN('film','series','book','music','game')),
  title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
  creator TEXT NOT NULL DEFAULT '' CHECK(length(creator)<=200),
  year INTEGER CHECK(year IS NULL OR (typeof(year)='integer' AND year BETWEEN 1000 AND 2100)),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=4000),
  visibility TEXT NOT NULL DEFAULT 'household' CHECK(visibility IN('household','private')),
  created_by INTEGER NOT NULL REFERENCES person(id),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX media_work_hh ON media_work(household_id, kind, archived);
CREATE TRIGGER media_work_no_delete BEFORE DELETE ON media_work
BEGIN SELECT RAISE(ABORT,'archive media work instead'); END;

CREATE TABLE media_progress (
  work_id INTEGER NOT NULL REFERENCES media_work(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  status TEXT NOT NULL DEFAULT 'wishlist' CHECK(status IN('wishlist','in_progress','done','dropped','favorite')),
  progress_label TEXT NOT NULL DEFAULT '' CHECK(length(progress_label)<=120),
  progress_percent INTEGER CHECK(progress_percent IS NULL OR (typeof(progress_percent)='integer' AND progress_percent BETWEEN 0 AND 100)),
  rating INTEGER CHECK(rating IS NULL OR (typeof(rating)='integer' AND rating BETWEEN 1 AND 5)),
  notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=2000),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(work_id, person_id)
);

CREATE TABLE media_list (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
  list_kind TEXT NOT NULL DEFAULT 'wishlist' CHECK(list_kind IN('wishlist','collection','custom')),
  owner_id INTEGER NOT NULL REFERENCES person(id),
  visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN('household','private')),
  created_at TEXT NOT NULL
);

CREATE TABLE media_list_entry (
  list_id INTEGER NOT NULL REFERENCES media_list(id),
  work_id INTEGER NOT NULL REFERENCES media_work(id),
  added_at TEXT NOT NULL,
  PRIMARY KEY(list_id, work_id)
);

CREATE TABLE media_asset (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL DEFAULT 1 REFERENCES household(id),
  public_id TEXT NOT NULL UNIQUE CHECK(length(public_id)=36),
  title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
  asset_kind TEXT NOT NULL CHECK(asset_kind IN('photo','video','audio','other')),
  collection TEXT NOT NULL DEFAULT '' CHECK(length(collection)<=120),
  storage_key TEXT NOT NULL UNIQUE CHECK(length(storage_key)=64 AND storage_key NOT GLOB '*[^a-f0-9]*'),
  mime_type TEXT NOT NULL CHECK(mime_type IN(
    'image/jpeg','image/png','image/webp','audio/mpeg','audio/ogg','video/mp4','application/pdf'
  )),
  size_bytes INTEGER NOT NULL CHECK(size_bytes BETWEEN 1 AND 20971520),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^a-f0-9]*'),
  original_name TEXT NOT NULL CHECK(length(original_name) BETWEEN 1 AND 180),
  visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN('household','private')),
  uploaded_by INTEGER NOT NULL REFERENCES person(id),
  work_id INTEGER REFERENCES media_work(id),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL
);
CREATE INDEX media_asset_hh ON media_asset(household_id, asset_kind, archived);
CREATE TRIGGER media_asset_no_delete BEFORE DELETE ON media_asset
BEGIN SELECT RAISE(ABORT,'archive media asset instead'); END;

CREATE TABLE media_asset_access (
  asset_id INTEGER NOT NULL REFERENCES media_asset(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES person(id),
  granted_by INTEGER NOT NULL REFERENCES person(id),
  granted_at TEXT NOT NULL,
  PRIMARY KEY(asset_id, person_id)
);

UPDATE module_setting SET enabled=1 WHERE module_key='mediatheque';
INSERT OR IGNORE INTO module_setting(household_id, module_key, enabled)
SELECT 1, 'mediatheque', 1 WHERE EXISTS(SELECT 1 FROM household WHERE id=1);

PRAGMA user_version = 6;
COMMIT;
