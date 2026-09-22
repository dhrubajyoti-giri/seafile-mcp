"""Share-link client methods and tools (mocked HTTP)."""

import httpx
import pytest

from seafile_mcp.auth import ScopeError
from seafile_mcp.config import Config
from seafile_mcp.seafile_client import SeafileClient
from seafile_mcp.tools import sharing


def make_config(**overrides):
    env = {"SEAFILE_SERVER_URL": "https://seafile.example.com", **overrides}
    return Config.from_env(env)


def make_client(handler):
    return SeafileClient(
        "https://seafile.example.com", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_create_share_link_sends_json_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["ct"] = request.headers.get("content-type", "")
        return httpx.Response(
            200, json={"token": "abc123", "link": "https://x.example/d/abc123/"}
        )

    client = make_client(handler)
    try:
        result = await client.create_share_link(
            "acct", "repo-1", "/Docs", password="pw", expire_days=7
        )
        assert "/api/v2.1/share-links/" in seen["url"]
        assert "application/json" in seen["ct"]
        assert '"repo_id": "repo-1"' in seen["body"] or '"repo_id":"repo-1"' in seen["body"]
        assert result["link"] == "https://x.example/d/abc123/"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_list_and_delete_share_links():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        if request.method == "DELETE":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json=[{"token": "t1"}])

    client = make_client(handler)
    try:
        links = await client.list_share_links("acct", repo_id="repo-1")
        assert links == [{"token": "t1"}]
        assert "repo_id=repo-1" in seen["url"]
        await client.delete_share_link("acct", "t1")
        assert seen["method"] == "DELETE"
        assert seen["url"].endswith("/api/v2.1/share-links/t1/")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_share_tools_require_account_token(tmp_path):
    from seafile_mcp.sessions import SessionRecord, SessionStore

    store = SessionStore(str(tmp_path / "s.json"))
    token = store.issue(SessionRecord(user_id="bob", repo_tokens={"Docs": "rt"}))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP should happen")

    client = make_client(handler)
    try:
        with pytest.raises(ScopeError, match="requires an account-token session"):
            await sharing.create_share_link(
                make_config(), client, store, "/f",
                library_name="Docs", session_token=token,
            )
        with pytest.raises(ScopeError, match="requires an account-token session"):
            await sharing.list_share_links(
                make_config(), client, store,
                library_name="Docs", session_token=token,
            )
        with pytest.raises(ValueError, match="share_token"):
            await sharing.delete_share_link(
                make_config(), client, None, "  ", account_token="a"
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_share_link_resolves_library_name():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        if str(request.url).endswith("/api2/repos/"):
            return httpx.Response(200, json=[{"id": "repo-9", "name": "Docs"}])
        return httpx.Response(200, json={"link": "https://x.example/d/z/"})

    client = make_client(handler)
    try:
        result = await sharing.create_share_link(
            make_config(), client, None, "/f",
            library_name="Docs", account_token="acct",
        )
        assert result["link"] == "https://x.example/d/z/"
    finally:
        await client.aclose()
