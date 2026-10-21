# UX Target Architecture — New Arch V2.1

Navigation cible **sans fusion des services métier** : les routes et services existants restent ; seule la couche
d'expérience (gabarits, CSS, petites routes d'alias) change. Contrainte : zéro JavaScript, CSP inchangée.

## 1. App Shell

```
┌───────────────┬──────────────────────────────────────────────────────────┐
│  Logo New Arch│  [ Rechercher dans le foyer… ]   [+ Ajouter ▾]  [Alex ▾] │  header
│               ├──────────────────────────────────────────────────────────┤
│ PRINCIPAL     │  PageHeader (titre, sous-titre, action principale)       │
│ ● Aujourd'hui │                                                          │
│ ○ Agenda      │  Contenu en grille (cartes, tableaux, galeries)          │
│   Calendrier  │                                                          │
│   Repères     │                                                          │
│ ○ À faire     │                                                          │
│ ○ Finances    │                                                          │
│ ○ Maison      │                                                          │
│ ○ Bibliothèque│                                                          │
│ ADMINISTRATION│                                                          │
│ ○ Paramètres  │                                                          │
└───────────────┴──────────────────────────────────────────────────────────┘
```

- **Desktop ≥ 1024 px** : sidebar fixe 248 px, contenu fluide jusqu'à 1280 px.
- **Tablette 720–1023 px** : sidebar en tiroir (bouton « Menu » dans le header, `:target`), header complet.
- **Mobile < 720 px** : barre d'onglets basse (Aujourd'hui · Agenda · À faire · Finances · Menu) + même tiroir.
- Tiroir sans JS : `<a href="#navigation">Menu</a>` ouvre `nav#navigation:target` ; « Fermer » = `href="#contenu"`.

## 2. Groupes de navigation

| Groupe | Entrée (route) | Sous-fonctions (routes existantes) | Visible si |
|---|---|---|---|
| Aujourd'hui | `/` | — | `accueil` |
| Agenda | `/calendrier` (sinon `/reperes`) | Calendrier `/calendrier` · Repères et échéances `/reperes` | `calendrier` ou `reperes` |
| À faire | `/organisation` | Tâches `/organisation` · Faites `/organisation?status=done` | `organisation` |
| Finances | `/finances` | Vue d'ensemble `/finances` · Nouvelle dépense · Budgets · Remboursements · Import | `finances` |
| Maison | `/inventaire` | Inventaire · Nouveau bien · Nouveau lieu | `inventaire` |
| Bibliothèque | `/coffre` (sinon premier dispo) | Documents et coffre `/coffre` · Médiathèque `/mediatheque` · Décisions `/decisions` | `coffre`, `mediatheque` ou `decisions` |
| Paramètres | `/parametres` | Foyer `/foyer`* · Membres `/personnes`* · Permissions `/acces`* · Préférences `/parametres` · Profil `/profil` · Administration avancée `/parametres/avance`* | `parametres` (Profil toujours) |

\* compte principal uniquement (mêmes règles serveur qu'aujourd'hui). Une entrée n'apparaît que si son module
est actif **et** si la personne a le droit ; un groupe sans entrée visible est masqué.

Sous-fonctions sans support métier aujourd'hui (Listes, Projets, Comptes, Garanties transverses…) : **non
affichées** tant qu'elles n'existent pas — on n'affiche jamais d'entrée inaccessible.

Alias de compatibilité (302) : `/agenda` → `/calendrier`, `/a-faire` → `/organisation`, `/maison` → `/inventaire`,
`/bibliotheque` → `/coffre`. Toutes les anciennes routes restent valides.

## 3. Header

- **Recherche globale** : formulaire GET `/recherche` (si module `recherche`).
- **+ Ajouter** : `<details>` menu ; entrées filtrées par modules et droits (Dépense, Événement, Tâche, Bien,
  Document, Repère, Décision, Œuvre). Sprint 3 : formulaires rapides.
- **Menu utilisateur** : `<details>` (nom, rôle, Profil, Paramètres, Déconnexion en POST + CSRF).
- **Notifications** : pas de moteur de notifications ; le brief interdit d'inventer → remplacé par les rappels réels
  (échéances urgentes, tâches en retard) sur Aujourd'hui. Décision documentée.

## 4. Accueil « Aujourd'hui » (Sprint 2)

Grille 12 colonnes desktop (2–3 cartes par ligne), 2 colonnes tablette, 1 colonne mobile :
Bienvenue · Agenda (événements + repères à échéance) · À faire (mes tâches + partagées, « Terminer » en un clic) ·
Finances (dépenses du mois par devise, budget restant, soldes) · Raccourcis · Démarrage (onboarding facultatif) ·
Activité récente (si données autorisées).

## 5. Composants partagés

Sidebar, Header, PageHeader (`_page_header.html`), Buttons (`.btn`, `.btn--primary/secondary/ghost`),
Cards (`.card`, ex-`.today-panel`), EmptyState (`_empty.html` : titre, explication, action principale, exemple
optionnel), ErrorState (`error.html` : aucune donnée / aucun résultat / aucun droit / erreur / indisponible),
Forms, Search, Tables (`.table`), Notifications (`.status` flash).

## 6. Tokens

Palette du brief = tokens existants (PR #16), inchangés : navy `#24364A`, sauge `#5F7E74`, pétrole `#7FA6A6`,
sable `#E8D7C1`, terracotta `#C97C43`, ivoire `#F7F4EE`. Thème sombre conservé.
