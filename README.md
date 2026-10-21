# New Arch

Home OS local-first pour un foyer : accueil transversal, organisation, calendrier, finances, inventaire, médiathèque, repères, décisions scellées, coffre.  
Le cadrage V2 est dans [`docs/v2/`](docs/v2/). Journal : [`CHANGELOG.md`](CHANGELOG.md).

Le guide d'usage, de sauvegarde et les limites sont dans [GUIDE.md](GUIDE.md).  
Exploitation Windows : [WINDOWS.md](WINDOWS.md).  
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

Sauvegarde et restauration : `python cli.py backup` et `python cli.py restore <archive> <dossier-neuf>` (inclut coffre + média).  
Dataset démo (dossier vide) : `python cli.py seed-demo`.

## Tests

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

## État V2 (A → F)

Livré : foyer V1, socle B, finances C, inventaire D, médiathèque E, solidification F (thème, e2e, backup étendu, démo, doc Windows). Migrations `001`–`006`.

**ZIP spécification V1** (`Foyer_Local_V1_Complet`) : non présent dans ce dépôt au moment de l'audit ; l'audit s'appuie sur le code et la doc livrée.

Hors périmètre actuel : chiffrement au repos, multi-foyer runtime.
