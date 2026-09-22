"""Tests for mode-gated tool registration and friendly error payloads."""

import httpx
import pytest

from seafile_mcp.config import Config
from seafile_mcp.seafile_client import SeafileClient
from seafile_mcp.server import create_server

READ_TOOLS = {
    "get_auth_help",
    "auth_login",
    "auth_register_library",
    "auth_reauth",
    "auth_rotate",
    "auth_revoke",
    "auth_add_library",
    "auth_remove_library",
    "auth_status",
    "list_libraries",
    "get_library_info",
    "resolve_library",
    "list_directory",
    "get_file_detail",
    "read_file",
    "get_download_link",
    "search_files",
}
SAFE_WRITE_EXTRA = {
    "create_library",
    "rename_library",
    "create_directory",
    "upload_file",
    "update_file",
    "rename_item",
    "move_item",
    "copy_item",
    "create_share_link",
    "list_share_links",
}
FULL_EXTRA = {"delete_library", "delete_item", "delete_share_link"}


def make_config(mode):
    return Config.from_env(
        {"SEAFILE_SERVER_URL": "https://seafile.example.com", "SEAFILE_MCP_MODE": mode}
    )


async def tool_names(mode):
    mcp, client, _store = create_server(make_config(mode))
    try:
        tools = await mcp.list_tools()
        return {t.name for t in tools}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_read_only_registers_no_mutations():
    names = await tool_names("read_only")
    assert READ_TOOLS <= names
    assert not (names & SAFE_WRITE_EXTRA)
    assert not (names & FULL_EXTRA)


@pytest.mark.asyncio
async def test_safe_write_registers_no_deletes():
    names = await tool_names("safe_write")
    assert READ_TOOLS <= names
    assert SAFE_WRITE_EXTRA <= names
    assert not (names & FULL_EXTRA)


@pytest.mark.asyncio
async def test_full_registers_everything():
    names = await tool_names("full")
    assert READ_TOOLS <= names
    assert SAFE_WRITE_EXTRA <= names
    assert FULL_EXTRA <= names


@pytest.mark.asyncio
async def test_repo_token_scope_error_is_friendly_payload():
    """search_files with only a repo-token default raises a clear ScopeError."""
    from seafile_mcp.auth import ScopeError
    from seafile_mcp.tools import files as file_tools

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    config = Config.from_env(
        {
            "SEAFILE_SERVER_URL": "https://seafile.example.com",
            "SEAFILE_MCP_MODE": "full",
            "SEAFILE_REPO_TOKENS_JSON": '{"Docs": "repo-tok"}',
        }
    )
    client = SeafileClient(
        config.server_url,
        auth_scheme=config.auth_scheme,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ScopeError, match="requires an account-token session"):
            await file_tools.search_files(
                config, client, None, "report", library_name="Docs"
            )
    finally:
        await client.aclose()
