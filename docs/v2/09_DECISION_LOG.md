# Journal de décisions V2

| ID | Décision | Statut | Motif |
|---|---|---|---|
| D01 | Garder Flask/Jinja/SQLite | Confirmé | Compatible dépôt ; pas de réécriture gratuite |
| D02 | ZIP V1 absent → audit code-only | Confirmé | Pas de faux documents lus |
| D03 | Migration additive 003 | Confirmé | Non-destructif ; `user_version=3` |
| D04 | UUID en `public_id`, PK int | Confirmé | Stabilité externe sans casser FK |
| D05 | Défaut TZ nouveaux foyers Europe/Zurich | Confirmé | Spec V2 ; foyers existants intacts |
| D06 | Modules finances/inventaire/média off par défaut | Confirmé | Masquer UI non livrée |
| D07 | Repères conservés comme capacité | Confirmé | Ne pas supprimer V1 |
| D08 | Pas de chiffrement cosmétique | Confirmé | Blobs AES-GCM OK ; SQLite volontairement clair |
| D09 | Charte New Arch officielle | Confirmé | Remplace Ars Codicis (PR branding) |
| D10 | Chiffrement blobs optionnel | Confirmé | `crypto.json` + FOYER_PASSPHRASE ; doc 10_ENCRYPTION |
| H1 | Multi-foyer runtime plus tard | Hypothèse | `household_id` prêt, UI mono-foyer |
| H2 | SPA éventuelle via `/api` | Hypothèse | Pas dans B |

## Backlog traçable

| ID | Priorité | Item | Critères d’acceptation |
|---|---|---|---|
| B-01 | P0 | Docs A | Fichiers 00–09 présents |
| B-02 | P0 | Migration 003 | DB V1 migrée ; tests verts |
| B-03 | P0 | Tâches | CRUD UI+API ; récurrence ; tests |
| B-04 | P0 | Événements | CRUD UI+API ; Accueil 30 j |
| B-05 | P0 | Liens | Création/lecture ACL |
| B-06 | P0 | Recherche | Filtrage permissions |
| B-07 | P0 | Nav modules | Masque désactivés |
| C-01 | P1 | Finances bout-en-bout | ✅ Splits exacts ; CHF/EUR ; confidentialité ; migration 004 |
| D-01 | P1 | Inventaire + liens facture | ✅ Migration 005 ; garanties → calendrier ; ACL privée |
| E-01 | P2 | Médiathèque simple | ✅ Catalogue ≠ fichiers ; migration 006 |
| F-01 | P2 | E2E + backup étendu | ✅ `test_solidification.py` ; backup media ; seed-demo ; WINDOWS.md |

### Déjà fait (V1)
Foyer, auth, repères, décisions scellées, coffre ACL, backup, tests R01–R24 (hors R02 partiel).

### Non fait (suite)
SQLCipher (base entière), multi-foyer runtime, SPA, sidebar compacte.
