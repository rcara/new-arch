"""Sauvegarde, restauration et seed démo — l'application arrêtée pour restore."""

import os
import sys
from pathlib import Path

from app import Ctx, create_app
from app.clock import SystemClock
from app.db import connect
from app.security import AttemptLimiter
from app.services.backup import create_backup, restore_archive
from app.services.demo import seed_demo


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _running(home):
    pidfile = Path(home) / "data" / "foyer.pid"
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    return _alive(pid)


def _usage():
    return (
        "Usage :\n"
        "  python cli.py backup\n"
        "  python cli.py restore <archive> <dossier-neuf>\n"
        "  python cli.py seed-demo\n"
    )


def main(argv):
    home = Path(os.environ.get("FOYER_HOME", Path(__file__).resolve().parent))
    if len(argv) < 2 or argv[1] not in {"backup", "restore", "seed-demo"}:
        print(_usage(), file=sys.stderr)
        return 1
    if argv[1] == "backup":
        app = create_app(home=home)
        with app.app_context():
            from flask import g
            g.db = connect(home / "data" / "metadata.sqlite")
            ctx = Ctx(g.db, app.config["CLOCK"], home, app.config["LOCK"], app.config["DUMMY_HASH"])
            try:
                path = create_backup(ctx)
            finally:
                g.db.close()
        print(path)
        return 0
    if argv[1] == "seed-demo":
        if _running(home):
            print("Arrêtez l'application avant le seed démo.", file=sys.stderr)
            return 1
        app = create_app(home=home)
        with app.app_context():
            from flask import g
            g.db = connect(home / "data" / "metadata.sqlite")
            ctx = Ctx(g.db, app.config["CLOCK"], home, app.config["LOCK"], app.config["DUMMY_HASH"])
            try:
                info = seed_demo(ctx, AttemptLimiter())
            finally:
                g.db.close()
        print(
            f"Foyer démo prêt : {info['household']}\n"
            f"  compte : {info['username']} / {info['password']}\n"
            f"  second : {info['secondary_username']} / {info['secondary_password']}\n"
            "Données fictives uniquement — ne pas utiliser pour un foyer réel."
        )
        return 0
    if len(argv) != 4:
        print(_usage(), file=sys.stderr)
        return 1
    archive, dest = Path(argv[2]), Path(argv[3])
    if _running(dest):
        print("Arrêtez l'application avant de restaurer dans ce dossier.", file=sys.stderr)
        return 1
    path = restore_archive(archive, dest, SystemClock())
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
