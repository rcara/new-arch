# Architecture — New Arch V2

## Confirmé

- **Monolithe modulaire** Flask dans `app/`.
- **Persistance** SQLite `data/metadata.sqlite` + fichiers `vault/objects/`.
- **Migrations** SQL versionnées (`PRAGMA user_version`), non destructives.
- **Présentation** Jinja + CSS ; pas de SPA obligatoire en V2.
- **API** JSON sous `/api` en parallèle des pages HTML.
- **Processus** Waitress loopback ; `FOYER_HOME`, `FOYER_PORT`.

## Organisation cible du code

```
app/
  routes/          # HTTP (pages + api) — mince
  services/        # règles métier par capacité
  domain/          # (futur) types partagés / contrats
  db.py            # connexion, migrations, write_tx
  security.py http.py validate.py present.py
```

Imports contrôlés : les routes appellent les services ; un service n’écrit pas dans les tables d’un autre module sans passer par son API service ou le contrat `object_link`.

## Modules runtime

`module_setting` active/masque les entrées de navigation. Modules désactivés : routes API renvoient 404 (pas de fuite d’existence via messages riches).

## Liens cross-module

Table `object_link` : `{source_type, source_id, target_type, target_id, relation_type}`.  
À la création : existence des deux objets dans le foyer + droits de l’acteur sur les deux.  
À la lecture : filtrage par ACL ; jamais de contournement via la table de liens.

## Hypothèses (non confirmées)

- H1 : multi-foyer runtime (`household_membership`, session login+persona, `user_version=7`).
- H2 : React/Vite pourra s’ajouter plus tard sans casser l’API JSON.
- H3 : PostgreSQL non requis tant que WAL + backup restent cohérents.
