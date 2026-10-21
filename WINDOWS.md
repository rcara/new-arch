# Exploitation Windows

Guide de lancement, sauvegarde et restauration sur Windows (New Arch V2).

## Prérequis

- Python 3.12+ (`py -3 --version`)
- Droits d’écriture dans le dossier du projet (ou un `FOYER_HOME` dédié)

## Installation

Dans le dossier du dépôt :

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Pour développer / lancer les tests :

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

## Lancement

```bat
lancer.bat
```

Équivalent :

```bat
.venv\Scripts\python launcher.py
```

L’application écoute sur `http://127.0.0.1:8765/` (local uniquement).

| Variable | Effet |
|---|---|
| `FOYER_PORT` | Autre port (ex. `8766`) |
| `FOYER_HOME` | Dossier de données (sinon le dossier du projet) |
| `FOYER_NO_BROWSER=1` | N’ouvre pas le navigateur |

Exemple PowerShell :

```powershell
$env:FOYER_HOME = "D:\FoyerData"
$env:FOYER_NO_BROWSER = "1"
.\lancer.bat
```

## Sauvegarde

Pendant que l’application tourne (ou à l’arrêt) :

```bat
.venv\Scripts\python cli.py backup
```

Produit un dossier `backups\foyer-AAAAMMJJTHHMMSSZ\` contenant :

- `metadata.sqlite` (snapshot cohérent)
- `objects\` — pièces du coffre (`vault/objects`)
- `media\` — fichiers de la médiathèque (`media/objects`)
- `manifest.json` — empreintes sha256 + `schema_version`

Ne copiez **pas** seulement le fichier SQLite : les pièces seraient perdues.

## Restauration

1. Arrêtez l’application (fermez le lanceur).
2. Choisissez un **dossier neuf et vide**.
3. Lancez :

```bat
.venv\Scripts\python cli.py restore backups\foyer-... D:\FoyerRestaure
```

4. Relancez avec `FOYER_HOME` pointant vers le dossier restauré.
5. Reconnectez-vous (les sessions sont révoquées) et vérifiez un repère, une décision et une pièce.

Deux foyers ne se fusionnent pas. Ne restaurez jamais par-dessus un foyer en cours.

## Dataset de démonstration

Uniquement sur un dossier **sans foyer** (nouveau `FOYER_HOME` vide) :

```bat
set FOYER_HOME=D:\FoyerDemo
.venv\Scripts\python cli.py seed-demo
```

Comptes fictifs (non sensibles) :

- `alex` / `DemoFoyer-2026!`
- `camille` / `DemoCamille-2026!`

Refuse si un foyer existe déjà. Ne pas utiliser pour un foyer réel.

## Thème clair / sombre

Dans **Paramètres → Apparence**, choisissez Sombre (défaut) ou Clair. Le choix est stocké dans le cookie `foyer_theme` (pas de JavaScript).

## Exports CSV

- Finances : `/finances/export.csv` ou `GET /api/finance/export.csv`
- Inventaire : `/inventaire/export.csv` ou `GET /api/inventory/export.csv`

Montants en unités mineures (centimes), séparateur `;`.

## Arrêt

Fermez la fenêtre du lanceur, ou interrompez le processus. Le fichier `data\foyer.pid` est retiré à l’arrêt.

## Limites à rappeler

- Données en clair sur le disque (pas de chiffrement au repos).
- Accès prévu uniquement depuis `127.0.0.1`.
- Voir `GUIDE.md` pour le détail des limites MVP.
