# UX Changelog — New Arch V2.1

## Mise en production — intégration avec le multi-foyer (PR #18)

- Fusion de la pile Sprint 1 → 5 avec `main` (qui contenait déjà Sprint 0 et le multi-foyer de PR #18).
- Shell : la sidebar V2.1 (tiroir `:target`) remplace celle de PR #18 (tiroir `#nav-toggle`) ; le sélecteur
  de foyer et « Nouveau foyer » de PR #18 sont repris en bas de la sidebar (`<details>`, POST + CSRF inchangés).
- Requêtes ajoutées par la V2.1 désormais cloisonnées au foyer actif (`hh(ctx)`) : agenda, Aujourd'hui
  (activité récente, progression de démarrage), total des dépenses du mois, recherche filtrée par module.
- Tests : `test_multi_household.py` vérifie le tiroir `:target` au lieu de la case à cocher ; nouveau test
  d'isolation des vues V2.1 entre deux foyers (`test_ux_quality.py`). 140 tests passés, axe : 0 violation.

## Sprint 5 — Qualité

**Ajouté**
- `tests/test_ux_quality.py` (8 tests) : pages d'erreur distinctes (403, 404, 500, invité), états et groupes
  de la recherche, bien privé masqué au compte secondaire, module désactivé exclu de la recherche, absence de
  script / style inline / gestionnaire `on*` et CSP stricte sur 21 pages, repères de structure (un `h1`,
  `main#contenu`, `lang`).
- Jeton CSS `--text-sage` (clair #4E6A61, sombre #A8C0B6) pour le texte sauge.

**Modifié**
- `error.html` : titre, explication et actions selon le statut (403 / 404 / 4xx de validation / 405 /
  423-429-503 / 500), `role="alert"`, « Réessayer » en GET pour les erreurs transitoires, connexion pour un invité.
  Les gestionnaires d'erreurs transmettent le statut (`app/__init__.py`).
- `services/search.py` : chaque source n'est interrogée que si son module est actif (repères, organisation,
  calendrier, décisions, foyer, inventaire, médiathèque). Règles d'accès inchangées.
- `search.html` : en-tête de page, résultats groupés par type, états vide / trop court / aucun résultat ;
  le message de validation complet est affiché (« Saisissez au moins 2 caractères. »).
- Contraste : liens et sur-titres en `--text-sage` (AA) ; règle sombre des liens en `:where()` pour ne plus
  écraser boutons primaires, navigation et barre mobile ; `--danger` sombre #FB8A80 ; bouton « Fermer » des
  panneaux en couleur de texte ; jours hors mois sans opacité.

**Inchangé** : schéma, données, sessions, permissions, scellement des décisions, règles financières, CSP.

## Sprint 4 — Modules

**Ajouté**
- `app/templates/_ui.html` : macros `page_header`, `subnav`, `empty_state` (variantes données / recherche /
  droit refusé, avec exemple illustratif présenté comme tel). Utilisées par tous les modules ci-dessous.
- `app/services/agenda.py` (lecture seule) : vues mois / semaine / liste au-dessus de `events.list_events` et
  `milestones.list_milestones` (repères seulement si module actif et index accordé). Événements multi-jours sur
  chaque jour en grille, une seule fois en liste.
- `POST /organisation/<id>/rouvrir` (CSRF, `next` même site) ; `tasks.list_tasks(assignee="moi"|"partage")`
  (paramètre optionnel, API inchangée).
- Finances : `?vue=apercu|transactions|budgets|comptes|repartition` ; évolution des dépenses sur 6 mois via
  `finance.month_spending` (aucune règle de calcul modifiée, devises séparées).

**Modifié**
- Agenda (`events.html`) : grille mois / semaine (tableau accessible, en-têtes de colonnes), liste par jour,
  navigation de période, filtre membre + titre, légende événement / échéance, état vide ou « aucun résultat ».
- À faire (`tasks.html`) : ajout rapide en ligne, groupes par échéance, onglets statut / responsable, pagination.
- Finances (`finance.html`) : onglets, cartes Vue d'ensemble, tableau des transactions (filtre type, export /
  import), budgets avec jauge, comptes en cartes, répartition. Sidebar Finances alignée sur les onglets.
- Inventaire : galerie / liste, filtres lieu + catégorie, garanties en bandeau, lieux en pastilles.
- Coffre : explorateur (filtres nom / type / repère, tri récent d'abord), carte de dépôt latérale, menu
  « … » pour Remplacer / Retirer, états vide / aucun résultat / aucun accès distincts.
- Médiathèque : onglets, galerie d'affiches typées, fichiers personnels séparés du catalogue.
- Décisions : explication du cycle, Brouillons / Scellées, sélection du repère (GET vers le formulaire existant).
  « + Ajouter → Décision » mène à ce formulaire.
- `tests/test_ux_stability.py` : le crawl ignore le paramètre `date=` (navigation de période infinie) et le test
  Calendrier utilise les vues liste / mois (comportement vérifié identique).

## Sprint 3 — Création rapide

**Ajouté**
- Panneaux d'ajout rapide sans JavaScript (`:target`) dans le shell : `#ajout-tache` (titre, échéance,
  « M'assigner la tâche » coché par défaut) et `#ajout-evenement` (titre, date du jour, journée entière). Lien
  « Formulaire complet » vers le formulaire détaillé. Retour sur la page d'origine après enregistrement.
- `next` sur toutes les créations (tâche, événement, dépense, bien, repère, œuvre), validé par `safe_next`
  (chemins du même site uniquement ; `//…`, `https://…`, `javascript:` → page par défaut). Les entrées du menu
  « + Ajouter » portent `?next=<page courante>`.
- Section « Tâches liées » sur la fiche événement et la fiche bien, avec « + Ajouter une tâche liée » (titre
  « Préparer : … » / « Entretien : … », date de l'événement pré-remplie). Lien typé `task → concerns → objet` créé
  après `links.require_object` : impossible de lier un objet invisible (404, aucune tâche créée).
- Dépense : date du jour par défaut ; compte facultatif (« Automatique » = premier compte actif **de la devise
  saisie** ; aucune conversion CHF/EUR, aucune règle de calcul modifiée).

**Modifié**
- Formulaires tâche, événement, dépense, bien : champs essentiels d'abord, le reste dans « Plus d'options »
  (`<details class="more">`, ouvert automatiquement si une erreur s'y trouve) ; boutons Enregistrer / Annuler
  (Annuler revient à `next`).
- Dépense : les erreurs catégorie, payeur, répartition, visibilité et notes sont désormais affichées (elles
  étaient silencieuses), plus un message récapitulatif `role="alert"`.
- Formulaire événement complet : la case « Journée entière » décochée est respectée (marqueur
  `all_day_present`) ; le panneau rapide crée un événement journée entière.
- `app.css` : `.form-card`, `.form-row` (2 colonnes, 1 sur mobile), `details.more`, `.form-actions`,
  `.quick-panel` + fond.

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
