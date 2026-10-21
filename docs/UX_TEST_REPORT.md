# UX Test Report — New Arch V2.1

Environnement : Python 3.12, `pytest`, Chrome headless (Playwright, outil hors dépôt) contre `launcher.py` local.
Foyers : **vide** (initialisé) et **démo** (`python cli.py seed-demo`, données fictives).

## Sprint 0

| Vérification | Avant (`main`) | Après |
|---|---|---|
| `pytest` complet | 68 passés | 74 passés |
| `tests/test_ux_stability.py` | 6 échecs | 6 passés |
| `GET /calendrier` (vide / démo) | 500 « Opération impossible » | 200 |
| `GET /organisation` (vide / démo) | 500 | 200 |
| `GET /recherche?q=…` | 500 | 200 (résultats / « Aucun résultat ») |
| Crawl pages liées, foyer vide | 26 pages, 2 en 500 | 26 pages, 0 erreur |
| Crawl pages liées, foyer démo | 38 pages, 2 en 500 (les pages détail événement/tâche étaient inatteignables) | 42 pages, 0 erreur |
| Événement : créer → lister → modifier | impossible (liste en 500) | OK (test) |
| Tâche : créer → lister → terminer → « Faites » | impossible | OK (test) |

Captures : store projet `media/ux-v2/s0-avant-*.png`, `s0-apres-*.png`.

Anomalies restantes : voir `UX_AUDIT_V2.md` §5 (A1–A4) et décisions D1–D5 dans `UX_IMPLEMENTATION_PLAN.md`.
