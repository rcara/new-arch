# New Arch

Home OS local-first pour un foyer : accueil transversal, organisation, calendrier, repères, décisions scellées, coffre.  
Le cadrage V2 est dans [`docs/v2/`](docs/v2/). Journal : [`CHANGELOG.md`](CHANGELOG.md).

Le guide d'usage, de sauvegarde et les limites sont dans [GUIDE.md](GUIDE.md).  
La matrice exigences → modules → tests est dans [MATRICE.md](MATRICE.md).  
Déploiement GitHub Actions → VPS + Cloudflare Tunnel : [DEPLOY.md](DEPLOY.md).

## Démarrage

Windows, dans ce dossier :

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
lancer.bat
```

Linux :

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./lancer.sh
```

L'application écoute sur `http://127.0.0.1:8765/`. Si le port est pris, le lanceur s'arrête avec un message explicite. Un autre port : `FOYER_PORT=8766`. Un autre dossier de données : `FOYER_HOME`.

`FOYER_NO_BROWSER=1` empêche l'ouverture automatique du navigateur.

Sauvegarde et restauration : `python cli.py backup` et `python cli.py restore <archive> <dossier-neuf>`.

## Tests

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

## État V2 (B + C)

Livré : foyer/personnes/permissions V1, liens, tâches, événements, recherche, accueil, **finances** (splits, remboursements, CHF/EUR, budgets, CSV), migrations `003`–`004`.  
Backlog : inventaire, médiathèque, light mode, chiffrement au repos (toujours **absent** — voir GUIDE).

**ZIP spécification V1** (`Foyer_Local_V1_Complet`) : non présent dans ce dépôt au moment de l'audit ; l'audit s'appuie sur le code et la doc livrée.
