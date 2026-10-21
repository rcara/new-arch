# UX Implementation Plan — New Arch V2.1

Règles : pas de réécriture, pas de migration destructive, aucune modification des règles de calcul financier,
zéro JS (CSP `script-src 'none'` inchangée), une PR **brouillon** par sprint, jamais de merge sur `main`
(le push sur `main` déploie en production).

## Sprint 0 — Audit et stabilité ✅

- Inventaire pages / routes / API / permissions / tests → `UX_AUDIT_V2.md`.
- Calendrier + Organisation + Recherche : cause racine `listed.items` (méthode `dict.items`) → lecture par clé.
- Tests : lint gabarits, crawl foyer vide + démo, allers-retours HTML.

## Sprint 1 — Navigation (App Shell) ✅

- `app/navigation.py` : construit les groupes à partir de `nav_modules` + droits de la personne.
- `base.html` : sidebar groupée, header (recherche, + Ajouter, menu utilisateur), tiroir `:target`, barre mobile.
- Alias `/agenda`, `/a-faire`, `/maison`, `/bibliotheque`.
- Paramètres : commandes CLI déplacées dans « Administration avancée » (`/parametres/avance`, principal seul),
  en langage clair, commandes repliées.
- Tests : chaque lien de nav répond 200, modules désactivés masqués, compte secondaire sans entrées admin,
  état actif correct.

## Sprint 2 — Accueil ✅

- Service `home.dashboard` étendu (lecture seule) : agenda 14 jours, tâches (moi + partagées), dépenses du mois par
  devise, budgets du mois, soldes, activité récente autorisée.
- `today.html` en grille ; action « Terminer » (POST) sur les tâches ; onboarding facultatif (masquable via
  cookie, reprenable depuis Paramètres) basé sur l'état réel.

## Sprint 3 — Création rapide ✅

- Menu « + Ajouter » : Tâche et Événement ouvrent un **panneau latéral `:target`** (CSS seul) ; les autres
  entrées ouvrent le formulaire complet avec `?next=<page courante>`.
- Formulaires rapides (champs essentiels d'abord, « Plus d'options » en `<details>`), redirection vers la page
  d'origine (`next` validé par `safe_next`, même site), messages de retour existants.
- Création contextuelle depuis un événement ou un bien (« Tâches liées », lien `concerns` après contrôle de
  visibilité).
- Reste hors périmètre sans JS : fermeture du menu « + Ajouter » au clic extérieur, focus automatique dans le
  panneau (voir D1).

## Sprint 4 — Modules ✅

- Composants partagés `_ui.html` : `page_header`, `subnav` (onglets), `empty_state` (données / recherche / droit).
- Agenda : vues mois, semaine, liste (HTML pur, `?vue=&date=`), Précédent / Aujourd'hui / Suivant, filtre par
  membre (responsable), échéances de repères si l'index est accordé ; grille repliée en liste de jours sur mobile.
  Anciens paramètres `from` / `q` toujours acceptés (vue liste).
- À faire : ajout rapide en ligne, groupes En retard / Aujourd'hui / À venir / Sans date, onglets statut et
  responsable, terminer et rouvrir en un clic (POST + CSRF), récurrence affichée (le moteur recrée l'occurrence).
- Finances : onglets Vue d'ensemble / Transactions / Budgets / Comptes / Répartition (sidebar alignée), devise
  CHF / EUR en onglets séparés, dépenses du mois + évolution 6 mois (barres CSS, sans style inline), tableaux.
- Inventaire : galerie / liste, filtres lieu et catégorie (catégories issues des seuls biens visibles).
- Coffre : explorateur (filtres nom, type, repère), zone de dépôt, actions secondaires en menu.
- Médiathèque : onglets Catalogue / En cours / Envies / Listes / Mes fichiers, galerie d'affiches (placeholder
  typé : aucune image d'œuvre n'existe en base).
- Décisions : cycle Rédiger → Sceller → Compléter, Brouillons / Scellées, choix du repère puis formulaire existant.
  Aucune règle de scellement ni d'accès modifiée.

## Sprint 5 — Qualité

Desktop / tablette / mobile, clair / sombre, clavier, lecteurs d'écran, permissions dans la recherche, états vides,
erreurs.

## Décisions à prendre (Roger)

| # | Sujet | Proposition | Statut |
|---|---|---|---|
| D1 | **JS / CSP** — glisser-déposer (Coffre) et panneau latéral (création rapide) nécessitent du JavaScript. | Livré sans JS : dépôt par `<input type=file>` (le navigateur accepte déjà le glisser-déposer *sur* le champ), panneaux d'ajout rapide via `:target` (livrés au Sprint 3 : `#ajout-tache`, `#ajout-evenement`, fermeture par « Fermer » ou le fond ; le menu `<details>` reste ouvert derrière le panneau et le focus n'y est pas déplacé automatiquement). Coffre (Sprint 4) : zone de dépôt agrandie autour du champ fichier natif, qui accepte le glisser-déposer sans script. Pour un vrai glisser-déposer sur zone ou un panneau dynamique : autoriser un script **local** (`script-src 'self'`) limité à l'amélioration progressive. CSP **non modifiée** tant que non validé. | Bloquant pour l'amélioration, pas pour la livraison |
| D2 | **Connexion locale HTTP** : Chrome envoie `Origin: null` (`Referrer-Policy: no-referrer`) → « Origine refusée » sur `127.0.0.1`. | Option A : `Referrer-Policy: same-origin` (le navigateur envoie alors l'Origin exacte). Option B : accepter `null` quand l'hôte est exactement `127.0.0.1:port` (CSRF reste requis). Non modifié (sécurité). | À décider |
| D3 | Modules activables affichés mais non basculables dans l'UI. | Ajouter un interrupteur (principal seul) en Sprint 4/5. | À décider |
| D4 | Notifications : aucun moteur existant. | Ne pas inventer ; rappels réels sur Aujourd'hui. | Proposé |
| D5 | Wordmark : le logo validé dit « New Arch » (pas « NEW ARCH. »). | Conserver le logo validé de PR #16. | Proposé |
| D6 | Événements récurrents : la récurrence est stockée mais aucune occurrence n'est générée dans les listes. | Badge « récurrent » seulement ; générer les occurrences demande une évolution du service `events` (hors UX). | À décider |
| D7 | Photos de biens / affiches d'œuvres : aucun champ image en base. | Vignettes typées (initiale, couleur par type). Ajouter une image = migration additive + stockage, à valider. | À décider |
