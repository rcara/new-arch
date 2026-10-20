# New Arch

Application locale pour un foyer : repères, décisions scellées, pièces au coffre.
Le nom est provisoire. Ce dossier ne modifie aucun site existant.

Le guide d'usage, de sauvegarde et les limites du MVP sont dans [GUIDE.md](GUIDE.md).
La matrice exigences → modules → tests est dans [MATRICE.md](MATRICE.md).
Le compte rendu d'exécution est dans [RAPPORT-TESTS.md](RAPPORT-TESTS.md).
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
