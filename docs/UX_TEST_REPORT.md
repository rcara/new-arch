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

## Sprint 1

| Vérification | Résultat |
|---|---|
| `pytest` complet | 89 passés |
| `tests/test_ux_navigation.py` (15 tests) | passés : 7 groupes au lieu de 14 entrées, chaque lien sidebar + « + Ajouter » répond 200 depuis 7 pages, état actif groupe/sous-entrée, compte secondaire sans entrées admin (et `/parametres/avance` → 403), modules désactivés masqués (+ 404 serveur), alias 302, anciennes routes 200, déconnexion POST + CSRF, aucune balise `<script>` et CSP inchangée |
| Visuel desktop 1440 / tablette 820 / mobile 390 | `s1-apres-*` : sidebar, tiroir tablette ouvert, menu « + Ajouter » ouvert, barre mobile |
| Thème sombre | `s1-apres-demo-finances-sombre-desktop.png` |

Limites connues : les menus `<details>` ne se ferment pas au clic extérieur (pas de JS) — un second clic sur le
bouton ou la navigation les ferme. Le tiroir se ferme via « Fermer » ou le fond.

## Sprint 2

| Vérification | Résultat |
|---|---|
| `pytest` complet | 96 passés |
| `tests/test_ux_today.py` (7 tests) | foyer vide guidé (onboarding 1/5, liens d'action, états vides) ; foyer rempli : événement à J+3 affiché / à J+40 exclu, tâche en retard + prioritaire, tâche d'un autre membre exclue de « Mes tâches », dépenses CHF 120,50 et EUR 30,00 séparées, dépense du mois précédent exclue, budget « Reste 79,50 » ; Terminer en 1 clic (POST → 302 `/`, statut `done`) ; refus sans CSRF ; `next=//evil…` → `/` ; onboarding masqué puis réaffiché ; compte secondaire : dépense privée du principal invisible |
| Visuel | `s2-apres-{vide,demo}-accueil-{desktop,tablet,mobile}.png`, `s2-apres-demo-accueil-sombre-desktop.png` |

Données de capture : foyer démo + éléments datés d'octobre 2026 ajoutés via l'API locale (le seed démo est daté
2027). Aucun impact sur le dépôt.
