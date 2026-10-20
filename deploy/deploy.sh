#!/usr/bin/env bash
# Déploiement idempotent sur le VPS. Appelé par GitHub Actions (SSH) ou à la main.
# Prérequis : dépôt déjà cloné, venv créé, unité systemd installée (voir DEPLOY.md).
set -euo pipefail

APP_DIR="${FOYER_APP_DIR:-/opt/foyer}"
BRANCH="${FOYER_DEPLOY_BRANCH:-main}"
REMOTE="${FOYER_DEPLOY_REMOTE:-origin}"
SERVICE="${FOYER_SERVICE_NAME:-foyer}"

cd "$APP_DIR"

if [ ! -d .git ]; then
  echo "Pas de dépôt git dans $APP_DIR — suivez le bootstrap de DEPLOY.md." >&2
  exit 1
fi

echo "==> git fetch/reset ($REMOTE/$BRANCH)"
git fetch --prune "$REMOTE" "$BRANCH"
git checkout "$BRANCH"
git reset --hard "$REMOTE/$BRANCH"

if [ ! -x .venv/bin/python ]; then
  echo "==> création du venv"
  python3 -m venv .venv
fi

echo "==> pip sync (requirements.txt)"
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt

echo "==> restart $SERVICE"
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-enabled --quiet "$SERVICE" 2>/dev/null || systemctl cat "$SERVICE" >/dev/null 2>&1; then
    if sudo -n systemctl restart "$SERVICE" 2>/dev/null; then
      sudo -n systemctl --no-pager --full status "$SERVICE" || true
    else
      systemctl --user restart "$SERVICE" 2>/dev/null \
        || systemctl restart "$SERVICE"
      systemctl --no-pager --full status "$SERVICE" || true
    fi
  else
    echo "Unité $SERVICE absente — redémarrez le processus manuellement (voir DEPLOY.md)." >&2
  fi
else
  echo "systemctl indisponible — redémarrez launcher.py manuellement." >&2
fi

echo "==> deploy OK ($(git rev-parse --short HEAD))"
