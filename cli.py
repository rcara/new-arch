"""Sauvegarde, restauration, seed démo et chiffrement au repos."""

import getpass
import os
import sys
from pathlib import Path

from app import Ctx, create_app
from app.clock import SystemClock
from app.crypto import enable as crypto_enable
from app.crypto import load_state, migrate_tree, status as crypto_status, unlock
from app.db import connect
from app.errors import AppError
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
        "  python cli.py crypto status\n"
        "  python cli.py crypto enable\n"
        "  python cli.py crypto migrate\n"
        "\n"
        "Chiffrement : active AES-256-GCM sur vault/objects et media/objects.\n"
        "Déverrouillage runtime : variable d'environnement FOYER_PASSPHRASE.\n"
        "SQLite reste en clair (choix explicite, pas de cosmétique).\n"
    )


def _ask_passphrase(confirm=False):
    env = os.environ.get("FOYER_PASSPHRASE")
    if env:
        return env
    first = getpass.getpass("Phrase secrète du coffre (≥12) : ")
    if confirm:
        second = getpass.getpass("Confirmez la phrase secrète : ")
        if first != second:
            raise AppError(400, "validation", "Les deux saisies diffèrent.")
    return first


def _ctx(app, home):
    from flask import g
    g.db = connect(home / "data" / "metadata.sqlite")
    return Ctx(
        g.db, app.config["CLOCK"], home, app.config["LOCK"], app.config["DUMMY_HASH"],
        crypto=app.config.get("CRYPTO"),
    )


def main(argv):
    home = Path(os.environ.get("FOYER_HOME", Path(__file__).resolve().parent))
    if len(argv) < 2:
        print(_usage(), file=sys.stderr)
        return 1
    command = argv[1]
    if command not in {"backup", "restore", "seed-demo", "crypto"}:
        print(_usage(), file=sys.stderr)
        return 1

    if command == "crypto":
        if len(argv) < 3 or argv[2] not in {"status", "enable", "migrate"}:
            print(_usage(), file=sys.stderr)
            return 1
        action = argv[2]
        if action == "status":
            info = crypto_status(home)
            if not info["enabled"]:
                print("Chiffrement au repos : désactivé (blobs en clair).")
            else:
                print(
                    "Chiffrement au repos : activé\n"
                    f"  version={info['version']} kdf={info['kdf']}\n"
                    f"  périmètre={', '.join(info['scope'])}\n"
                    f"  sqlite_encrypted={info['sqlite_encrypted']} (volontairement faux)"
                )
                unlocked = load_state(home).unlocked
                print(f"  déverrouillé={unlocked} (FOYER_PASSPHRASE)")
            return 0
        if _running(home):
            print("Arrêtez l'application avant crypto enable/migrate.", file=sys.stderr)
            return 1
        if action == "enable":
            try:
                phrase = _ask_passphrase(confirm=True)
                state = crypto_enable(home, phrase)
                result = migrate_tree(state, home)
            except AppError as exc:
                print(exc.message, file=sys.stderr)
                return 1
            print(
                "Chiffrement activé. Définissez FOYER_PASSPHRASE pour démarrer l'application.\n"
                f"Blobs migrés : {result['encrypted']} "
                f"(déjà scellés/vides : {result['already_sealed_or_empty']})."
            )
            return 0
        # migrate
        try:
            phrase = _ask_passphrase()
            state = unlock(home, phrase)
            result = migrate_tree(state, home)
        except AppError as exc:
            print(exc.message, file=sys.stderr)
            return 1
        print(
            f"Migration : {result['encrypted']} fichier(s) chiffré(s), "
            f"{result['already_sealed_or_empty']} déjà scellé(s)."
        )
        return 0

    if command == "backup":
        app = create_app(home=home)
        with app.app_context():
            ctx = _ctx(app, home)
            try:
                path = create_backup(ctx)
            except AppError as exc:
                print(exc.message, file=sys.stderr)
                return 1
            finally:
                from flask import g
                g.db.close()
        print(path)
        return 0
    if command == "seed-demo":
        if _running(home):
            print("Arrêtez l'application avant le seed démo.", file=sys.stderr)
            return 1
        app = create_app(home=home)
        with app.app_context():
            ctx = _ctx(app, home)
            try:
                info = seed_demo(ctx, AttemptLimiter())
            finally:
                from flask import g
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
