# Plan de tests V2

## Unitaires
- Statuts d’échéance repères (existant).
- Récurrence tâche : prochaine occurrence après completion.
- Validation liens (types, unicité, ACL).
- Recherche : absence de fuite (décision/fichier sans droit).

## Intégration
- Migration `002 → 003` sur DB V1 copiée (`user_version`, tables présentes, seed modules).
- Auth + CSRF inchangés.
- CRUD tâches/événements/liens via API et pages.
- Backup/restore reste cohérent après 003.

## E2E (manuel / futur)
Parcours Accueil → tâche → événement → recherche ; mobile 375 px ; pas d’erreur console (UI sans JS aujourd’hui).

## Sécurité
Non-autorisé : pas de lecture décision/fichier via lien ou search. Index/home sans noms de fichiers ni textes de décision.

## Exécution
`pytest` dans le dépôt ; résultats reportés sans invention.
