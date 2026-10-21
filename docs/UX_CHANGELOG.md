# UX Changelog — New Arch V2.1

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
