# Audit branding — New Arch (Phase A)

Date : 2026-10-21  
Périmètre : refonte visuelle uniquement (pas de refactor fonctionnel).

## Architecture frontend

| Élément | Constat |
|---|---|
| Framework | Flask 3 + Jinja2 (SSR), pas de React/Vue |
| CSS | Fichier unique `app/static/app.css` (~393 lignes) |
| JS | Un script local d'amélioration progressive (`script-src 'self'`, aucun inline) depuis D1 |
| Composants partagés | `base.html`, `_status.html` (chips / vault mark) |
| Thème | Cookie `foyer_theme` (`dark` \| `light`) ; **défaut actuel = dark** |
| Fonts | Roboto + Roboto Mono self-hostés (`app/static/fonts/`) — héritage Ars Codicis |
| Branding actuel | Wordmark texte « New Arch. » + accent orange `#e8501e` sur fond noir |
| Navigation | Header horizontal responsive (pas de sidebar) |
| Responsive | Breakpoint ~720px ; skip link ; `:focus-visible` ; `prefers-reduced-motion` |
| Tests UI | Pytest + `test_client` (assertions HTML) — pas de Playwright |

## Inventaire des écrans (templates)

Authentification : `login.html`, `bootstrap.html`  
Shell : `base.html`, `error.html`, `confirm.html`  
Modules : Accueil/dashboard (`today.html`), Profil, Finances, Inventaire, Calendrier, Organisation, Repères, Décisions, Médiathèque, Coffre, Foyer/Personnes/Accès, Recherche, Paramètres.

## Écarts vs charte officielle

1. **Logo** : absent — wordmark typographique seulement ; assets PNG fournis hors dépôt (`assets/`).
2. **Palette** : noir/orange/papier ≠ bleu nuit / sauge / pétrole / sable / terracotta / ivoire.
3. **Typo** : Roboto/Mono ≠ Manrope (titres) + Inter (corps).
4. **Thème** : dark-first ; charte = **clair-first** (ivoire).
5. **UI** : angles vifs, uppercase mono nav, pas de cartes douces ni boutons navy arrondis.
6. **Signature** : « Organiser le foyer, simplement. » absente.

## Fichiers à modifier (prévu)

- `docs/BRANDING_AUDIT.md`, `docs/NEW_ARCH_DESIGN_SYSTEM.md`, `docs/BRANDING_CHANGELOG.md`
- `app/static/app.css` (tokens + composants)
- `app/static/brand/` (logo PNG officiel + déclinaisons raster)
- `app/static/fonts/` (Manrope + Inter self-hostés)
- `app/templates/base.html`, `login.html`, `bootstrap.html`, `today.html`, `_status.html` (marque / ambiance)
- `app/http.py` (défaut thème `light`)
- Tests touchant `data-theme="dark"` / wordmark

## Non-objectifs

- Pas de nouvelle lib UI, pas de SPA, pas de changement API/schéma/ACL.
- Pas de faux SVG tracé depuis le PNG (asset raster officiel conservé).
- Pas de sidebar complète si elle casse la nav existante : **header de marque + nav horizontale** restylée (structure préservée) ; layout type « rail » documenté pour évolution.

## Stratégie

Tokens CSS sémantiques → restyle global via `app.css` → logo dans le header → light par défaut → ajustements templates légers → tests + captures.
