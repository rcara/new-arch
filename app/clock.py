"""Horloge injectable. Les dates civiles suivent le fuseau du foyer."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class SystemClock:
    def now(self):
        return datetime.now(timezone.utc).replace(microsecond=0)


class FrozenClock:
    def __init__(self, instant):
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        self.instant = instant.astimezone(timezone.utc).replace(microsecond=0)

    def now(self):
        return self.instant

    def advance(self, **kwargs):
        from datetime import timedelta
        self.instant = (self.instant + timedelta(**kwargs)).replace(microsecond=0)


def iso_utc(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def civil_today(clock, timezone_name):
    return clock.now().astimezone(ZoneInfo(timezone_name)).date()
