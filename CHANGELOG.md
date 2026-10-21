# Changelog

## [0.2.0-v2b] — 2026-10-21

### Ajouté
- Documentation architecture Home OS : `docs/v2/00_AUDIT.md` … `09_DECISION_LOG.md`
- Migration non destructive `003_v2_foundation.sql` (`user_version=3`) : modules, liens, tâches, événements
- Modules Organisation (tâches + récurrence), Calendrier (événements), Recherche, Paramètres, Accueil agrégé
- API : `/api/home`, `/api/tasks`, `/api/events`, `/api/links`, `/api/search`, `/api/modules`
- Snapshot pré-migration : `backups/snapshots/`
- Tests socle V2 (`tests/test_v2_foundation.py`)

### Modifié
- Navigation V2 (modules masqués si désactivés) ; Accueil remplace le libellé « Aujourd'hui »
- Fuseau par défaut des **nouveaux** foyers : `Europe/Zurich`
- Restauration de sauvegardes : versions de schéma 2 et 3 acceptées

### Conservé
- Toutes les capacités V1 (repères, décisions scellées, coffre ACL, personnes, backup)
- Empreinte figée de `migrations/001_schema.sql`

### Non livré (backlog)
- Finances, inventaire, médiathèque, light mode, chiffrement au repos
