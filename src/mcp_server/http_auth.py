"""HTTP MCP token gate and bearer middleware."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from collections.abc import Awaitable, Callable
from typing import Any

ASGIApp = Callable[..., Awaitable[None]]

_PUBLIC_PATHS = frozenset({"/health"})
MIN_HTTP_TOKEN_LENGTH = 16


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    if h in {"localhost"}:
        return True
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def ensure_http_token(token: str | None) -> None:
    """Raise ValueError if HTTP MCP would start without a strong enough token."""
    value = (token or "").strip()
    if len(value) >= MIN_HTTP_TOKEN_LENGTH:
        return
    raise ValueError(
        "Refusing to start HTTP MCP without MCP_HTTP_TOKEN "
        f"(at least {MIN_HTTP_TOKEN_LENGTH} characters). "
        "Set a shared secret and send Authorization: Bearer <token> on "
        "every /mcp request. HTTP is cleartext — terminate TLS in front "
        "before exposing off-loopback."
    )


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    kind, _, rest = authorization.partition(" ")
    if kind.lower() != "bearer" or not rest.strip():
        return None
    return rest.strip()


def tokens_match(got: str | None, expected: str) -> bool:
    """Constant-time compare (hash both sides so length is not leaked)."""
    have = hashlib.sha256((got or "").encode("utf-8")).digest()
    exp = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(have, exp)


def _header_map(scope: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in scope.get("headers") or []:
        out[key.decode("latin1").lower()] = value.decode("latin1")
    return out


def _path_is_public(path: str) -> bool:
    return (path.rstrip("/") or "/") in _PUBLIC_PATHS


class BearerAuthMiddleware:
    """ASGI middleware: require Authorization: Bearer <token> except /health."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if _path_is_public(path):
            await self.app(scope, receive, send)
            return
        got = bearer_token(_header_map(scope).get("authorization"))
        if not tokens_match(got, self.token):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"error":"unauthorized"}',
                }
            )
            return
        await self.app(scope, receive, send)
