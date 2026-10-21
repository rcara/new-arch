# Rapport de tests — 21 octobre 2026 (New Arch V2 B+C+D)

Machine : Linux, Python 3.12.3, Flask 3.1.3.

## Automatisés

```sh
.venv/bin/python -m pytest tests/ -q
```

Résultat : **48 tests, tous réussis**.

- V1 + B + C inchangés (`user_version` jusqu’à 5).
- Inventaire : lieux/biens, lien achat finance, garantie → événement calendrier, maintenance, confidentialité privée, cession/historique, UI `/inventaire`.

## Limitations

- Médiathèque non livrée (étape E).
- Pas de chiffrement au repos.
- ZIP V1 toujours absent du workspace.
