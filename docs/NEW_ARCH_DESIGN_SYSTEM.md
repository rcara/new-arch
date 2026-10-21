# New Arch — Design System

Signature : **« Organiser le foyer, simplement. »**

## Principes

Clarté · Chaleur · Structure · Sobriété

## Logo

Assets raster officiels (PNG source validé — pas de faux SVG) dans `app/static/brand/` :

| Fichier | Usage |
|---|---|
| `logo-full.png` | Source complète (fond transparent ; texte bleu nuit : réservé aux fonds clairs) |
| `logo-mark.png` | Symbole seul, fond transparent (sidebar, en-tête, connexion ; clair et sombre) |
| `logo-header.png` / `logo-lockup.png` | Lockups compactés |
| `favicon-32.png`, `apple-touch-icon.png`, `app-icon-*.png` | Icônes |

Planche de référence : `docs/brand/brand-board.png`.

## Couleurs (tokens CSS)

| Token marque | HEX | Rôle |
|---|---|---|
| `--brand-navy` | `#24364A` | Nav, titres, boutons primary |
| `--brand-sage` | `#5F7E74` | Secondaire / succès |
| `--brand-petrol` | `#7FA6A6` | Info / focus |
| `--brand-sand` | `#E8D7C1` | Surfaces chaudes |
| `--brand-terracotta` | `#C97C43` | Accent / alerte douce |
| `--brand-ivory` | `#F7F4EE` | Fond clair |

Sémantiques : `--background`, `--surface`, `--text-primary`, `--text-secondary`, `--border`, `--primary`, `--secondary`, `--accent`, `--success`, `--warning`, `--danger`, `--focus-ring` (+ hover).

**Clair = référence produit.** Sombre = tokens dédiés (`html[data-theme=dark]`), pas d’inversion.

## Typographie

- Titres : **Manrope** (self-host `app/static/fonts/brand/`)
- Corps : **Inter** (idem)
- Chiffres : `font-variant-numeric: tabular-nums`

## Composants

- Header sticky + logo mark + wordmark + nav pills
- Boutons primary navy (pill), secondary bordure, accent sauge, danger
- Panneaux `.today-panel` = cartes surface blanche, radius 16px, ombre légère
- Chips statut (terminé / en cours / neutre)
- Formulaires : labels Inter, champs radius 8px, focus pétrole

## Navigation

Sidebar gauche (rail desktop) + tiroir mobile via checkbox CSS (`#nav-toggle`), sans JavaScript — CSP `script-src 'self'` (un seul script local d'amélioration progressive, aucun inline ; tout fonctionne sans JS). Sélecteur de foyer + création dans la sidebar. État actif navy / sable en sombre.

## Accessibilité

Skip link, `:focus-visible`, contrastes navy/ivoire, zones tactiles ≥ 44px mobile, `prefers-reduced-motion`.
