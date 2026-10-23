-- Retour arrière manuel de 009_sejour.sql (jamais exécuté par l'application).
-- À lancer seulement application arrêtée, après une sauvegarde (`python cli.py backup`) :
--   sqlite3 data/metadata.sqlite < migrations/rollback/009_sejour_down.sql
-- Effet : retire les séjours, leurs participants, l'enveloppe et les rattachements.
-- Les transactions financières restent dans Finances.
BEGIN;
DROP TRIGGER IF EXISTS sejour_expense_no_delete;
DROP INDEX IF EXISTS sejour_expense_one_trip;
DROP INDEX IF EXISTS sejour_expense_active;
DROP INDEX IF EXISTS sejour_expense_sejour;
DROP TABLE IF EXISTS sejour_expense;
DROP TABLE IF EXISTS sejour_envelope_line;
DROP TABLE IF EXISTS sejour_participant;
DROP TRIGGER IF EXISTS sejour_no_delete;
DROP INDEX IF EXISTS sejour_range;
DROP TABLE IF EXISTS sejour;
PRAGMA user_version = 8;
COMMIT;
