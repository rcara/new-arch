# Déploiement GitHub → VPS (Cloudflare Tunnel)

L’application écoute **uniquement** `127.0.0.1:8765`. Elle n’est **pas** exposée sur `0.0.0.0`.  
L’accès public passe par un **Cloudflare Tunnel** (`cloudflared`) vers le loopback. **Pas besoin d’ouvrir les ports 80/443** sur le pare-feu du VPS.

```
GitHub Actions (main + CI OK)
  → SSH → VPS → deploy/deploy.sh (git reset + pip + systemctl restart foyer)
  → cloudflared → http://127.0.0.1:8765
  → HTTPS sur votre domaine Cloudflare
```

VPS cible prévu : `188.245.26.201`. Chemin d’install par défaut : `/opt/foyer`.

---

## 1. Secrets GitHub (à créer par le propriétaire du dépôt)

Settings → Secrets and variables → Actions :

| Secret | Exemple | Obligatoire |
|---|---|---|
| `VPS_HOST` | `188.245.26.201` | oui |
| `VPS_USER` | `deploy` (ou `ubuntu` / `root`) | oui |
| `VPS_SSH_KEY` | clé **privée** ed25519 dédiée au deploy | oui |
| `VPS_SSH_PORT` | `22` | non (défaut 22) |

Ne jamais committer de clés, tokens Cloudflare ou `credentials.json`.

Sur le VPS, la clé **publique** correspondante va dans `~/.ssh/authorized_keys` de `VPS_USER`.

---

## 2. Bootstrap VPS (une fois, manuellement)

Sur le serveur (Ubuntu typique) :

```bash
# paquets de base (git suffit ; le script installe python3.X-venv si besoin)
sudo apt-get update
sudo apt-get install -y git python3

# Python 3.14+ : le métapaquet python3-venv ne suffit souvent pas —
# il faut python3.14-venv (ensurepip). bootstrap-vps.sh le fait via apt,
# ou manuellement : sudo apt-get install -y python3.14-venv

# cloner + user système + systemd
export FOYER_REPO_URL=https://github.com/rcara/new-arch.git
export FOYER_APP_DIR=/opt/foyer
export FOYER_DEPLOY_USER=deploy   # utilisateur SSH utilisé par Actions
# Tant que deploy/ n'est pas sur main, pointer la branche/PR :
export FOYER_GIT_REF=cursor/github-vps-deploy-3fe0
sudo -E bash -c 'git clone "$FOYER_REPO_URL" /tmp/foyer-src && \
  git -C /tmp/foyer-src checkout "$FOYER_GIT_REF" && \
  bash /tmp/foyer-src/deploy/bootstrap-vps.sh'
```

`FOYER_GIT_REF` (optionnel) : après clone dans `FOYER_APP_DIR`, le script fait
`fetch` + checkout de cette branche / tag / SHA. Sans ref, on garde le défaut du
clone (`main`). Si `deploy/deploy.sh` ou `foyer.service` manquent, le script
s’arrête avec un message clair (cas typique : `main` avant le merge de cette PR).

Ou, si le dépôt est déjà présent :

```bash
cd /opt/foyer
sudo -E FOYER_DEPLOY_USER=deploy FOYER_GIT_REF=cursor/github-vps-deploy-3fe0 \
  bash deploy/bootstrap-vps.sh
# si deploy/ est encore absent sur le checkout actuel, récupérez le script depuis la branche :
#   git fetch origin cursor/github-vps-deploy-3fe0
#   sudo -E FOYER_GIT_REF=... bash <(git show origin/cursor/github-vps-deploy-3fe0:deploy/bootstrap-vps.sh)
```

Vérification locale sur le VPS :

```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Host: 127.0.0.1:8765" http://127.0.0.1:8765/connexion
# attendu : 200
sudo systemctl status foyer
```

Fichiers utiles dans `deploy/` :

- `foyer.service` — unité systemd (User=`foyer`, `FOYER_NO_BROWSER=1`)
- `deploy.sh` — script idempotent appelé par Actions
- `bootstrap-vps.sh` — première installation (`FOYER_GIT_REF`, apt `python3.X-venv`)
- `cloudflared.service` + `cloudflared.yml.example`

---

## 3. Cloudflare Tunnel

1. Dans Cloudflare Zero Trust → Networks → Tunnels : **Create a tunnel** (cloudflared).
2. Installer `cloudflared` sur le VPS (paquet officiel ou binaire dans `/usr/local/bin/cloudflared`).
3. Associer le tunnel (login / token / fichier credentials — **hors git**).
4. Configurer l’ingress vers `http://127.0.0.1:8765` (voir `deploy/cloudflared.yml.example`).
5. DNS : enregistrement CNAME du hostname public vers le tunnel  
   (ex. `new-arch.arscodicis.net`).
6. Dans `foyer.service`, définir le Host/Origin publics (sinon **« Hôte refusé »**) :

```ini
Environment=FOYER_PUBLIC_HOST=new-arch.arscodicis.net
Environment=FOYER_PUBLIC_ORIGIN=https://new-arch.arscodicis.net
```

   Puis `sudo systemctl daemon-reload && sudo systemctl restart foyer`.
7. Activer le service tunnel : `sudo systemctl enable --now cloudflared`.

**Pare-feu :** laissez 80/443 fermés si tout passe par le Tunnel. Gardez SSH (22 ou votre port) restreint (idéalement IP admin / fail2ban).

L’app continue d’exiger `REMOTE_ADDR == 127.0.0.1` (cloudflared en loopback). Seuls Host/Origin acceptés changent via ces variables.

> Cookie de session sans attribut `Secure` : l’app a été conçue pour HTTP local. Derrière Cloudflare en HTTPS, prévoyez éventuellement un ajustement cookie plus tard ; ce n’est pas requis pour le premier tunnel.

---

## 4. Pipeline GitHub

- **CI** (`.github/workflows/ci.yml`) : `pytest` sur chaque PR et chaque push `main` (Python 3.12).
- **Deploy** (`.github/workflows/deploy.yml`) : après un **CI réussi** sur un **push** `main`, SSH et exécution de `/opt/foyer/deploy/deploy.sh`.

Premier deploy automatique : une fois bootstrap + secrets OK, un merge sur `main` suffit.

Déploy manuel de secours sur le VPS :

```bash
sudo FOYER_APP_DIR=/opt/foyer /opt/foyer/deploy/deploy.sh
```

---

## 5. Variables d’environnement app (rappels)

| Variable | Défaut | Rôle |
|---|---|---|
| `FOYER_HOME` | répertoire du dépôt | données (`data/`, `vault/`, …) |
| `FOYER_PORT` | `8765` | port loopback |
| `FOYER_NO_BROWSER` | — | `1` en prod (systemd) |
| `FOYER_PUBLIC_HOST` | `127.0.0.1:{port}` | valeur attendue de l’en-tête `Host` (domaine Tunnel, sans `https://`) |
| `FOYER_PUBLIC_ORIGIN` | `http://127.0.0.1:{port}` | valeur attendue de `Origin` sur POST (ex. `https://new-arch.arscodicis.net`) |

L’écoute reste `127.0.0.1` dans `launcher.py` — **ne pas** binder `0.0.0.0` pour publier le service.

---

## Checklist Roger

1. User SSH + clé deploy dédiée (`VPS_USER` / `VPS_SSH_KEY`)
2. Secrets GitHub renseignés
3. Bootstrap `/opt/foyer` + `systemctl enable --now foyer`
4. Domaine dans Cloudflare + Tunnel → `127.0.0.1:8765`
5. Merge sur `main` et vérifier Actions → Deploy
