# Rapport de tests — 21 octobre 2026 (New Arch V2 socle B)

Machine : Linux, Python 3.12.3, SQLite (système), Flask 3.1.3, Waitress 3.0.2, argon2-cffi.

## Automatisés

Commande exécutée :

```sh
.venv/bin/python -m pytest tests/ -q
```

Résultat : **38 tests, tous réussis**.

- Suite V1 inchangée (schéma 001 figé, droits, scellement, coffre, backup v2/v3, sécurité locale).
- Migration `002 → 003` sur DB V1 copiée (`test_migration_002_to_003_on_copied_v1`).
- Récurrence de tâches et accueil (`test_task_recurrence_and_home`).
- Événements + recherche (`test_event_and_search`).
- Liens ACL + absence de fuite décision pour second compte (`test_links_acl_and_search_privacy`).

## Non exécutés

- Recette navigateur Windows / largeur 375 px manuelle.
- Débranchement réseau physique.

## Limitations connues

- Pas de chiffrement au repos (inchangé).
- Finances / inventaire / médiathèque non implémentés (modules masqués).
- ZIP spécification V1 absent du workspace.
