# Changelog

## [0.4.0-v2d] — 2026-10-21

### Ajouté
- Migration `005_inventory.sql` (`user_version=5`)
- Module Inventaire : lieux, biens, propriétaires, garanties, maintenance, historique
- Liens typés achat (`finance_transaction`) et facture (`stored_file`) ; échéance calendrier pour garanties
- UI `/inventaire`, API `/api/inventory/*`, recherche et accueil (garanties à venir)
- Tests `tests/test_inventory.py`

## [0.3.0-v2c] — 2026-10-21

### Ajouté
- Migration `004_finances.sql` (`user_version=4`)
- Module Finances activé : comptes, catégories, dépenses partagées, remboursements, budgets, soldes, CSV
- `app/money.py` : parsing sans float, splits à somme exacte
- API `/api/finance/*` et écrans `/finances`
- Tests `tests/test_finances.py` (arrondis, soldes, double comptage, devises, confidentialité)

### Conservé
- Socle V2B et capacités V1 ; aucune conversion de devise implicite

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
