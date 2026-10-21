# Rapport de tests — 21 octobre 2026 (New Arch V2 A→F)

Machine : Linux, Python 3.12.3, Flask 3.1.3.

## Automatisés

```sh
.venv/bin/python -m pytest tests/ -q
```

Résultat : **60 tests, tous réussis**.

- V1 + B + C + D + E + F inchangés (`user_version` jusqu’à 6).
- Profil / mot de passe / tableau de bord : `tests/test_profile.py`.

## Limitations

- Pas de chiffrement au repos.
- ZIP V1 toujours absent du workspace.
