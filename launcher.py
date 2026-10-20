"""Lanceur local. N'écoute jamais en dehors de 127.0.0.1."""

import os
import signal
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from app import create_app

ROOT = Path(__file__).resolve().parent


def port_is_free(port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def main():
    port = int(os.environ.get("FOYER_PORT", "8765"))
    if not port_is_free(port):
        print(f"Le port {port} est déjà occupé. Arrêtez l'autre programme, ou choisissez un autre port avec FOYER_PORT.", file=sys.stderr)
        return 1
    home = Path(os.environ.get("FOYER_HOME", ROOT))
    app = create_app(home=home, port=port)
    pid = home / "data" / "foyer.pid"
    pid.write_text(str(os.getpid()), encoding="utf-8")
    url = f"http://127.0.0.1:{port}/"
    if os.environ.get("FOYER_NO_BROWSER") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    from waitress import create_server
    server = create_server(app, host="127.0.0.1", port=port, threads=4, ident="foyer")
    def stop(_signum, _frame):
        server.close()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"Plateforme foyer écoute sur {url}", flush=True)
    try:
        server.run()
    finally:
        pid.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
