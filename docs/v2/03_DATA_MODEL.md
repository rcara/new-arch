# Modèle de données V2

## Hérité (V1, inchangé structurellement)

`household`, `person`, `account`, `session`, `milestone`, `decision`, `decision_result`, `stored_file`, `decision_access`, `file_access` — voir `migrations/001_schema.sql` + `002_concurrency.sql`.

## Ajouts migration 003 (`user_version=3`)

### `module_setting`

- PK `(household_id, module_key)`
- `enabled` 0/1
- Clés : `accueil`, `foyer`, `finances`, `inventaire`, `calendrier`, `organisation`, `coffre`, `decisions`, `mediatheque`, `reperes`, `recherche`, `parametres`

Par défaut au seed : finances/inventaire/mediatheque **désactivés** ; le reste activé.

### `object_link`

Liens typés cross-module. Soft-archive via `archived`. Unique sur le quintuplet logique.

Types source/cible autorisés V2B : `milestone`, `decision`, `stored_file`, `person`, `task`, `calendar_event`.

### `task`

Organisation : titre, notes, statut (`open`/`done`/`cancelled`), priorité, assigné, échéance date civile, récurrence (`none`/`daily`/`weekly`/`monthly`/`yearly`), `public_id` UUID, soft-archive.

### `calendar_event`

Événement : titre, notes, `all_day`, `start_date`/`end_date` (dates civiles) ou `start_at`/`end_at` (UTC ISO), `timezone`, responsable, récurrence, `public_id` UUID.

## Conventions

- `household_id` sur toute ressource foyer.
- Horodatages stockés UTC ISO `…Z`.
- Affichage local via fuseau foyer.
- Pas de float monétaire : INTEGER `amount_minor` + `currency` ISO 4217 (CHF/EUR).
- Suppression douce / archivage quand pertinent (pas de DELETE physique sur décisions V1).

## Ajouts migration 004 (`user_version=4`)

### `finance_ledger_account`
Comptes de suivi (checking/cash/savings/credit/other), devise CHF|EUR, propriétaire optionnel.

### `finance_category` / `finance_income_share`
Catégories expense|income ; revenus déclarés pour prorata.

### `finance_transaction` / `finance_split`
Kinds : `expense`, `income`, `transfer`, `reimbursement`. Montants en unités mineures. Splits `equal|percent|fixed|income_prorata` avec somme exacte. Les remboursements ne comptent pas dans les budgets.

### `finance_budget`
Budgets mensuels/annuels par catégorie et devise.

## Ajouts migration 005 (`user_version=5`)

### `inventory_place` / `inventory_item` / `inventory_item_owner`
Lieux et biens (état, série, prix/valeur en unités mineures, visibilité, lien optionnel transaction/facture).

### `inventory_warranty` / `inventory_maintenance` / `inventory_history`
Garanties (échéance calendrier optionnelle), interventions, historique de cession/état.
