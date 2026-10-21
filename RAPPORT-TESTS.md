# Rapport de tests — 21 octobre 2026 (New Arch V2 A→F)

Machine : Linux, Python 3.12.3, Flask 3.1.3.

## Automatisés

```sh
.venv/bin/python -m pytest tests/ -q
```

Résultat : **68 tests, tous réussis** (branche chiffrement).

- V1 + B→F + profil + branding + crypto blobs (`user_version` jusqu’à 7).
- Crypto : `tests/test_crypto.py` (enable, migrate, backup scellé).

## Limitations

- SQLite non chiffré (volontaire).
- ZIP V1 toujours absent du workspace.
