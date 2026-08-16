"""HTTP token gate and bearer middleware (no TCP listener)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from mcp_server.http_auth import (
    MIN_HTTP_TOKEN_LENGTH,
    BearerAuthMiddleware,
    bearer_token,
    ensure_http_token,
    is_loopback_host,
    tokens_match,
)

_OK_TOKEN = "t" * MIN_HTTP_TOKEN_LENGTH


def test_loopback_hosts():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("127.0.0.2")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert is_loopback_host("[::1]")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("::")
    assert not is_loopback_host("example.invalid")


def test_http_token_always_required():
    with pytest.raises(ValueError, match="MCP_HTTP_TOKEN"):
        ensure_http_token("")
    with pytest.raises(ValueError, match="MCP_HTTP_TOKEN"):
        ensure_http_token(None)
    with pytest.raises(ValueError, match="MCP_HTTP_TOKEN"):
        ensure_http_token("   ")
    ensure_http_token(_OK_TOKEN)


def test_http_token_rejects_short():
    with pytest.raises(ValueError, match="at least"):
        ensure_http_token("x")
    with pytest.raises(ValueError, match="at least"):
        ensure_http_token("t" * (MIN_HTTP_TOKEN_LENGTH - 1))
    with pytest.raises(ValueError, match="at least"):
        ensure_http_token("  " + "t" * (MIN_HTTP_TOKEN_LENGTH - 1) + "  ")
    ensure_http_token(_OK_TOKEN)


def test_bearer_token_parse():
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer abc") == "abc"
    assert bearer_token("Basic abc") is None
    assert bearer_token(None) is None


def test_tokens_match():
    assert tokens_match("abc", "abc")
    assert not tokens_match("abc", "abd")
    assert not tokens_match(None, "abc")
    assert not tokens_match("ab", "abc")
    assert not tokens_match("", "abc")


async def _dummy_app(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": b"ok"})


async def _status(
    app,
    path: str,
    authorization: str | None = None,
    method: str = "GET",
    body: bytes = b"",
) -> int:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("latin1")))
    code = {"n": 0}

    async def send(msg):
        if msg["type"] == "http.response.start":
            code["n"] = msg["status"]

    sent = {"n": False}

    async def receive():
        if sent["n"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["n"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
    }
    await app(scope, receive, send)
    return code["n"]


def test_middleware_health_open_mcp_requires_token():
    app = BearerAuthMiddleware(_dummy_app, "s3cret")

    async def run():
        assert await _status(app, "/health") == 200
        assert await _status(app, "/health/") == 200
        assert await _status(app, "/mcp") == 401
        assert await _status(app, "/mcp/") == 401
        assert await _status(app, "/mcp", "Bearer wrong") == 401
        assert await _status(app, "/mcp", "Bearer s3cret") == 200

    asyncio.run(run())


@asynccontextmanager
async def _lifespan(app):
    """Drive ASGI lifespan so StreamableHTTP session manager can run."""
    queue: asyncio.Queue = asyncio.Queue()
    started = asyncio.Event()
    stopped = asyncio.Event()
    failed: dict[str, str] = {}

    async def receive():
        return await queue.get()

    async def send(msg):
        kind = msg.get("type")
        if kind == "lifespan.startup.complete":
            started.set()
        elif kind == "lifespan.shutdown.complete":
            stopped.set()
        elif kind == "lifespan.startup.failed":
            failed["msg"] = str(msg.get("message") or msg)
            started.set()

    task = asyncio.create_task(
        app(
            {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}},
            receive,
            send,
        )
    )
    await queue.put({"type": "lifespan.startup"})
    await asyncio.wait_for(started.wait(), timeout=5)
    if failed:
        task.cancel()
        raise RuntimeError(failed["msg"])
    try:
        yield
    finally:
        await queue.put({"type": "lifespan.shutdown"})
        await asyncio.wait_for(stopped.wait(), timeout=5)
        await asyncio.wait_for(task, timeout=5)


def test_real_app_health_and_mcp_auth():
    """Auth wraps a real Starlette MCP app: /health public, /mcp needs Bearer.

    Uses a throwaway MCPServer so the production ``mcp`` object is not mutated.
    """
    from mcp.server.mcpserver import MCPServer
    from starlette.responses import JSONResponse

    tmp = MCPServer(name="http-auth-test")

    @tmp.custom_route("/health", methods=["GET"])
    async def _health(_request):
        return JSONResponse({"status": "ok"})

    inner = tmp.streamable_http_app(streamable_http_path="/mcp", host="127.0.0.1")
    app = BearerAuthMiddleware(inner, "s3cret")

    async def run():
        async with _lifespan(app):
            assert await _status(app, "/health") == 200
            assert await _status(app, "/mcp") == 401
            authed = await asyncio.wait_for(
                _status(app, "/mcp", "Bearer s3cret", method="POST"),
                timeout=5,
            )
            assert authed != 401

    asyncio.run(run())


def test_main_help_omits_sse(capsys, monkeypatch):
    from mcp_server.server import main

    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "streamable-http" in help_text
    assert "sse" not in help_text.lower().replace("streamable-http", "")


def test_help_tolerates_bad_mcp_port(monkeypatch):
    from mcp_server.server import main

    monkeypatch.setenv("MCP_PORT", "nope")
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_main_rejects_sse():
    from mcp_server.server import main

    with pytest.raises(SystemExit) as exc:
        main(["--transport", "sse"])
    assert exc.value.code == 2


def test_invalid_env_transport_does_not_start_http(monkeypatch):
    from mcp_server.server import main

    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    monkeypatch.delenv("MCP_HTTP_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_http_requires_token(monkeypatch, host):
    from mcp_server.server import main

    monkeypatch.delenv("MCP_HTTP_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--transport",
                "streamable-http",
                "--host",
                host,
                "--port",
                "9",
            ]
        )
    assert exc.value.code == 2


def test_http_rejects_short_token(monkeypatch):
    from mcp_server.server import main

    monkeypatch.setenv("MCP_HTTP_TOKEN", "short")
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--transport",
                "streamable-http",
                "--host",
                "127.0.0.1",
                "--port",
                "9",
            ]
        )
    assert exc.value.code == 2


def test_http_rejects_bad_port(monkeypatch):
    from mcp_server.server import main

    monkeypatch.setenv("MCP_HTTP_TOKEN", "x")
    with pytest.raises(SystemExit) as exc:
        main(["--transport", "streamable-http", "--port", "nope"])
    assert exc.value.code == 2
