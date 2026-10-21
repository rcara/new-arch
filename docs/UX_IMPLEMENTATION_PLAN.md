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

## Sprint 5 — Qualité ✅

- Accessibilité : audit axe-core (WCAG 2.1 AA) sur 20 pages × clair / sombre × desktop / mobile, foyer démo et
  foyer vide, plus connexion et 404 invité : **0 violation**. Corrections : jeton `--text-sage` (#4E6A61 clair,
  5,9:1 sur blanc ; #A8C0B6 sombre) pour liens et sur-titres, au lieu du sauge de marque #5F7E74 (4,44:1) ;
  règle sombre des liens passée en `:where()` (elle écrasait boutons primaires, sidebar et barre mobile) ;
  rouge danger sombre éclairci ; jours hors mois sans opacité.
- Clavier : lien d'évitement en premier, anneau de focus visible partout, sidebar mobile masquée hors du parcours,
  panneaux d'ajout rapide : Tab → « Fermer » puis Titre (ancre `:target`, sans JS).
- Erreurs : une page par famille de statut (403 accès, 404 introuvable, 400/409/413/415 action non enregistrée,
  405, 423/429/503 indisponible, 500) avec code, message, action de retour, « Réessayer » si pertinent, lien de
  connexion pour un invité ; aucun détail technique exposé.
- Recherche : sources filtrées par module actif (un module désactivé ne remonte plus rien), résultats groupés
  par type, états « Que cherchez-vous ? », trop court (message complet, `aria-invalid`), aucun résultat.
  Permissions inchangées (`can_see_object`, index, principal seul pour les personnes).
- Garde-fous testés : aucune page sans CSP `script-src 'none'`, aucun `<script>`, `style=` ni `on*=` ;
  un seul `h1`, `main#contenu` et `lang="fr"` par page.

## Décisions à prendre (Roger)

| # | Sujet | Proposition | Statut |
|---|---|---|---|
| D1 | **JS / CSP** — glisser-déposer (Coffre) et panneau latéral (création rapide) nécessitent du JavaScript. | Livré sans JS : dépôt par `<input type=file>` (le navigateur accepte déjà le glisser-déposer *sur* le champ), panneaux d'ajout rapide via `:target` (livrés au Sprint 3 : `#ajout-tache`, `#ajout-evenement`, fermeture par « Fermer » ou le fond ; le menu `<details>` reste ouvert derrière le panneau et le focus n'y est pas déplacé automatiquement). Coffre (Sprint 4) : zone de dépôt agrandie autour du champ fichier natif, qui accepte le glisser-déposer sans script. Pour un vrai glisser-déposer sur zone ou un panneau dynamique : autoriser un script **local** (`script-src 'self'`) limité à l'amélioration progressive. CSP **non modifiée** tant que non validé. | Bloquant pour l'amélioration, pas pour la livraison |
| D2 | **Connexion locale HTTP** : Chrome envoie `Origin: null` (`Referrer-Policy: no-referrer`) → « Origine refusée » sur `127.0.0.1`. | Option A : `Referrer-Policy: same-origin` (le navigateur envoie alors l'Origin exacte). Option B : accepter `null` quand l'hôte est exactement `127.0.0.1:port` (CSRF reste requis). Non modifié (sécurité). | À décider |
| D3 | Modules activables affichés mais non basculables dans l'UI. | **Livré (V2.2)** : formulaire « Modules du foyer » dans Paramètres, compte principal seul (403 sinon), POST + CSRF, journalisé (`module_enable` / `module_disable`), par foyer actif. Un module désactivé est masqué partout (navigation, « + Ajouter », recherche, cartes et raccourcis d'Aujourd'hui, liens croisés) et ses routes HTML/API renvoient 404 ; aucune donnée n'est modifiée. Toujours actifs : Accueil (page d'arrivée), Foyer (membres et accès), Paramètres (sinon impossible de réactiver). Aucune migration : table `module_setting` existante. | Résolu (approuvé par Roger) |
| D4 | Notifications : aucun moteur existant. | Ne pas inventer ; rappels réels sur Aujourd'hui. | Proposé |
| D5 | Wordmark : le logo validé dit « New Arch » (pas « NEW ARCH. »). | Conserver le logo validé de PR #16. | Proposé |
| D6 | Événements récurrents : la récurrence est stockée mais aucune occurrence n'est générée dans les listes. | Approuvé par Roger : occurrences calculées à la lecture sur la période demandée (`events.occurrences`), sans réécriture ni migration ; Agenda (mois, semaine, liste) et carte Agenda d'Aujourd'hui. Une occurrence ouvre la série ; la modification porte explicitement sur toute la série (pas d'édition par occurrence). | Résolu (V2.2) |
| D7 | Photos de biens / affiches d'œuvres : aucun champ image en base. | Vignettes typées (initiale, couleur par type). Ajouter une image = migration additive + stockage, à valider. | À décider |
