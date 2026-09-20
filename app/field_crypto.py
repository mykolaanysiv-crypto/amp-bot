from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _key_id(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def _root_secret() -> str:
    explicit = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    if explicit:
        return explicit
    session_secret = os.getenv("WEB_SESSION_SECRET", "").strip()
    if session_secret:
        return session_secret
    return "local-dev-field-encryption-key"


def _previous_secrets() -> list[str]:
    raw = os.getenv("FIELD_ENCRYPTION_PREVIOUS_KEYS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class CryptoKey:
    key_id: str
    secret: str
    fernet: Fernet


@lru_cache(maxsize=1)
def keyring() -> tuple[CryptoKey, tuple[CryptoKey, ...]]:
    current_secret = _root_secret()
    current = CryptoKey(
        key_id=_key_id(current_secret),
        secret=current_secret,
        fernet=Fernet(_derive_fernet_key(current_secret)),
    )
    previous: list[CryptoKey] = []
    seen = {current.key_id}
    for secret in _previous_secrets():
        kid = _key_id(secret)
        if kid in seen:
            continue
        seen.add(kid)
        previous.append(CryptoKey(kid, secret, Fernet(_derive_fernet_key(secret))))
    return current, tuple(previous)


def clear_keyring_cache() -> None:
    keyring.cache_clear()


def is_encrypted(value: str | None) -> bool:
    return bool(value and value.startswith(PREFIX))


def encrypt_field(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if is_encrypted(value):
        return value
    current, _ = keyring()
    token = current.fernet.encrypt(value.encode("utf-8")).decode("ascii")
    return f"{PREFIX}{current.key_id}:{token}"


def decrypt_field(value: str | None) -> str | None:
    if value is None or value == "" or not is_encrypted(value):
        # Legacy plaintext remains readable until the v1.17.2 backfill encrypts it.
        return value
    payload = value[len(PREFIX):]
    try:
        kid, token = payload.split(":", 1)
    except ValueError as exc:
        raise ValueError("Malformed encrypted field payload") from exc
    current, previous = keyring()
    candidates = (current,) + previous
    ordered = sorted(candidates, key=lambda item: item.key_id != kid)
    for item in ordered:
        try:
            return item.fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken:
            continue
    raise ValueError(f"Encrypted field cannot be decrypted with configured keyring (kid={kid})")


def reencrypt_field(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    plaintext = decrypt_field(value)
    if plaintext is None:
        return None
    current, _ = keyring()
    token = current.fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{PREFIX}{current.key_id}:{token}"


def current_key_id() -> str:
    return keyring()[0].key_id
