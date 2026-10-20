#!/usr/bin/env bash
# Bootstrap manuel (une fois) sur le VPS. À lancer en root ou avec sudo.
# Usage :
#   export FOYER_REPO_URL=https://github.com/rcara/new-arch.git
#   export FOYER_GIT_REF=cursor/github-vps-deploy-3fe0   # ou main après merge
#   export FOYER_DEPLOY_USER=deploy   # utilisateur SSH de GitHub Actions
#   sudo -E bash deploy/bootstrap-vps.sh
set -euo pipefail

APP_DIR="${FOYER_APP_DIR:-/opt/foyer}"
REPO_URL="${FOYER_REPO_URL:-https://github.com/rcara/new-arch.git}"
GIT_REF="${FOYER_GIT_REF:-}"
APP_USER="${FOYER_APP_USER:-foyer}"
DEPLOY_USER="${FOYER_DEPLOY_USER:-}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Exécutez en root (sudo)." >&2
  exit 1
fi

ensure_python_venv() {
  local pyver minor pkg
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 introuvable. Installez-le (ex. apt install python3) puis relancez." >&2
    exit 1
  fi
  # Déjà utilisable ?
  if python3 -m venv --help >/dev/null 2>&1; then
    local probe
    probe="$(mktemp -d)"
    if python3 -m venv "$probe/t" >/dev/null 2>&1; then
      rm -rf "$probe"
      return 0
    fi
    rm -rf "$probe"
  fi

  pyver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  minor="$(python3 -c 'import sys; print(sys.version_info.minor)')"
  # Ubuntu : python3.14-venv (ou python3-venv sur versions plus anciennes)
  pkg="python3.${minor}-venv"
  echo "==> ensurepip / venv manquant — installation apt de $pkg (et python3-venv si dispo)"
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get absent. Installez manuellement le paquet venv pour Python $pyver (ex. $pkg), puis relancez." >&2
    exit 1
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  if ! apt-get install -y "$pkg" python3-venv 2>/dev/null; then
    # python3-venv peut être un métapaquet absent ; réessayer le paquet versionné seul
    if ! apt-get install -y "$pkg"; then
      echo "Échec apt install $pkg. Sur Ubuntu avec Python $pyver : sudo apt install $pkg" >&2
      exit 1
    fi
  fi

  local probe
  probe="$(mktemp -d)"
  if ! python3 -m venv "$probe/t" >/dev/null 2>&1; then
    rm -rf "$probe"
    echo "python3 -m venv échoue encore après apt. Vérifiez : sudo apt install $pkg" >&2
    exit 1
  fi
  rm -rf "$probe"
}

checkout_ref() {
  local ref="$1"
  if [ -z "$ref" ]; then
    return 0
  fi
  echo "==> checkout FOYER_GIT_REF=$ref"
  git -C "$APP_DIR" fetch --prune origin "+refs/heads/*:refs/remotes/origin/*" "+refs/tags/*:refs/tags/*" || \
    git -C "$APP_DIR" fetch --prune origin
  # Branche distante, tag, ou SHA
  if git -C "$APP_DIR" show-ref --verify --quiet "refs/remotes/origin/$ref"; then
    git -C "$APP_DIR" checkout -B "$ref" "origin/$ref"
  elif git -C "$APP_DIR" rev-parse --verify --quiet "$ref^{commit}" >/dev/null; then
    git -C "$APP_DIR" checkout --detach "$ref"
  else
    echo "FOYER_GIT_REF='$ref' introuvable dans $REPO_URL (ni branche origin/$ref, ni tag/SHA)." >&2
    echo "Avant le merge de la PR deploy, utilisez par ex. FOYER_GIT_REF=cursor/github-vps-deploy-3fe0" >&2
    exit 1
  fi
}

require_deploy_files() {
  if [ ! -f "$APP_DIR/deploy/deploy.sh" ] || [ ! -f "$APP_DIR/deploy/foyer.service" ]; then
    echo "deploy/deploy.sh ou deploy/foyer.service absents dans $APP_DIR." >&2
    echo "La branche checkoutée n'inclut pas encore le dossier deploy/." >&2
    echo "Relancez avec FOYER_GIT_REF pointant vers la branche/PR deploy (ex. cursor/github-vps-deploy-3fe0)," >&2
    echo "ou attendez le merge sur main." >&2
    exit 1
  fi
}

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  echo "==> git clone $REPO_URL → $APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi

checkout_ref "$GIT_REF"
require_deploy_files

ensure_python_venv

echo "==> venv + pip"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install -U pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod +x "$APP_DIR/deploy/deploy.sh" "$APP_DIR/deploy/bootstrap-vps.sh" "$APP_DIR/lancer.sh" || true

# Unité systemd
install -m 644 "$APP_DIR/deploy/foyer.service" /etc/systemd/system/foyer.service
systemctl daemon-reload
systemctl enable --now foyer

if [ -n "$DEPLOY_USER" ] && id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  # Le user Actions peut mettre à jour le code et redémarrer le service.
  usermod -aG "$APP_USER" "$DEPLOY_USER" || true
  cat >/etc/sudoers.d/foyer-deploy <<EOF
# Généré par bootstrap-vps.sh — redémarrage foyer uniquement
$DEPLOY_USER ALL=(root) NOPASSWD: /bin/systemctl restart foyer, /bin/systemctl status foyer, /bin/systemctl is-active foyer
EOF
  chmod 440 /etc/sudoers.d/foyer-deploy
  # Accès écriture au dépôt (groupe foyer)
  chmod -R g+rwX "$APP_DIR"
  chmod g+s "$APP_DIR" || true
fi

echo "Bootstrap OK (ref=$(git -C "$APP_DIR" rev-parse --short HEAD))."
echo "Vérifiez : curl -H 'Host: 127.0.0.1:8765' http://127.0.0.1:8765/connexion"
echo "Ensuite : Cloudflare Tunnel (DEPLOY.md) + secrets GitHub."
