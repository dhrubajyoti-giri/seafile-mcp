"""Tests for SeafileClient: auth headers, Bearer fallback, error mapping."""

import httpx
import pytest

from seafile_mcp.seafile_client import SeafileClient, SeafileError


def make_client(handler, auth_scheme="auto"):
    transport = httpx.MockTransport(handler)
    return SeafileClient(
        "https://seafile.example.com", auth_scheme=auth_scheme, transport=transport
    )


@pytest.mark.asyncio
async def test_sends_token_scheme_by_default():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json=[])

    client = make_client(handler)
    await client.list_libraries("tok123")
    assert seen["auth"] == "Token tok123"
    await client.aclose()


@pytest.mark.asyncio
async def test_bearer_scheme_config():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json=[])

    client = make_client(handler, auth_scheme="bearer")
    await client.list_libraries("tok123")
    assert seen["auth"] == "Bearer tok123"
    await client.aclose()


@pytest.mark.asyncio
async def test_auto_falls_back_to_bearer_on_401():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["Authorization"])
        if calls[-1].startswith("Token"):
            return httpx.Response(401, json={"detail": "Invalid token"})
        return httpx.Response(200, json=[{"id": "r1", "name": "Docs"}])

    client = make_client(handler)
    libs = await client.list_libraries("tok123")
    assert calls == ["Token tok123", "Bearer tok123"]
    assert libs == [{"id": "r1", "name": "Docs"}]
    # Second call reuses the learned scheme — single request.
    calls.clear()
    await client.list_libraries("tok123")
    assert calls == ["Bearer tok123"]
    await client.aclose()


@pytest.mark.asyncio
async def test_error_message_extraction():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error_msg": "Library not found"})

    client = make_client(handler)
    with pytest.raises(SeafileError, match="Library not found") as exc_info:
        await client.get_library("tok", "missing-id")
    assert exc_info.value.status_code == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_library_name_exact_and_case_insensitive():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[{"id": "r1", "name": "Shared Docs"}, {"id": "r2", "name": "Pics"}]
        )

    client = make_client(handler)
    lib = await client.resolve_library_name("tok", "shared docs")
    assert lib["id"] == "r1"
    with pytest.raises(SeafileError) as exc_info:
        await client.resolve_library_name("tok", "Nope")
    assert exc_info.value.status_code == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_repo_mkdir_uses_form_and_query_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"success": True})

    client = make_client(handler)
    result = await client.repo_mkdir("repo-tok", "/new-dir")
    assert "path=%2Fnew-dir" in seen["url"] or "path=/new-dir" in seen["url"]
    assert "operation=mkdir" in seen["body"]
    assert result == {"success": True}
    await client.aclose()


@pytest.mark.asyncio
async def test_repo_rename_dir_uses_newname():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json="success")

    client = make_client(handler)
    await client.repo_rename_dir("repo-tok", "/old", "new")
    assert "operation=rename" in seen["body"]
    assert "newname=new" in seen["body"]
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_library_name_single_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=[{"id": "r1", "name": "Docs"}])

    client = make_client(handler)
    lib = await client.resolve_library_name("tok", "docs")
    assert lib["id"] == "r1"
    assert len(calls) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_repo_list_dir_params():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"dirent_list": [], "user_perm": "rw"})

    client = make_client(handler)
    data = await client.repo_list_dir("repo-tok", path="/sub", recursive=True)
    assert "path=%2Fsub" in seen["url"] or "path=/sub" in seen["url"]
    assert "recursive=1" in seen["url"]
    assert seen["auth"] == "Token repo-tok"
    assert data["user_perm"] == "rw"
    await client.aclose()
