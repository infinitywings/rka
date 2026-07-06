#!/usr/bin/env python3
"""OAuth-protected reverse proxy for RKA's Streamable HTTP MCP endpoint.

This is a local development bridge for ChatGPT's "Server URL" connector path:

    ChatGPT -> HTTPS tunnel -> this proxy -> http://127.0.0.1:9713/mcp

The proxy implements the MCP OAuth discovery documents plus a minimal
authorization-code + PKCE flow. It is intentionally small and in-memory; restart
it to revoke issued codes/tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse


UPSTREAM_MCP_URL = os.environ.get("RKA_MCP_UPSTREAM", "http://127.0.0.1:9713/mcp")
AUTH_PASSPHRASE = os.environ.get("RKA_MCP_OAUTH_PASSPHRASE")
TOKEN_TTL_SECONDS = int(os.environ.get("RKA_MCP_OAUTH_TOKEN_TTL_SECONDS", "3600"))
CODE_TTL_SECONDS = int(os.environ.get("RKA_MCP_OAUTH_CODE_TTL_SECONDS", "300"))
SCOPE = "rka"

if not AUTH_PASSPHRASE:
    raise RuntimeError("Set RKA_MCP_OAUTH_PASSPHRASE before starting the proxy.")


@dataclass
class OAuthClient:
    client_id: str
    redirect_uris: list[str]
    client_name: str | None = None


@dataclass
class AuthorizationCode:
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    resource: str | None
    scope: str
    expires_at: float


@dataclass
class AccessToken:
    client_id: str
    resource: str | None
    scope: str
    expires_at: float


@dataclass
class RefreshToken:
    client_id: str
    resource: str | None
    scope: str


app = FastAPI(title="RKA MCP OAuth Proxy")
clients: dict[str, OAuthClient] = {}
codes: dict[str, AuthorizationCode] = {}
access_tokens: dict[str, AccessToken] = {}
refresh_tokens: dict[str, RefreshToken] = {}


def _external_base(request: Request) -> str:
    configured = os.environ.get("RKA_MCP_PUBLIC_BASE_URL")
    if configured:
        return configured.rstrip("/")

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        raise HTTPException(status_code=400, detail="Missing Host header")
    return f"{proto}://{host}".rstrip("/")


def _resource_metadata_url(request: Request) -> str:
    return f"{_external_base(request)}/.well-known/oauth-protected-resource/mcp"


def _resource_uri(request: Request) -> str:
    return f"{_external_base(request)}/mcp"


def _issuer(request: Request) -> str:
    return _external_base(request)


def _now() -> float:
    return time.time()


def _cleanup_expired() -> None:
    now = _now()
    for code, record in list(codes.items()):
        if record.expires_at < now:
            codes.pop(code, None)
    for token, record in list(access_tokens.items()):
        if record.expires_at < now:
            access_tokens.pop(token, None)


def _pkce_matches(verifier: str, challenge: str, method: str) -> bool:
    if method.upper() == "S256":
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(computed, challenge)
    if method.lower() == "plain":
        return hmac.compare_digest(verifier, challenge)
    return False


def _validate_redirect_uri(client: OAuthClient, redirect_uri: str) -> bool:
    return redirect_uri in client.redirect_uris


def _token_response(client_id: str, resource: str | None, scope: str) -> JSONResponse:
    access_token = "rka_at_" + secrets.token_urlsafe(32)
    refresh_token = "rka_rt_" + secrets.token_urlsafe(32)
    access_tokens[access_token] = AccessToken(
        client_id=client_id,
        resource=resource,
        scope=scope,
        expires_at=_now() + TOKEN_TTL_SECONDS,
    )
    refresh_tokens[refresh_token] = RefreshToken(
        client_id=client_id,
        resource=resource,
        scope=scope,
    )
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": TOKEN_TTL_SECONDS,
            "refresh_token": refresh_token,
            "scope": scope,
        }
    )


def _unauthorized(request: Request) -> Response:
    headers = {
        "WWW-Authenticate": (
            'Bearer error="invalid_token", '
            f'resource_metadata="{_resource_metadata_url(request)}"'
        )
    }
    return JSONResponse({"error": "unauthorized"}, status_code=401, headers=headers)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


def _require_token(request: Request) -> AccessToken | Response:
    _cleanup_expired()
    token = _bearer_token(request)
    if not token:
        return _unauthorized(request)
    record = access_tokens.get(token)
    if record is None or record.expires_at < _now():
        return _unauthorized(request)
    expected_resource = _resource_uri(request)
    if record.resource and record.resource.rstrip("/") != expected_resource.rstrip("/"):
        return JSONResponse({"error": "invalid_resource"}, status_code=403)
    return record


@app.on_event("startup")
async def startup() -> None:
    app.state.http = httpx.AsyncClient(timeout=None, follow_redirects=False)


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.http.aclose()


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
async def protected_resource_metadata(request: Request) -> dict[str, Any]:
    return {
        "resource": _resource_uri(request),
        "authorization_servers": [_issuer(request)],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
    }


@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/openid-configuration")
async def authorization_server_metadata(request: Request) -> dict[str, Any]:
    base = _external_base(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
    }


@app.post("/register")
async def register(request: Request) -> JSONResponse:
    body = await request.json()
    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uris is required")

    client_id = "rka_client_" + secrets.token_urlsafe(16)
    client = OAuthClient(
        client_id=client_id,
        redirect_uris=[str(uri) for uri in redirect_uris],
        client_name=body.get("client_name"),
    )
    clients[client_id] = client
    return JSONResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": int(_now()),
            "redirect_uris": client.redirect_uris,
            "client_name": client.client_name or "ChatGPT",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


@app.get("/authorize")
async def authorize_form(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str = "S256",
    resource: str | None = None,
    scope: str = SCOPE,
) -> HTMLResponse:
    client = clients.get(client_id)
    if response_type != "code" or client is None or not _validate_redirect_uri(client, redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid OAuth authorization request")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="PKCE code_challenge is required")

    hidden = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state or "",
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "resource": resource or "",
        "scope": scope or SCOPE,
    }
    hidden_html = "\n".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in hidden.items()
    )
    return HTMLResponse(
        f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Authorize RKA</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 3rem; }}
    main {{ max-width: 34rem; }}
    input {{ width: 100%; padding: .65rem; margin: .5rem 0 1rem; }}
    button {{ padding: .65rem 1rem; }}
    code {{ word-break: break-all; }}
  </style>
</head>
<body>
  <main>
    <h1>Authorize RKA MCP</h1>
    <p>Enter the local authorization passphrase to connect ChatGPT to RKA.</p>
    <p>Resource: <code>{html.escape(resource or _resource_uri(request))}</code></p>
    <form method="post" action="/authorize">
      {hidden_html}
      <label>Passphrase</label>
      <input name="passphrase" type="password" autocomplete="current-password" autofocus>
      <button type="submit">Authorize</button>
    </form>
  </main>
</body>
</html>"""
    )


@app.post("/authorize")
async def authorize_submit(
    passphrase: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(""),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    resource: str = Form(""),
    scope: str = Form(SCOPE),
) -> RedirectResponse:
    client = clients.get(client_id)
    if client is None or not _validate_redirect_uri(client, redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid OAuth client")
    if not hmac.compare_digest(passphrase, AUTH_PASSPHRASE):
        raise HTTPException(status_code=401, detail="Invalid passphrase")

    code = "rka_code_" + secrets.token_urlsafe(24)
    codes[code] = AuthorizationCode(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        resource=resource or None,
        scope=scope or SCOPE,
        expires_at=_now() + CODE_TTL_SECONDS,
    )
    params = {"code": code}
    if state:
        params["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=303)


@app.post("/token")
async def token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
    resource: str | None = Form(None),
) -> JSONResponse:
    if client_id not in clients:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    if grant_type == "authorization_code":
        if not code or not redirect_uri or not code_verifier:
            raise HTTPException(status_code=400, detail="Missing authorization_code fields")
        record = codes.pop(code, None)
        if record is None or record.expires_at < _now():
            raise HTTPException(status_code=400, detail="Invalid or expired code")
        if record.client_id != client_id or record.redirect_uri != redirect_uri:
            raise HTTPException(status_code=400, detail="Invalid code binding")
        if resource and record.resource and resource.rstrip("/") != record.resource.rstrip("/"):
            raise HTTPException(status_code=400, detail="Invalid resource")
        if not _pkce_matches(code_verifier, record.code_challenge, record.code_challenge_method):
            raise HTTPException(status_code=400, detail="Invalid PKCE verifier")
        return _token_response(client_id, record.resource or resource, record.scope)

    if grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(status_code=400, detail="Missing refresh_token")
        record = refresh_tokens.get(refresh_token)
        if record is None or record.client_id != client_id:
            raise HTTPException(status_code=400, detail="Invalid refresh_token")
        return _token_response(client_id, record.resource, record.scope)

    raise HTTPException(status_code=400, detail="Unsupported grant_type")


@app.api_route("/mcp", methods=["GET", "POST", "DELETE", "HEAD", "OPTIONS"])
async def proxy_mcp(request: Request) -> Response:
    token_or_response = _require_token(request)
    if isinstance(token_or_response, Response):
        return token_or_response

    incoming_headers = dict(request.headers)
    proxy_headers = {
        key: value
        for key, value in incoming_headers.items()
        if key.lower()
        not in {
            "host",
            "authorization",
            "content-length",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
    }

    req = app.state.http.build_request(
        request.method,
        UPSTREAM_MCP_URL,
        headers=proxy_headers,
        content=request.stream(),
    )
    upstream = await app.state.http.send(req, stream=True)
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower()
        not in {
            "content-length",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
    }
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream.aclose),
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    host = os.environ.get("RKA_MCP_OAUTH_HOST", "127.0.0.1")
    port = int(os.environ.get("RKA_MCP_OAUTH_PORT", "9720"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
