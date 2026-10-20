"""Horloge civile et statuts, sans base."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.clock import FrozenClock, civil_today
from app.errors import AppError
from app.present import notice_date, status_for
from app.validate import due_date_value


TODAY = date(2027, 2, 20)


@pytest.mark.parametrize("delta,expected", [
    (-1, "expire"),
    (0, "sous_30"),
    (30, "sous_30"),
    (31, "sous_90"),
    (90, "sous_90"),
    (91, "a_jour"),
])
def test_bornes_de_statut(delta, expected):
    assert status_for(TODAY + timedelta(days=delta), TODAY) == expected


def test_sans_date_et_preavis_informatif():
    assert status_for(None, TODAY) == "sans_date"
    assert notice_date("2027-03-15", 30) == "2027-02-13"
    assert status_for("2027-03-15", TODAY) == "sous_30"


def test_dates_calendaires():
    assert due_date_value("2024-02-29") == "2024-02-29"
    with pytest.raises(AppError):
        due_date_value("2027-02-31")


def test_minuit_et_heure_d_ete_europe_berlin():
    def seen(stamp):
        moment = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        return civil_today(FrozenClock(moment), "Europe/Berlin")

    assert seen("2027-03-27T22:30:00") == date(2027, 3, 27)
    assert seen("2027-03-27T23:30:00") == date(2027, 3, 28)
    assert seen("2027-03-28T00:30:00") == date(2027, 3, 28)
    assert seen("2027-03-28T01:30:00") == date(2027, 3, 28)
    assert seen("2027-10-30T22:30:00") == date(2027, 10, 31)
    assert seen("2027-10-31T00:30:00") == date(2027, 10, 31)
    assert seen("2027-10-31T01:30:00") == date(2027, 10, 31)
