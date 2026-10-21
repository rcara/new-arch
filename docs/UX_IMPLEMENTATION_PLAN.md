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

## Sprint 2 — Accueil

- Service `home.dashboard` étendu (lecture seule) : agenda 14 jours, tâches (moi + partagées), dépenses du mois par
  devise, budgets du mois, soldes, activité récente autorisée.
- `today.html` en grille ; action « Terminer » (POST) sur les tâches ; onboarding facultatif (masquable via
  cookie, reprenable depuis Paramètres) basé sur l'état réel.

## Sprint 3 — Création rapide

- Menu « + Ajouter » ; formulaires rapides (champs essentiels d'abord, « Plus d'options » en `<details>`),
  redirection vers la page d'origine (`next` validé, même origine), messages de retour.
- Création contextuelle depuis un bien / un événement.

## Sprint 4 — Modules

Finances (sous-nav, tableaux, indicateurs), Inventaire (galerie/liste, filtres), Agenda (mois / semaine / liste en
HTML pur), À faire (liste rapide, terminer en 1 clic), Coffre (explorateur, dépôt simple), Médiathèque (catalogue /
envies / en cours / fichiers), Décisions (présentation, création guidée — règles de scellement intactes).

## Sprint 5 — Qualité

Desktop / tablette / mobile, clair / sombre, clavier, lecteurs d'écran, permissions dans la recherche, états vides,
erreurs.

## Décisions à prendre (Roger)

| # | Sujet | Proposition | Statut |
|---|---|---|---|
| D1 | **JS / CSP** — glisser-déposer (Coffre) et panneau latéral (création rapide) nécessitent du JavaScript. | Livré sans JS : dépôt par `<input type=file>` (le navigateur accepte déjà le glisser-déposer *sur* le champ), panneaux via pages dédiées / `:target`. Pour un vrai glisser-déposer sur zone ou un panneau dynamique : autoriser un script **local** (`script-src 'self'`) limité à l'amélioration progressive. CSP **non modifiée** tant que non validé. | Bloquant pour l'amélioration, pas pour la livraison |
| D2 | **Connexion locale HTTP** : Chrome envoie `Origin: null` (`Referrer-Policy: no-referrer`) → « Origine refusée » sur `127.0.0.1`. | Option A : `Referrer-Policy: same-origin` (le navigateur envoie alors l'Origin exacte). Option B : accepter `null` quand l'hôte est exactement `127.0.0.1:port` (CSRF reste requis). Non modifié (sécurité). | À décider |
| D3 | Modules activables affichés mais non basculables dans l'UI. | Ajouter un interrupteur (principal seul) en Sprint 4/5. | À décider |
| D4 | Notifications : aucun moteur existant. | Ne pas inventer ; rappels réels sur Aujourd'hui. | Proposé |
| D5 | Wordmark : le logo validé dit « New Arch » (pas « NEW ARCH. »). | Conserver le logo validé de PR #16. | Proposé |
