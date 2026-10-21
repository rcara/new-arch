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
- Pas de float monétaire (prévu étape C : INTEGER cents + `currency` ISO 4217).
- Suppression douce / archivage quand pertinent (pas de DELETE physique sur décisions V1).
