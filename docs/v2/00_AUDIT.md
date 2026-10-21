# Audit New Arch V2 — dépôt ouvert

**Date :** 2026-10-21  
**ZIP V1 `Foyer_Local_V1_Complet(1).zip` :** **absent** du workspace. Aucune prétention de l’avoir lu. La comparaison V1 s’appuie sur le code livré, `GUIDE.md`, `MATRICE.md`, `RAPPORT-TESTS.md` et le schéma SQL versionné.

## Synthèse diagnostic (15 points)

1. **Stack réelle :** Flask 3.1 + Waitress + Jinja2 + SQLite (WAL) + Argon2id — **pas** FastAPI/React/Vite.
2. **Décision stack V2 :** conserver Flask/Jinja/SQLite ; ne pas réécrire pour « conformité » théorique.
3. **Périmètre V1 implémenté :** foyer unique, personnes/comptes, repères (Index), décisions scellées, coffre PDF/JPEG/PNG, accès granulaires, sauvegarde/restauration, API JSON miroir.
4. **Couches V1 :** Aujourd’hui / Repères / Décision / Coffre — à transformer en **capacités** d’un Home OS, pas en produit entier.
5. **Schéma :** `migrations/001_schema.sql` (empreinte figée) + `002_concurrency.sql` (`user_version=2`).
6. **IDs :** entiers SQLite auto-incrémentés ; pas d’UUID aujourd’hui.
7. **Auth :** cookie session + CSRF ; Person ≠ Account (titulaire sans compte possible) ; principal unique immuable.
8. **Confidentialité :** droits indépendants Index / décision / fichier ; parenté sans droit ; API Index sans nom de fichier ni texte de décision.
9. **Chiffrement au repos :** **absent** (documenté dans GUIDE) — ne pas prétendre le contraire.
10. **Modules V2 absents :** finances, inventaire, calendrier générique, tâches/organisation, médiathèque, liens cross-module typés, recherche transversale UI, light mode.
11. **Timezone défaut code :** `Europe/Berlin` ; cible produit V2 : `Europe/Zurich` (configurable) sans migration destructive des foyers existants.
12. **UI :** français, dark Ars Codicis (Roboto), nav limitée aux écrans V1.
13. **Tests :** ~23 pytest verts (rapport 20 oct 2026) — schéma, droits, scellement, coffre, backup, sécurité locale.
14. **Déploiement :** loopback 127.0.0.1:8765 ; option Tunnel Cloudflare documentée ; local-first.
15. **Dette :** monolithe plat `app/services/*` sans frontières de modules ; `household_id` présent mais foyer figé `id=1` ; pas de table de liens génériques.

## Existant réel (à préserver)

| Domaine | Preuve code |
|---|---|
| Bootstrap foyer + principal | `services/auth.py`, routes pages/API |
| Sessions + rate limit | `security.py`, `http.py` |
| Repères + statuts J/30/90 | `services/milestones.py` |
| Décisions brouillon/scellement/résultat | `services/decisions.py` + triggers SQL |
| Coffre + ACL | `services/vault.py` |
| Personnes / accès | `services/people.py` |
| Backup/restore | `services/backup.py`, `cli.py` |

## Manquant vs vision Home OS

Finances (montants exacts, splits, CHF/EUR), inventaire, calendrier/événements hors repères, organisation/tâches, médiathèque, recherche globale, modèle de liens, modules activables, UUID publics, light mode, docs V2.

## Risques

| Risque | Mitigation |
|---|---|
| Réécriture stack | Interdit sans justification ; stack conservée |
| Migration destructive | `user_version` incrémental ; snapshot migrations ; pas de reset DB |
| Fuite via liens | Validation existence + ACL à la création/lecture |
| Fausse sécurité | Documenter clair-texte disque ; pas de « chiffrement » cosmétique |
| Régression V1 | Tests existants doivent rester verts ; pas supprimer écrans Repères/Décision/Coffre |

## Stratégie de migration

1. Docs V2 (cadrage).
2. Snapshot des migrations pré-V2 : `docs/v2/snapshots/`.
3. Migration `003` additive : modules, liens, tâches, événements, UUID publics.
4. Socle B : nav, accueil enrichi, tâches, échéances/événements, recherche, liens.
5. Tranches C→F selon roadmap ; backlog traçable.

## Décisions motivées (confirmées)

- **D01** Conserver Flask + SQLite + templates.
- **D02** ZIP V1 absent → pas de reconstruction fantôme des 14 docs.
- **D03** Repères restent ; calendrier V2 = événements + échéances dérivées des repères.
- **D04** UUID en `public_id` pour nouvelles entités ; PK entières conservées.
- **D05** Défaut timezone **nouveaux** foyers : `Europe/Zurich`.
