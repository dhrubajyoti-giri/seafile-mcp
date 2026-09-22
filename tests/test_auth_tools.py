"""Auth tool flows: login, library bootstrap/attach, reauth, rotate, revoke."""

import httpx
import pytest

from seafile_mcp.auth import AuthError
from seafile_mcp.config import Config
from seafile_mcp.seafile_client import SeafileClient
from seafile_mcp.sessions import SessionStore
from seafile_mcp.tools import auth_tools


def make_config(**overrides):
    env = {"SEAFILE_SERVER_URL": "https://seafile.example.com", **overrides}
    return Config.from_env(env)


def make_client(handler):
    return SeafileClient(
        "https://seafile.example.com", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_login_issues_full_scope_session(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/api2/auth-token/")
        assert request.headers.get("X-SEAFILE-OTP") == "123456"
        return httpx.Response(200, json={"token": "seafile-acct"})

    client = make_client(handler)
    store = SessionStore(str(tmp_path / "s.json"))
    try:
        result = await auth_tools.auth_login(
            make_config(), client, store, "alice", "pw", "123456"
        )
        assert result["scope"] == "full"
        assert result["user_id"] == "alice"
        token = result["session_token"]
        record = store.lookup(token)
        assert record is not None and record.account_token == "seafile-acct"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_login_rejects_bad_credentials(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"non_field_errors": ["bad login"]})

    client = make_client(handler)
    try:
        with pytest.raises(AuthError, match="rejected the login"):
            await auth_tools.auth_login(make_config(), client, SessionStore(str(tmp_path / "s.json")), "alice", "wrong")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_library_bootstrap_and_attach(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"repo_id": "r1", "repo_name": "Docs", "user_perm": "rw"}
        )

    client = make_client(handler)
    store = SessionStore(str(tmp_path / "s.json"))
    try:
        first = await auth_tools.auth_register_library(
            make_config(), client, store, "lib-tok-1", library_name="Docs"
        )
        assert first["scope"] == "libraries"
        assert first["libraries"] == ["Docs"]
        token = first["session_token"]

        second = await auth_tools.auth_add_library(
            make_config(), client, store, token, "lib-tok-2", library_name="Pics"
        )
        assert second["session_token"] == token
        assert second["libraries"] == ["Docs", "Pics"]

        removed = await auth_tools.auth_remove_library(
            make_config(), client, store, token, "Docs"
        )
        assert removed["libraries"] == ["Pics"]

        status = await auth_tools.auth_status(make_config(), client, store, token)
        assert status["libraries"] == ["Pics"]
        assert status["has_account_token"] is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_library_token_mismatch_rejected(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"repo_id": "other-id"})

    client = make_client(handler)
    try:
        with pytest.raises(AuthError, match="does not belong"):
            await auth_tools.auth_register_library(
                make_config(), client, SessionStore(str(tmp_path / "s.json")),
                "tok", library_name="Docs", repo_id="r1",
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_rotate_and_revoke(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token": "seafile-acct"})

    client = make_client(handler)
    store = SessionStore(str(tmp_path / "s.json"))
    try:
        login = await auth_tools.auth_login(make_config(), client, store, "a", "pw")
        old = login["session_token"]
        rotated = await auth_tools.auth_rotate(make_config(), client, store, old)
        assert rotated["session_token"] != old
        assert store.lookup(old) is None

        reauth = await auth_tools.auth_reauth(
            make_config(), client, store, rotated["session_token"], "new-pw"
        )
        assert reauth["reauthenticated"] is True

        revoked = await auth_tools.auth_revoke(
            make_config(), client, store, rotated["session_token"]
        )
        assert revoked == {"revoked": True}
        with pytest.raises(AuthError, match="[Uu]nknown or revoked"):
            await auth_tools.auth_status(
                make_config(), client, store, rotated["session_token"]
            )
    finally:
        await client.aclose()
