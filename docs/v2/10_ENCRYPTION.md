# Chiffrement au repos (tranche 1)

## Objectif

Protéger le **contenu des fichiers** du coffre et de la médiathèque contre un accès disque hors application, sans prétendre chiffrer toute la base (D08 — pas de cosmétique).

## Périmètre chiffré

| Surface | État |
|---|---|
| `vault/objects/*` | AES-256-GCM (`NAE1…`) si activé |
| `media/objects/*` | idem |
| `data/metadata.sqlite` | **clair** (métadonnées, ACL, montants) |
| `logs/` | **clair** |
| `data/crypto.json` | sel + DEK enveloppée (pas la phrase) |

## Mécanisme

1. Phrase secrète (≥12) → KEK via Argon2id (64 MiB, t=3).
2. DEK aléatoire 256 bits enveloppée (AES-GCM) dans `crypto.json`.
3. Blobs : `NAE1 || nonce(12) || ciphertext+tag`.
4. Empreintes SQLite = sha256 du **clair** ; le disque porte le scellé.
5. Runtime : `FOYER_PASSPHRASE` déverrouille la DEK en mémoire.

## CLI

```sh
python cli.py crypto status
python cli.py crypto enable    # active + migre les blobs existants
python cli.py crypto migrate   # chiffre les clairs restants
```

Démarrage avec chiffrement :

```sh
export FOYER_PASSPHRASE='…'
./lancer.sh
```

Sans phrase : l’UI fonctionne, mais l’ouverture d’un blob scellé renvoie une erreur explicite (503).

## Sauvegarde

Les archives emportent les blobs scellés + `crypto.json`. La restauration exige ensuite `FOYER_PASSPHRASE` pour lire les pièces.

## Non-objectifs (tranche suivante)

- SQLCipher / chiffrement de la base entière
- Changement de phrase (rewrap) UI
- TPM / clé matérielle
