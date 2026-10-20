#!/usr/bin/env bash
# Déploiement idempotent sur le VPS. Appelé par GitHub Actions (SSH) ou à la main.
# Prérequis : dépôt déjà cloné, venv créé, unité systemd installée (voir DEPLOY.md).
#
# Redémarrage : stop → attendre que 127.0.0.1:FOYER_PORT soit bindable → start.
# Évite la boucle systemd quand TIME-WAIT fait échouer le probe de launcher.py.
set -euo pipefail

APP_DIR="${FOYER_APP_DIR:-/opt/foyer}"
BRANCH="${FOYER_DEPLOY_BRANCH:-main}"
REMOTE="${FOYER_DEPLOY_REMOTE:-origin}"
SERVICE="${FOYER_SERVICE_NAME:-foyer}"
FOYER_PORT="${FOYER_PORT:-8765}"
FOYER_BIND_HOST="${FOYER_BIND_HOST:-127.0.0.1}"
FOYER_PORT_WAIT_SECS="${FOYER_PORT_WAIT_SECS:-90}"
FOYER_SERVICE_USER="${FOYER_SERVICE_USER:-foyer}"

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

# --- helpers systemd / port (TIME-WAIT) ---

SYSTEMCTL=()

resolve_systemctl() {
  if sudo -n systemctl cat "$SERVICE" >/dev/null 2>&1; then
    SYSTEMCTL=(sudo -n systemctl)
  elif systemctl --user cat "$SERVICE" >/dev/null 2>&1; then
    SYSTEMCTL=(systemctl --user)
  else
    SYSTEMCTL=(systemctl)
  fi
}

run_systemctl() {
  "${SYSTEMCTL[@]}" "$@"
}

# Bind probe sans SO_REUSEADDR : échoue tant qu'un TIME-WAIT ou un listener
# occupe le port (critère strict avant de relancer le service).
_port_bind_probe_py() {
  local py="$APP_DIR/.venv/bin/python"
  [ -x "$py" ] || py=python3
  "$py" -c 'import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind((host, port))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
' "$FOYER_BIND_HOST" "$FOYER_PORT"
}

port_is_bindable() {
  # Préférer l'utilisateur du service (foyer) ; sinon l'utilisateur qui déploie.
  if id "$FOYER_SERVICE_USER" >/dev/null 2>&1; then
    local py="$APP_DIR/.venv/bin/python"
    [ -x "$py" ] || py=python3
    if sudo -n -u "$FOYER_SERVICE_USER" "$py" -c 'import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind((host, port))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
' "$FOYER_BIND_HOST" "$FOYER_PORT" >/dev/null 2>&1; then
      return 0
    fi
  fi
  _port_bind_probe_py >/dev/null 2>&1
}

clear_stale_pid() {
  local pidfile="$APP_DIR/data/foyer.pid"
  if [ -f "$pidfile" ]; then
    echo "==> suppression PID périmé ($pidfile)"
    rm -f "$pidfile" || sudo -n rm -f "$pidfile" || true
  fi
}

kill_leftover_launcher() {
  # Optionnel : processus launcher encore vivant hors systemd.
  if pgrep -f "$APP_DIR/launcher.py" >/dev/null 2>&1; then
    echo "==> arrêt des processus launcher restants"
    pkill -TERM -f "$APP_DIR/launcher.py" 2>/dev/null \
      || sudo -n pkill -TERM -f "$APP_DIR/launcher.py" 2>/dev/null \
      || true
    sleep 1
    if pgrep -f "$APP_DIR/launcher.py" >/dev/null 2>&1; then
      pkill -KILL -f "$APP_DIR/launcher.py" 2>/dev/null \
        || sudo -n pkill -KILL -f "$APP_DIR/launcher.py" 2>/dev/null \
        || true
    fi
  fi
}

wait_until_port_bindable() {
  local waited=0
  echo "==> attente bind $FOYER_BIND_HOST:$FOYER_PORT (max ${FOYER_PORT_WAIT_SECS}s)"
  while [ "$waited" -lt "$FOYER_PORT_WAIT_SECS" ]; do
    if port_is_bindable; then
      echo "==> port $FOYER_PORT libre pour bind"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "ERREUR: impossible de binder $FOYER_BIND_HOST:$FOYER_PORT après ${FOYER_PORT_WAIT_SECS}s." >&2
  echo "Cause probable : TIME-WAIT TCP ou un autre processus écoute encore." >&2
  echo "Vérifiez : ss -ltnp 'sport = :$FOYER_PORT'  et  pgrep -af launcher.py" >&2
  ss -ltnp "sport = :$FOYER_PORT" 2>/dev/null || true
  pgrep -af launcher.py 2>/dev/null || true
  return 1
}

stop_then_start_service() {
  echo "==> stop $SERVICE"
  run_systemctl stop "$SERVICE" || true
  clear_stale_pid
  kill_leftover_launcher
  wait_until_port_bindable
  echo "==> start $SERVICE"
  run_systemctl start "$SERVICE"
  run_systemctl --no-pager --full status "$SERVICE" || true
}

echo "==> redémarrage propre $SERVICE (stop → wait port → start)"
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-enabled --quiet "$SERVICE" 2>/dev/null \
    || systemctl cat "$SERVICE" >/dev/null 2>&1 \
    || sudo -n systemctl cat "$SERVICE" >/dev/null 2>&1; then
    resolve_systemctl
    stop_then_start_service
  else
    echo "Unité $SERVICE absente — redémarrez le processus manuellement (voir DEPLOY.md)." >&2
  fi
else
  echo "systemctl indisponible — arrêtez launcher.py, attendez le port $FOYER_PORT, puis relancez." >&2
  clear_stale_pid
  kill_leftover_launcher
  wait_until_port_bindable
fi

echo "==> deploy OK ($(git rev-parse --short HEAD))"
