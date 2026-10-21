# Rapport de tests — 21 octobre 2026 (New Arch V2 étapes B+C)

Machine : Linux, Python 3.12.3, Flask 3.1.3, Waitress 3.0.2, argon2-cffi.

## Automatisés

```sh
.venv/bin/python -m pytest tests/ -q
```

Résultat : **44 tests, tous réussis**.

- Suite V1 + socle B inchangées (migrations jusqu’à `user_version=4`).
- Finances : parsing sans float, splits somme exacte, soldes 50/50, remboursement sans double comptage budget, refus CHF≠compte EUR, transactions privées invisibles au second compte, export CSV + page Finances.

## Limitations

- Inventaire / médiathèque non livrés.
- Pas de chiffrement au repos.
- ZIP spécification V1 toujours absent du workspace.
