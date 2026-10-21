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

## Sprint 3

| Vérification | Résultat |
|---|---|
| `pytest` complet | 106 passés |
| `tests/test_ux_quick_create.py` (10 tests) | menu « + Ajouter » → `#ajout-tache` / `#ajout-evenement`, autres entrées avec `?next=` ; panneaux POST vers les bonnes routes avec CSRF, `next` et date du jour ; tâche rapide → 302 vers la page d'origine, assignée à moi ; sans « M'assigner » → partagée ; événement rapide = journée entière, formulaire complet case décochée = non ; dépense EUR sans compte → compte EUR, montant 1240 centimes ; dépense sans catégorie → 400 + message ; `next` malveillant (`//evil`, `https://evil`, `javascript:`) ignoré ; tâche liée depuis un événement et depuis un bien (affichée sur la fiche) ; compte secondaire + bien privé → 404 et aucune tâche ; erreur de validation : saisie et `next` conservés, `aria-invalid` |
| Visuel avant | `s3-avant-{vide,demo}-{organisation-nouvelle,calendrier-nouveau,finances-depense,inventaire-nouveau}-{desktop,mobile}.png` |
| Visuel après | mêmes noms en `s3-apres-…` ; `s3-apres-demo-menu-ajouter-*`, `s3-apres-demo-panneau-{tache,evenement}-{desktop,mobile}`, `s3-apres-demo-retour-confirmation-desktop`, `s3-apres-demo-tache-liee-formulaire-desktop`, `s3-apres-demo-evenement-taches-liees-{desktop,mobile}`, `s3-apres-demo-depense-options-ouvertes-{desktop,mobile}` |

Limites connues : sans JS, le menu « + Ajouter » reste ouvert derrière le panneau et le focus n'est pas placé
dans le champ Titre ; le panneau se ferme par « Fermer », le fond, ou après envoi. Sur les captures pleine page,
l'en-tête et la barre mobile fixes apparaissent au milieu (artefact de capture).

## Sprint 4

| Vérification | Résultat |
|---|---|
| `pytest` complet | 128 passés |
| `tests/test_ux_modules.py` (22 tests) | Agenda : événement 3 jours présent sur chaque case et une seule fois en liste, hors mois exclu, case du jour marquée, semaine et mois suivants, liens Précédent / Suivant ; filtre membre (responsable) et titre, échéance de repère affichée puis masquée quand l'index est retiré au compte secondaire. À faire : ordre En retard → Aujourd'hui → À venir, récurrence affichée, filtre « Pour moi », ajout rapide, terminer puis rouvrir, rouvrir sans CSRF refusé. Finances : 5 vues + vue inconnue en 200, CHF et EUR jamais mélangés, transaction privée invisible pour le compte secondaire (tableau et vue d'ensemble), total du mois : écart exact de 1000,00 CHF entre principal et secondaire (dépense privée), aucun `style=` inline (CSP), sidebar alignée sur l'onglet. Inventaire : galerie, liste, filtres catégorie et lieu, aucun résultat ; bien privé et sa catégorie invisibles pour le compte secondaire. Coffre : dépôt, filtres type / texte, compte secondaire sans accès : ni fichier, ni repère, ni formulaire de dépôt, recherche sans fuite. Médiathèque : 6 onglets en 200. Décisions : cycle affiché, sélection du repère → formulaire existant, compte secondaire sans formulaire ; « + Ajouter » → `/decisions#nouvelle-decision`. États vides (9 pages, foyer vide) : titre explicite + action principale |
| Visuel avant | `s4-avant-{vide,demo}-{calendrier,organisation,finances,inventaire,coffre,mediatheque,decisions}-{desktop,mobile}.png` |
| Visuel après | `s4-apres-{vide,demo}-…` mêmes pages + `calendrier-vue-semaine`, `calendrier-vue-liste`, `finances-vue-transactions`, `finances-vue-budgets`, `inventaire-vue-liste` (desktop, mobile) ; tablette : `calendrier`, `organisation`, `finances`, `inventaire` |

Données de capture : foyer démo enrichi (3 lieux, 5 biens, 5 œuvres, 1 bail au coffre, 1 décision brouillon)
via l'API locale. Quelques tâches en double proviennent des captures du Sprint 3.

Limites connues : événements récurrents non développés en occurrences (D6, résolu en V2.2) ; pas d'images de biens ni d'œuvres
(D7) ; sur mobile, la grille du mois est remplacée par la liste des jours occupés (et le jour même).

## Sprint 5

| Vérification | Résultat |
|---|---|
| `pytest` complet | 136 passés |
| `tests/test_ux_quality.py` (8 tests) | 403 compte secondaire sur `/parametres/avance`, 404, 500 simulée (message générique, aucune trace), 404 invité → connexion ; recherche : invite, trop court (`aria-invalid`), aucun résultat, groupes Tâches / Événements ; bien privé invisible au secondaire, « Personnes » réservé au principal ; Calendrier désactivé → aucun événement ni lien `/calendrier` dans les résultats ; 21 pages sans `<script>`, `style=`, `on*=`, avec CSP `script-src 'none'`, un seul `h1`, `main#contenu`, `lang="fr"` |
| axe-core 4.x (WCAG 2.1 A/AA) | Avant : 1 règle (`color-contrast`, ~180 nœuds clair + sombre). Après : **0 violation** sur 20 pages × clair / sombre × 1440 px / 390 px, foyer démo et foyer vide ; connexion et 404 invité également à 0 |
| Clavier (Playwright) | Tab 1 = « Aller au contenu », puis marque, navigation ; Entrée sur le lien d'évitement → premier lien du contenu ; anneau de focus 2 px sur chaque arrêt ; mobile : sidebar masquée hors du parcours ; `/organisation#ajout-tache` : Tab → « Fermer le panneau » → champ Titre |
| Visuel avant / après | `s5-{avant,apres}-demo-recherche-{light,dark}-{desktop,mobile}`, `-recherche-trop-court-light-desktop`, `s5-…-vide-recherche-aucun-light-{desktop,mobile}`, `-erreur-404-{light,dark}-{desktop,mobile}`, `-erreur-403-light-{desktop,mobile}` (compte secondaire), `-accueil-{light,dark}-{desktop,tablet,mobile}`, `-finances-dark-{desktop,mobile}`, `-organisation-dark-{desktop,tablet}`, `-calendrier-{light,dark}-{desktop,tablet}`, `-panneau-tache-dark-mobile` (28 + 28 fichiers) |

Limites connues : le thème est une préférence enregistrée (cookie, Paramètres › Thème) et ne suit pas
`prefers-color-scheme` ; axe ne couvre pas tout (ordre de lecture, pertinence des libellés) — vérification
manuelle faite sur la navigation, les formulaires rapides et les pages d'erreur ; l'interrupteur de modules (D3)
n'est pas livré.

