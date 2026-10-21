# Spécification produit — New Arch V2 (Home OS)

## Vision

Point d’entrée unique local-first pour gérer la vie quotidienne d’une personne, d’un couple ou d’une famille. Une donnée peut être reliée à plusieurs domaines sans duplication. Confidentialité par personne et par objet. Aucune API cloud obligatoire.

## Principes

- Local-first, monolithe modulaire, pas de microservices.
- Moindre privilège : partager le foyer ≠ partager documents/décisions/finances.
- Montants exacts (unités mineures / Decimal) — hors socle B, obligatoire dès finances.
- Fuseau explicite (défaut nouveaux foyers : Europe/Zurich).
- Démo et données réelles séparées (aucun faux chiffre en UI).

## Modules cibles

| # | Module | Statut socle B |
|---|---|---|
| 1 | Accueil | Enrichi (repères + tâches + événements réels) |
| 2 | Foyer & personnes | Préservé V1 + nav « Foyer » |
| 3 | Finances | Backlog C |
| 4 | Inventaire | Backlog D |
| 5 | Calendrier & échéances | Événements CRUD + échéances repères |
| 6 | Organisation | Tâches CRUD + récurrence simple |
| 7 | Coffre | Préservé V1 |
| 8 | Décisions | Préservé V1 (invariants scellement) |
| 9 | Médiathèque | Backlog E |
| 10 | Recherche / liens / audit / backup | Recherche + liens B ; backup V1 |

## Parcours prioritaires (socle B)

1. Créer une tâche récurrente et la cocher.
2. Créer un événement et le voir sur Accueil (30 jours).
3. Relier une tâche à un repère via lien typé.
4. Rechercher transversalement sans fuite de contenu privé.
5. Conserves V1 : sceller décision, déposer pièce, droits séparés.

## Hors périmètre immédiat

Paiements cloud, e-mail, streaming, conversion de devises implicite, multi-foyer runtime (schéma prêt via `household_id`).
