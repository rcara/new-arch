# UX Changelog — New Arch V2.1

## Sprint 2 — Accueil « Aujourd'hui »

**Ajouté**
- Page Aujourd'hui en grille (12 colonnes desktop, 2 tablette, 1 mobile) : bienvenue contextuelle (date, foyer,
  résumé réel « N rendez-vous · N tâches dont N en retard »), **Agenda** 14 jours (événements + échéances de
  repères, chronologique), **À faire** (mes tâches + tâches sans responsable, retard, priorité, récurrence,
  **Terminer en un clic**), **Finances du mois** (dépenses par devise CHF / EUR séparées, budgets du mois avec
  jauge et reste, soldes entre membres par devise), **Raccourcis** (mêmes droits que « + Ajouter »),
  garanties, médias en cours, **Ajouté récemment** (tâches, événements, transactions et biens visibles ; coffre et
  décisions exclus).
- Onboarding facultatif « Bien démarrer » (5 étapes calculées sur l'état réel, disparaît quand tout est fait),
  masquable, réaffichable depuis Paramètres (cookie `foyer_onboarding`, aucune donnée en base).
- `POST /organisation/<id>/terminer` (CSRF, `next` limité au même site) ; `POST /accueil/demarrage`.
- `finance.month_spending` (lecture seule) : somme des dépenses visibles du mois par devise — mêmes règles de
  visibilité que `_spent_in_period`, aucune règle de calcul existante modifiée.
- `home.dashboard` : clés `agenda`, `todo`, `finance_month`, `recent`, `onboarding` ajoutées ; clés existantes
  inchangées (`/api/home` compatible).

**Modifié** : `today.html` (réécrit), `settings.html` (guide de démarrage), `app.css` (grille, timeline, tâches,
stats, budgets, étapes), `app/http.py` (cookie + messages), `app/routes/pages.py`.
`tests/test_profile.py` : « Tableau de bord » / « Pour vous » → « Bonjour Roger » / « À faire » (titres
administratifs retirés par le brief).

## Sprint 1 — Navigation (App Shell)

**Ajouté**
- App Shell : sidebar persistante groupée **Principal** (Aujourd'hui, Agenda, À faire, Finances, Maison,
  Bibliothèque) / **Administration** (Paramètres), sous-entrées du groupe actif, état actif (`aria-current`).
- Header : recherche globale (GET `/recherche`), menu **+ Ajouter** (`<details>`, entrées filtrées par modules
  et droits), menu utilisateur (Profil, Paramètres, Déconnexion POST + CSRF).
- Responsive sans JS : tablette = tiroir `:target` (`#navigation`) + fond cliquable ; mobile = barre d'onglets
  basse (4 groupes + Menu).
- `app/navigation.py` : modèle de navigation (modules actifs + droits) ; rien n'est listé si la personne ne
  peut pas l'ouvrir (Foyer/Permissions/Administration avancée = principal ; Repères = `can_view_index` ;
  Document/Repère/Décision dans « + Ajouter » = principal, comme côté serveur).
- `/parametres/avance` (principal) : sauvegarde, restauration, chiffrement, démo en langage clair, commandes
  repliées dans « Détails techniques ». Les commandes CLI ne sont plus sur `/parametres`.
- Alias `/agenda`, `/a-faire`, `/maison`, `/bibliotheque` (302). Toutes les anciennes routes inchangées.
- Composants CSS : `.page-header`, `.eyebrow`, `.card-grid`, `.card`, `.btn`, `.btn--primary`, `.sr-only`.

**Modifié** : `base.html` (shell connecté ; écran invité inchangé), `settings.html`, `vault.html` (ancre
`#depot`), `app.css`, `app/__init__.py` (contexte `shell`), `app/routes/pages.py` (routes avance + alias).
`tests/test_v2_foundation.py` : assertion « Accueil » → « Aujourd » (libellé renommé par le brief).

**Fixe** : bouton secondaire illisible en thème sombre.

## Sprint 0 — Audit et stabilité

**Corrigé**
- Calendrier (`/calendrier`) et Organisation (`/organisation`) affichaient « Information — Opération impossible. »
  sur tout foyer : `listed.items` résolvait la méthode `dict.items` au lieu de la clé `"items"`. Lecture par clé.
- Recherche avec requête (`/recherche?q=…`) : même défaut (`results.items`), même correction.

**Ajouté**
- `tests/test_ux_stability.py` (6 tests) : lint des gabarits, crawl des pages (foyer vide + démo), allers-retours
  Calendrier et Organisation, recherche.
- Docs : `UX_AUDIT_V2.md`, `UX_TARGET_ARCHITECTURE.md`, `UX_IMPLEMENTATION_PLAN.md`, `UX_CHANGELOG.md`,
  `UX_TEST_REPORT.md`.

**Fichiers modifiés** : `app/templates/events.html`, `app/templates/tasks.html`, `app/templates/search.html`.
