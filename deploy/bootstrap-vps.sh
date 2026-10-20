#!/usr/bin/env bash
# Bootstrap manuel (une fois) sur le VPS. À lancer en root ou avec sudo.
# Usage :
#   export FOYER_REPO_URL=https://github.com/rcara/new-arch.git
#   export FOYER_DEPLOY_USER=deploy   # utilisateur SSH de GitHub Actions
#   sudo -E bash deploy/bootstrap-vps.sh
set -euo pipefail

APP_DIR="${FOYER_APP_DIR:-/opt/foyer}"
REPO_URL="${FOYER_REPO_URL:-https://github.com/rcara/new-arch.git}"
APP_USER="${FOYER_APP_USER:-foyer}"
DEPLOY_USER="${FOYER_DEPLOY_USER:-}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Exécutez en root (sudo)." >&2
  exit 1
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install -U pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod +x "$APP_DIR/deploy/deploy.sh" "$APP_DIR/lancer.sh" || true

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

echo "Bootstrap OK. Vérifiez : curl -H 'Host: 127.0.0.1:8765' http://127.0.0.1:8765/connexion"
echo "Ensuite : Cloudflare Tunnel (DEPLOY.md) + secrets GitHub."
