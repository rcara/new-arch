-- Retour arrière manuel de 010_google_calendar.sql (jamais exécuté par l'application).
-- À lancer seulement application arrêtée, après une sauvegarde (`python cli.py backup`) :
--   sqlite3 data/metadata.sqlite < migrations/rollback/010_google_calendar_down.sql
-- Effet : retire le lien OAuth Google, les cartes d'événements et le cache overlay.
-- Les calendar_event du foyer restent intacts.
BEGIN;
DROP INDEX IF EXISTS google_overlay_range;
DROP TABLE IF EXISTS google_overlay_event;
DROP INDEX IF EXISTS google_event_map_hh;
DROP TABLE IF EXISTS google_event_map;
DROP INDEX IF EXISTS google_oauth_pending_expires;
DROP TABLE IF EXISTS google_oauth_pending;
DROP TABLE IF EXISTS google_oauth_link;
PRAGMA user_version = 9;
COMMIT;
