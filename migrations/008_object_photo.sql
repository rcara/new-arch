-- Photos de biens (inventaire) et affiches d'œuvres (médiathèque).
-- Migration additive : une nouvelle table, aucune table existante modifiée ni réécrite.
-- Retour arrière : voir migrations/rollback/008_object_photo_down.sql.
BEGIN;

CREATE TABLE object_photo (
  id INTEGER PRIMARY KEY,
  household_id INTEGER NOT NULL REFERENCES household(id),
  object_type TEXT NOT NULL CHECK(object_type IN('inventory_item','media_work')),
  object_id INTEGER NOT NULL CHECK(typeof(object_id)='integer' AND object_id>0),
  storage_key TEXT NOT NULL UNIQUE CHECK(length(storage_key)=64 AND storage_key NOT GLOB '*[^a-f0-9]*'),
  mime_type TEXT NOT NULL CHECK(mime_type IN('image/jpeg','image/png','image/webp')),
  size_bytes INTEGER NOT NULL CHECK(size_bytes BETWEEN 1 AND 10485760),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^a-f0-9]*'),
  uploaded_by INTEGER NOT NULL REFERENCES person(id),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
  created_at TEXT NOT NULL
);
CREATE INDEX object_photo_hh ON object_photo(household_id, object_type, object_id, archived);
CREATE UNIQUE INDEX object_photo_one_active ON object_photo(object_type, object_id) WHERE archived=0;
CREATE TRIGGER object_photo_no_delete BEFORE DELETE ON object_photo
BEGIN SELECT RAISE(ABORT,'archive photo instead'); END;

PRAGMA user_version = 8;
COMMIT;
