-- Retour arrière manuel de 008_object_photo.sql (jamais exécuté par l'application).
-- À lancer seulement application arrêtée, après une sauvegarde (`python cli.py backup`) :
--   sqlite3 data/metadata.sqlite < migrations/rollback/008_object_photo_down.sql
-- Effet : retire uniquement la table des photos ; biens, œuvres et toutes les autres données restent intacts.
-- Les fichiers photo restent dans media/objects (orphelins) ; on peut les conserver ou les supprimer
-- d'après la liste `SELECT storage_key FROM object_photo` relevée avant ce script.
BEGIN;
DROP TRIGGER IF EXISTS object_photo_no_delete;
DROP INDEX IF EXISTS object_photo_one_active;
DROP INDEX IF EXISTS object_photo_hh;
DROP TABLE IF EXISTS object_photo;
PRAGMA user_version = 7;
COMMIT;
