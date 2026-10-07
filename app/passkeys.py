from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from typing import Any, Iterable

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    text = str(value or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_challenge() -> bytes:
    return secrets.token_bytes(32)


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")[:48]


@dataclass(frozen=True, slots=True)
class RegisteredPasskey:
    credential_id_b64: str
    public_key: bytes
    sign_count: int
    device_type: str
    backed_up: bool
    transports_json: str


@dataclass(frozen=True, slots=True)
class AuthenticatedPasskey:
    new_sign_count: int
    device_type: str
    backed_up: bool


def registration_options(*, account, credentials: Iterable, rp_id: str, rp_name: str) -> tuple[dict[str, Any], str]:
    challenge = new_challenge()
    excluded = [
        PublicKeyCredentialDescriptor(id=b64url_decode(row.credential_id_b64))
        for row in credentials
        if not getattr(row, "revoked_at", None)
    ]
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=str(account.id).encode("utf-8"),
        user_name=account.username,
        user_display_name=account.display_name,
        challenge=challenge,
        exclude_credentials=excluded,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        timeout=120_000,
    )
    return json.loads(options_to_json(options)), b64url_encode(challenge)


def authentication_options(*, credentials: Iterable, rp_id: str) -> tuple[dict[str, Any], str]:
    challenge = new_challenge()
    allowed = [
        PublicKeyCredentialDescriptor(id=b64url_decode(row.credential_id_b64))
        for row in credentials
        if not getattr(row, "revoked_at", None)
    ]
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        allow_credentials=allowed,
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=120_000,
    )
    return json.loads(options_to_json(options)), b64url_encode(challenge)


def verify_registration(*, credential: dict[str, Any], challenge_b64: str, rp_id: str, origin: str) -> RegisteredPasskey:
    verified = verify_registration_response(
        credential=credential,
        expected_challenge=b64url_decode(challenge_b64),
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_verification=True,
    )
    transports = credential.get("response", {}).get("transports") or []
    clean_transports = [str(value)[:40] for value in transports if str(value).strip()][:12]
    return RegisteredPasskey(
        credential_id_b64=b64url_encode(verified.credential_id),
        public_key=verified.credential_public_key,
        sign_count=int(verified.sign_count or 0),
        device_type=_enum_value(verified.credential_device_type),
        backed_up=bool(verified.credential_backed_up),
        transports_json=json.dumps(clean_transports, ensure_ascii=False, separators=(",", ":")),
    )


def verify_authentication(*, credential: dict[str, Any], stored, challenge_b64: str, rp_id: str, origin: str) -> AuthenticatedPasskey:
    verified = verify_authentication_response(
        credential=credential,
        expected_challenge=b64url_decode(challenge_b64),
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=stored.public_key,
        credential_current_sign_count=int(stored.sign_count or 0),
        require_user_verification=True,
    )
    return AuthenticatedPasskey(
        new_sign_count=int(verified.new_sign_count or 0),
        device_type=_enum_value(verified.credential_device_type),
        backed_up=bool(verified.credential_backed_up),
    )
