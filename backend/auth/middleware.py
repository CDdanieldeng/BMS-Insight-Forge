"""Optional Bearer JWT enforcement for the FastAPI app."""

from __future__ import annotations

import logging

from jwt import PyJWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .entra_jwt import AUTH_ENABLED, verify_entra_access_token

logger = logging.getLogger(__name__)

_EXACT_EXEMPT = frozenset({"/health", "/openapi.json", "/redoc"})
_PREFIX_EXEMPT = ("/docs",)


def _path_exempt(path: str) -> bool:
    if path in _EXACT_EXEMPT:
        return True
    return any(path.startswith(p) for p in _PREFIX_EXEMPT)


class EntraAuthMiddleware(BaseHTTPMiddleware):
    """When AUTH_ENABLED is true, require a valid Entra access token on non-exempt routes."""

    async def dispatch(self, request: Request, call_next):
        if not AUTH_ENABLED:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        if _path_exempt(request.url.path):
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            return JSONResponse({"detail": "Missing bearer token"}, status_code=401)

        token = auth.removeprefix("Bearer ").strip()
        if not token:
            return JSONResponse({"detail": "Missing bearer token"}, status_code=401)

        try:
            claims = verify_entra_access_token(token)
            request.state.entra_claims = claims
        except PyJWTError as e:
            logger.debug("JWT validation failed: %s", e)
            return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

        return await call_next(request)
