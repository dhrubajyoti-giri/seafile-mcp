"""Tools-layer behavior: mkdir params, shape normalization, caps, validation."""

import httpx
import pytest

from seafile_mcp.auth import ScopeError
from seafile_mcp.config import Config
from seafile_mcp.seafile_client import SeafileClient
from seafile_mcp.tools import files as file_tools
from seafile_mcp.vault import CredentialVault


def make_config(**overrides):
    env = {"SEAFILE_SERVER_URL": "https://seafile.example.com", **overrides}
    return Config.from_env(env)


def make_client(handler):
    return SeafileClient(
        "https://seafile.example.com", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_account_mkdir_posts_full_path_with_parents():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json="success")

    client = make_client(handler)
    try:
        result = await file_tools.create_directory(
            make_config(SEAFILE_ACCOUNT_TOKEN="acct"),
            client, None, "/a/b/c", repo_id="r1",
        )
        assert result["created"] is True
        assert "p=%2Fa%2Fb%2Fc" in seen["url"] or "p=/a/b/c" in seen["url"]
        assert "operation=mkdir" in seen["body"]
        assert "create_parents=true" in seen["body"]
        assert "dirname" not in seen["body"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_directory_rejects_root_and_blank():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP should happen")

    client = make_client(handler)
    try:
        with pytest.raises(ValueError, match="library root"):
            await file_tools.create_directory(
                make_config(SEAFILE_ACCOUNT_TOKEN="a"), client, None, "/"
            )
        with pytest.raises(ValueError, match="must not be empty"):
            await file_tools.create_directory(
                make_config(SEAFILE_ACCOUNT_TOKEN="a"), client, None, "   "
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_list_directory_normalizes_repo_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "user_perm": "rw",
                "dir_id": "abc",
                "dirent_list": [{"type": "file", "name": "a.txt"}],
            },
        )

    client = make_client(handler)
    try:
        result = await file_tools.list_directory(
            make_config(), client, None, "/",
            repo_token="rt", library_name="Docs",
        )
        assert result["entries"] == [{"type": "file", "name": "a.txt"}]
        assert result["permission"] == "rw"
        assert result["path"] == "/"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_read_file_caps_max_chars():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/file/") or "/file/?" in str(request.url):
            return httpx.Response(200, text="https://x.example/dl/1")
        return httpx.Response(200, content=b"x" * 300_000)

    client = make_client(handler)
    try:
        result = await file_tools.read_file(
            make_config(), client, None, "/big.txt",
            max_chars=999_999_999, account_token="a", repo_id="r1",
        )
        assert result["truncated"] is True
        assert len(result["content"]) == 200_000
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_blank_path_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP should happen")

    client = make_client(handler)
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            await file_tools.read_file(
                make_config(), client, None, "", account_token="a", repo_id="r"
            )
        with pytest.raises(ValueError, match="must not be empty"):
            await file_tools.search_files(make_config(), client, None, "  ")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_vault_repo_user_move_gets_scope_error(tmp_path):
    vault = CredentialVault(str(tmp_path / "v.json"))
    vault.register("bob", repo_tokens={"Docs": "rt"})

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP should happen")

    client = make_client(handler)
    try:
        with pytest.raises(ScopeError, match="requires an account token"):
            await file_tools.move_item(
                make_config(), client, vault, "/f.txt", "/d",
                library_name="Docs", user_id="bob",
            )
    finally:
        await client.aclose()
