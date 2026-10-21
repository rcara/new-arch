# UX Audit V2.1 — Sprint 0

Date : 2026-10-21 · Base : `main` @ `bffe360` · Brief : « NEW ARCH — UX Transformation V2.1 ».

## 1. Technologies réellement utilisées

| Couche | Constat |
|---|---|
| Serveur | Flask 3 + Waitress, rendu Jinja2 côté serveur (`app/routes/pages.py`, 99 routes HTML) |
| API | JSON sous `/api` (`app/routes/api.py`, 84 routes), même services métier que les pages |
| Données | SQLite (`data/metadata.sqlite`), migrations `001`→`006`, `PRAGMA user_version = 6` |
| Fichiers | Coffre + médiathèque sur disque, chiffrement AES-GCM optionnel (`docs/v2/10_ENCRYPTION.md`) |
| Front | **Zéro JavaScript.** CSP stricte : `script-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'` |
| CSS | Une feuille `app/static/app.css` (684 lignes), tokens de marque PR #16, thème clair + sombre (cookie `foyer_theme`) |
| Polices | Manrope (titres) + Inter (corps) auto-hébergées |
| Tests | pytest, 68 tests au départ (`tests/`), client de test Flask, pas de navigateur |
| Déploiement | Push sur `main` → CI → `deploy.yml` (SSH VPS). **Aucun merge sur `main` dans ce chantier.** |

Conséquence de conception : toute interaction (menus, tiroirs, panneaux) doit être réalisable en HTML/CSS
(`<details>`, `:target`, `:focus-within`, formulaires). Voir les décisions JS/CSP dans `UX_IMPLEMENTATION_PLAN.md`.

## 2. Inventaire des écrans

| Rubrique nav (actuelle) | Route | Gabarits | Module désactivable |
|---|---|---|---|
| Accueil | `/` | `today.html` | `accueil` |
| Finances | `/finances`, `/finances/depense`, `/remboursement`, `/budget`, `/import` | `finance*.html` | `finances` |
| Inventaire | `/inventaire`, `/inventaire/nouveau`, `/<id>`, `/lieux/nouveau` | `inventory*.html` | `inventaire` |
| Calendrier | `/calendrier`, `/nouveau`, `/<id>`, `/<id>/modifier` | `events.html`, `event*.html` | `calendrier` |
| Organisation | `/organisation`, `/nouvelle`, `/<id>`, `/<id>/modifier` | `tasks.html`, `task*.html` | `organisation` |
| Repères | `/reperes` (+ archiver/restaurer) | `milestone*.html` | `reperes` |
| Décisions | `/decisions` (+ sceller/résultat) | `decision*.html` | `decisions` |
| Médiathèque | `/mediatheque` (+ œuvres, listes, bibliothèque) | `media*.html` | `mediatheque` |
| Coffre | `/coffre` (+ remplacer/retirer/ouvrir) | `vault.html`, `file_replace.html` | `coffre` |
| Foyer | `/foyer`, `/personnes`, `/acces` (principal uniquement) | `people.html`, `person_form.html`, `access*.html` | `foyer` |
| Recherche | `/recherche?q=` | `search.html` | `recherche` |
| Paramètres | `/parametres`, `/parametres/theme` | `settings.html` | `parametres` |
| Profil | `/profil` | `profile.html` | — |

Composants existants réutilisables : `.site-header`, nav à pastilles, `.today-panel` (carte), `.row`, `.badge`,
`.toolbar`, `_status.html` (pastilles statut), `confirm.html`, `error.html`.

## 3. Permissions (à préserver)

- Compte **principal** : tout voir/administrer ; seul à accéder à Foyer / Personnes / Accès.
- Compte **secondaire** : Repères visibles si `can_view_index` ; fichiers du coffre et décisions visibles uniquement
  via `file_access` / `decision_access` individuels ; recherche filtrée par les mêmes règles (`services/search.py`).
- Décisions : séparation décision/fichier, scellement, contenu scellé immuable (triggers SQL), résultats ajoutés ensuite.
- Modules : `module_setting` ; `require_module()` renvoie 404 si désactivé ; la nav ne liste que `nav_modules`.

## 4. Anomalie bloquante : Calendrier et Organisation — « Information — Opération impossible. »

**Reproduction** (foyer vide *et* foyer démo, navigateur et client de test) : `GET /calendrier` → 500,
`GET /organisation` → 500, `GET /recherche?q=…` → 500. Le message vient du gestionnaire générique
`on_error` (`app/__init__.py`) qui masque toute exception non métier.

**Cause racine** — trace :

```
File "app/templates/events.html", line 8:  {% for item in listed.items %}
TypeError: 'builtin_function_or_method' object is not iterable
```

Les services renvoient un dict `{"items": [...], "total": …}`. En Jinja2, `listed.items` résout d'abord
l'**attribut** Python `dict.items` (méthode) avant la clé `"items"`. Donc `{% if listed.items %}` est toujours vrai
(méthode liée) et la boucle `for` plante — même sur un foyer vide. Même défaut dans `search.html`
(`results.items`), déclenché dès qu'une recherche a une requête.

**Pourquoi non détecté** : les tests couvraient l'API JSON `/api/tasks`, `/api/events`, `/api/search` (qui
fonctionnent) mais aucun test ne rendait les pages HTML correspondantes.

**Correction** : `listed['items']` / `results['items']` (lecture par clé) dans `events.html`, `tasks.html`,
`search.html`. Aucune donnée, route ni service modifiés.

**Garde-fous ajoutés** (`tests/test_ux_stability.py`) :
- lint des gabarits : interdit `x.items` / `x.keys` / `x.values` sans appel ;
- crawl de toutes les pages liées depuis `/` sur foyer vide (26 pages) et foyer démo (42 pages) : aucun 500,
  aucun « Opération impossible » ;
- aller-retour HTML Calendrier : créer → listé → modifier → changement visible ;
- aller-retour HTML Organisation : créer → listé → terminer → disparaît des ouvertes, visible dans « Faites » ;
- recherche avec résultats et sans résultat.

Les 6 tests échouent sur `main` et passent après correction.

## 5. Autres constats (brief §3)

| # | Constat | Gravité | Sprint |
|---|---|---|---|
| 3.1 | 14 entrées horizontales (12 modules + Profil + Déconnexion), retour à la ligne sur desktop | Haute | 1 |
| 3.2 | `--wrap` limite le contenu à une colonne étroite, cartes empilées | Moyenne | 1–2 |
| 3.3 | Accueil = « Tableau de bord » de compteurs ; pas d'agenda/tâches actionnables ni budget du mois | Haute | 2 |
| 3.5 | États vides = phrase + lien texte, pas d'action principale visible | Moyenne | 2–4 |
| 3.6 | Tous les modules = listes `.row` identiques | Moyenne | 4 |
| 3.7 | Paramètres → « Exploitation » expose des commandes `python cli.py …` à tous les comptes | Moyenne | 1 (déplacé en « Administration avancée », principal seul) |
| A1 | Modules affichés « Activé/Masqué » mais aucune UI pour les basculer | Basse | Décision Roger |
| A2 | En local HTTP (`127.0.0.1`), Chrome envoie `Origin: null` (car `Referrer-Policy: no-referrer`) → « Origine refusée » à la connexion. En production HTTPS : accepté. | Moyenne (usage local Windows) | Décision Roger (sécurité) |
| A3 | Dataset démo daté février 2027 : à date réelle, l'Accueil démo paraît vide (« 30 prochains jours ») | Basse | Doc |
| A4 | Création = une page complète par opération, pas de création rapide globale | Haute | 3 |

## 6. Identité

Le logo validé existe (`app/static/brand/logo-*.png`, PR #16) et la palette du brief est déjà la palette
des tokens (`--brand-navy #24364A`, `--brand-sage #5F7E74`, `--brand-petrol #7FA6A6`, `--brand-sand #E8D7C1`,
`--brand-terracotta #C97C43`, `--brand-ivory #F7F4EE`). Le chantier UX conserve ces tokens et le logo ;
il ne crée pas de nouveau logo.

## 7. Captures

Avant/après dans le store projet `media/ux-v2/` : `s0-avant-*` (main) et `s0-apres-*` (correctif),
foyers `vide` et `demo`, desktop + mobile.
