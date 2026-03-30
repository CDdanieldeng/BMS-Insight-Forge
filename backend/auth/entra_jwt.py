"""Validate Microsoft Entra ID (Azure AD) access tokens (JWT)."""

from __future__ import annotations

import os
from functools import lru_cache

import jwt
from jwt import PyJWKClient

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _tenant_id() -> str:
    return os.getenv("ENTRA_TENANT_ID", "").strip()


def _audiences() -> list[str]:
    raw = os.getenv("ENTRA_API_AUDIENCE", "").strip()
    if not raw:
        return []
    return [a.strip() for a in raw.split(",") if a.strip()]


@lru_cache
def _jwks_client(tenant_id: str) -> PyJWKClient:
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    return PyJWKClient(url)


def verify_entra_access_token(token: str) -> dict:
    """Decode and validate a Bearer access token. Raises jwt.PyJWTError subclasses on failure."""
    tenant = _tenant_id()
    audiences = _audiences()
    if not tenant or not audiences:
        raise jwt.InvalidTokenError(
            "ENTRA_TENANT_ID and ENTRA_API_AUDIENCE must be set when AUTH_ENABLED"
        )

    issuers = [
        f"https://login.microsoftonline.com/{tenant}/v2.0",
        f"https://sts.windows.net/{tenant}/",
    ]
    jwks = _jwks_client(tenant)
    signing_key = jwks.get_signing_key_from_jwt(token)

    last_err: Exception | None = None
    for issuer in issuers:
        try:
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=audiences,
                issuer=issuer,
            )
        except jwt.InvalidIssuerError as e:
            last_err = e
            continue

    raise last_err or jwt.InvalidTokenError("Token issuer not recognized")
