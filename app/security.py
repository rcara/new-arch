"""Mots de passe Argon2id, jetons de session, limite de tentatives."""

import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

# Paramètres OWASP pour Argon2id : m=19456, t=2, p=1, hash 32, sel 16.
# Mesure du 20 octobre 2026 sur cette machine : environ 0,03 s par empreinte.
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)
SESSION_HOURS = 8


def hash_password(password):
    return HASHER.hash(password)


def verify_password(stored, password):
    try:
        return HASHER.verify(stored, password)
    except VerificationError:
        return False


def needs_rehash(stored):
    try:
        return HASHER.check_needs_rehash(stored)
    except VerificationError:
        return False


def new_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AttemptLimiter:
    """Compteur glissant. Le blocage expire ; il n'est jamais définitif."""

    def __init__(self, per_user=8, global_limit=40, window=900):
        self.per_user = per_user
        self.global_limit = global_limit
        self.window = window
        self.events = []
        self.now = time.monotonic

    def _prune(self):
        now = self.now()
        self.events = [item for item in self.events if now - item[0] < self.window]

    def too_many(self, username):
        self._prune()
        own = sum(1 for _, name in self.events if name == username)
        return own >= self.per_user or len(self.events) >= self.global_limit

    def add(self, username):
        self._prune()
        self.events.append((self.now(), username))

    def clear_user(self, username):
        self.events = [item for item in self.events if item[1] != username]
