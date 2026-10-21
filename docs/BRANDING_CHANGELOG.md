# Changelog branding New Arch

## 2026-10-21 — Refonte identité visuelle

### Ajouté
- Logo officiel PNG + déclinaisons (`app/static/brand/`)
- Fonts Manrope + Inter self-hostées
- Tokens de charte (clair / sombre) dans `app.css`
- Favicon / apple-touch-icon / app icons
- Docs : `BRANDING_AUDIT.md`, `NEW_ARCH_DESIGN_SYSTEM.md`
- Tests `tests/test_branding.py`

### Modifié
- `base.html` : logo mark, signature, theme-color, défaut **clair**
- `app/http.py` : `resolve_theme` → défaut `light`
- Styles globaux (header, boutons, cartes, formulaires, chips)
- Paramètres : libellés thème (clair en premier)
- Docs GUIDE / WINDOWS (défaut clair)

### Conservé
- Toutes les routes, ACL, calculs financiers, schéma SQLite
- Navigation horizontale fonctionnelle (pas de rewrite sidebar)
- Cookie `foyer_theme` et bascule clair/sombre

### Limites
- Pas de SVG vectoriel source (asset raster officiel uniquement)
- Sidebar compacte non livrée (header restylé à la place)
- Captures avant/après : selon disponibilité navigateur dans l’environnement CI/agent
