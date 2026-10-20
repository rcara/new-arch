"""Le schéma livré reste exécutable. La migration 002 s'ajoute ensuite."""

import hashlib
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "migrations" / "001_schema.sql"
SPEC_HASH = "ab22368db6158bd48fd6a424495a5cd6f590cc2a5ee83fd7a8b5e5fb58d5e219"


def test_schema_inchange():
    data = SCHEMA.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SPEC_HASH


def test_contraintes_du_schema_initial():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    t = "2027-02-20T09:00:00Z"
    db.execute("INSERT INTO household VALUES(1,'Démo','Europe/Berlin',?)", (t,))
    _reject(db, "INSERT INTO household VALUES(2,'Autre','Europe/Berlin',?)", (t,))
    db.execute("INSERT INTO person(id,display_name,is_principal,created_at) VALUES(1,'Roger',1,?)", (t,))
    _reject(db, "INSERT INTO person(id,display_name,is_principal,created_at) VALUES(3,'Autre',1,?)", (t,))
    _reject(db, "UPDATE person SET active=0 WHERE id=1")
    db.execute("INSERT INTO milestone(id,name,category,holder_id,created_at,updated_at) VALUES(1,'Passeport','Identité',1,?,?)", (t, t))
    _reject(db, "UPDATE milestone SET category='Autre' WHERE id=1")
    _reject(db, "UPDATE milestone SET amount_cents=-1 WHERE id=1")
    db.execute("INSERT INTO decision(id,milestone_id,author_id,created_at) VALUES(1,1,1,?)", (t,))
    _reject(db, "INSERT INTO decision_result VALUES(1,1,'Fait',?)", (t,))
    _reject(db, "UPDATE decision SET milestone_id=999 WHERE id=1")
    db.execute("UPDATE decision SET choice='Renouveler', expected='Recevoir', reconsider_if='Délai', options_json='[\"Renouveler\",\"Ne rien faire\"]' WHERE id=1")
    db.execute("UPDATE decision SET sealed_at=? WHERE id=1", (t,))
    _reject(db, "UPDATE decision SET choice='Attendre' WHERE id=1")
    _reject(db, "DELETE FROM decision WHERE id=1")
    db.execute("INSERT INTO decision_result VALUES(1,1,'Reçu',?)", (t,))
    _reject(db, "INSERT INTO decision_result VALUES(1,1,'Encore',?)", (t,))
    query = """
    SELECT CASE WHEN m.due_date IS NULL THEN 'sans_date'
    WHEN m.due_date < :today THEN 'expire'
    WHEN m.due_date <= date(:today,'+30 days') THEN 'sous_30'
    WHEN m.due_date <= date(:today,'+90 days') THEN 'sous_90'
    ELSE 'a_jour' END AS status
    FROM milestone m WHERE m.archived=0 AND m.id=1
    """
    for delta, expected in [(-1, "expire"), (0, "sous_30"), (30, "sous_30"), (31, "sous_90"), (90, "sous_90"), (91, "a_jour"), (None, "sans_date")]:
        due = None if delta is None else str(date(2027, 2, 20) + timedelta(days=delta))
        db.execute("UPDATE milestone SET due_date=? WHERE id=1", (due,))
        assert db.execute(query, {"today": "2027-02-20"}).fetchone()[0] == expected
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def _reject(db, query, args=()):
    try:
        db.execute(query, args)
    except sqlite3.IntegrityError:
        return
    raise AssertionError(query)
