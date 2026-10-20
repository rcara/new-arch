"""Journal technique : action, identifiants, date, résultat. Jamais de contenu."""

import os

from .clock import iso_utc


def audit(home, clock, action, result, person_id=None, object_type=None, object_id=None):
    path = home / "logs" / "audit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"{iso_utc(clock.now())} {action} "
        f"person={person_id if person_id is not None else '-'} "
        f"object={object_type or '-'}:{object_id if object_id is not None else '-'} "
        f"result={result}\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    if os.name == "posix":
        os.chmod(path, 0o600)
