# Rapport de tests — 21 octobre 2026 (New Arch V2 A→F)

Machine : Linux, Python 3.12.3, Flask 3.1.3.

## Automatisés

```sh
.venv/bin/python -m pytest tests/ -q
```

Résultat : **57 tests, tous réussis**.

- V1 + B + C + D + E inchangés (`user_version` jusqu’à 6).
- Solidification F : backup vault+média, seed démo, thème clair/sombre, export inventaire CSV, parcours e2e transversal (`tests/test_solidification.py`).

## Limitations

- Pas de chiffrement au repos.
- ZIP V1 toujours absent du workspace.
