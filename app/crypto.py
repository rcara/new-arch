"""Chiffrement au repos des blobs (coffre + média) — AES-256-GCM, KEK Argon2id.

Honnêteté (D08) : la base SQLite et les journaux restent en clair. Seuls les
fichiers sous vault/objects et media/objects sont chiffrés lorsque le mode
est activé. Sans phrase secrète au démarrage, l'application refuse d'ouvrir
les blobs chiffrés.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import AppError

MAGIC = b"NAE1"
META_NAME = "crypto.json"
# Argon2id params aligned with password hashing spirit (local machine).
KDF_TIME = 3
KDF_MEMORY_KIB = 65536  # 64 MiB
KDF_PARALLELISM = 1
SALT_LEN = 16
NONCE_LEN = 12
DEK_LEN = 32


@dataclass
class CryptoState:
    enabled: bool
    dek: bytes | None = None  # None si désactivé ou non déverrouillé

    @property
    def unlocked(self):
        return (not self.enabled) or (self.dek is not None)


def meta_path(home):
    return Path(home) / "data" / META_NAME


def is_ciphertext(data: bytes) -> bool:
    return isinstance(data, (bytes, bytearray)) and len(data) >= 4 + NONCE_LEN + 16 and data[:4] == MAGIC


def _kdf(passphrase: str, salt: bytes) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) < 12:
        raise AppError(400, "validation", "La phrase secrète doit contenir au moins 12 caractères.")
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=KDF_TIME,
        memory_cost=KDF_MEMORY_KIB,
        parallelism=KDF_PARALLELISM,
        hash_len=DEK_LEN,
        type=Type.ID,
    )


def _read_meta(home):
    path = meta_path(home)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_meta(home, meta):
    path = meta_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    if os.name == "posix":
        os.chmod(path, 0o600)


def status(home):
    meta = _read_meta(home)
    if meta is None or not meta.get("enabled"):
        return {"enabled": False, "version": 0}
    return {
        "enabled": True,
        "version": int(meta.get("version", 1)),
        "kdf": meta.get("kdf", "argon2id"),
        "scope": meta.get("scope", ["vault/objects", "media/objects"]),
        "sqlite_encrypted": False,
    }


def enable(home, passphrase):
    """Active le chiffrement : génère une DEK, l'enveloppe avec la phrase secrète."""
    if status(home)["enabled"]:
        raise AppError(409, "conflict", "Le chiffrement au repos est déjà activé.")
    salt = secrets.token_bytes(SALT_LEN)
    kek = _kdf(passphrase, salt)
    dek = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(NONCE_LEN)
    wrapped = AESGCM(kek).encrypt(nonce, dek, b"new-arch-dek-v1")
    meta = {
        "version": 1,
        "enabled": True,
        "kdf": "argon2id",
        "kdf_time": KDF_TIME,
        "kdf_memory_kib": KDF_MEMORY_KIB,
        "kdf_parallelism": KDF_PARALLELISM,
        "salt": salt.hex(),
        "wrap_nonce": nonce.hex(),
        "wrapped_dek": wrapped.hex(),
        "scope": ["vault/objects", "media/objects"],
        "sqlite_encrypted": False,
        "notes": "SQLite et journaux restent en clair volontairement (pas de cosmétique).",
    }
    _write_meta(home, meta)
    return CryptoState(enabled=True, dek=dek)


def unlock(home, passphrase) -> CryptoState:
    meta = _read_meta(home)
    if meta is None or not meta.get("enabled"):
        return CryptoState(enabled=False, dek=None)
    try:
        salt = bytes.fromhex(meta["salt"])
        nonce = bytes.fromhex(meta["wrap_nonce"])
        wrapped = bytes.fromhex(meta["wrapped_dek"])
    except (KeyError, ValueError) as exc:
        raise AppError(500, "storage", "Métadonnées de chiffrement invalides.") from exc
    kek = _kdf(passphrase, salt)
    try:
        dek = AESGCM(kek).decrypt(nonce, wrapped, b"new-arch-dek-v1")
    except Exception as exc:
        raise AppError(401, "unauthorized", "Phrase secrète incorrecte.") from exc
    if len(dek) != DEK_LEN:
        raise AppError(500, "storage", "Clé de données invalide.")
    return CryptoState(enabled=True, dek=dek)


def load_state(home, passphrase=None) -> CryptoState:
    """Charge l'état : désactivé, ou déverrouillé via phrase / FOYER_PASSPHRASE."""
    meta = _read_meta(home)
    if meta is None or not meta.get("enabled"):
        return CryptoState(enabled=False, dek=None)
    secret = passphrase if passphrase is not None else os.environ.get("FOYER_PASSPHRASE")
    if not secret:
        # Mode activé mais non déverrouillé — lectures chiffrées échoueront clairement.
        return CryptoState(enabled=True, dek=None)
    return unlock(home, secret)


def seal(state: CryptoState, plaintext: bytes) -> bytes:
    """Chiffre si activé+déverrouillé ; sinon renvoie le clair."""
    if not state.enabled:
        return plaintext
    if state.dek is None:
        raise AppError(503, "storage", "Coffre verrouillé : définissez FOYER_PASSPHRASE.")
    nonce = secrets.token_bytes(NONCE_LEN)
    ct = AESGCM(state.dek).encrypt(nonce, plaintext, MAGIC)
    return MAGIC + nonce + ct


def open_blob(state: CryptoState, data: bytes) -> bytes:
    """Déchiffre un blob NAE1 ; laisse passer le clair historique."""
    if not is_ciphertext(data):
        return data
    if not state.enabled or state.dek is None:
        raise AppError(503, "storage", "Fichier chiffré : déverrouillez avec FOYER_PASSPHRASE.")
    nonce = data[4:4 + NONCE_LEN]
    ct = data[4 + NONCE_LEN:]
    try:
        return AESGCM(state.dek).decrypt(nonce, ct, MAGIC)
    except Exception as exc:
        raise AppError(500, "storage", "Déchiffrement impossible.") from exc


def require_unlocked(state: CryptoState):
    if state.enabled and state.dek is None:
        raise AppError(503, "storage", "Coffre verrouillé : définissez FOYER_PASSPHRASE.")


def encrypt_existing_file(state: CryptoState, path: Path) -> bool:
    """Chiffre un fichier clair sur place. Retourne True si modifié."""
    require_unlocked(state)
    if not state.enabled:
        return False
    raw = path.read_bytes()
    if is_ciphertext(raw):
        return False
    sealed = seal(state, raw)
    tmp = path.with_suffix(path.suffix + ".enc-tmp")
    tmp.write_bytes(sealed)
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return True


def migrate_tree(state: CryptoState, home) -> dict:
    """Chiffre les blobs clairs restants sous vault/ et media/."""
    require_unlocked(state)
    if not state.enabled:
        raise AppError(409, "conflict", "Activez d'abord le chiffrement (cli.py crypto enable).")
    changed = 0
    skipped = 0
    for relative in ("vault/objects", "media/objects"):
        root = Path(home) / relative
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if not entry.is_file() or entry.is_symlink():
                continue
            if encrypt_existing_file(state, entry):
                changed += 1
            else:
                skipped += 1
    return {"encrypted": changed, "already_sealed_or_empty": skipped}
