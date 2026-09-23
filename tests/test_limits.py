"""Transfer guardrail tests: timeout/size config, enforced caps (mocked HTTP)."""

import httpx
import pytest

from seafile_mcp.config import Config
from seafile_mcp.seafile_client import SeafileClient, SeafileError


def make_config(**overrides):
    env = {"SEAFILE_SERVER_URL": "https://seafile.example.com", **overrides}
    return Config.from_env(env)


def make_client(handler, **kwargs):
    return SeafileClient(
        "https://seafile.example.com", transport=httpx.MockTransport(handler), **kwargs
    )


def test_transfer_defaults():
    cfg = make_config()
    assert cfg.timeout == 60.0
    assert cfg.max_read_size == 10485760
    assert cfg.max_write_size == 52428800


def test_transfer_custom_values():
    cfg = make_config(SEAFILE_TIMEOUT="10", SEAFILE_MAX_READ_SIZE="100", SEAFILE_MAX_WRITE_SIZE="200")
    assert cfg.timeout == 10.0
    assert cfg.max_read_size == 100
    assert cfg.max_write_size == 200


def test_transfer_invalid():
    with pytest.raises(ValueError, match="SEAFILE_TIMEOUT"):
        make_config(SEAFILE_TIMEOUT="soon")
    with pytest.raises(ValueError, match="SEAFILE_TIMEOUT"):
        make_config(SEAFILE_TIMEOUT="0")
    with pytest.raises(ValueError, match="SEAFILE_MAX_READ_SIZE"):
        make_config(SEAFILE_MAX_READ_SIZE="-5")
    with pytest.raises(ValueError, match="SEAFILE_MAX_WRITE_SIZE"):
        make_config(SEAFILE_MAX_WRITE_SIZE="huge")


def test_client_rejects_bad_limits():
    with pytest.raises(ValueError, match="timeout"):
        SeafileClient("https://x.example", timeout=0)
    with pytest.raises(ValueError, match="max_read_size"):
        SeafileClient("https://x.example", max_read_size=-1)


@pytest.mark.asyncio
async def test_download_bytes_over_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"y" * 100)
    client = make_client(handler, max_read_size=10)
    try:
        with pytest.raises(SeafileError) as exc_info:
            await client.download_bytes("https://x.example/dl/1")
        assert exc_info.value.status_code == 413
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_download_bytes_under_cap_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"tiny")
    client = make_client(handler, max_read_size=10)
    try:
        assert await client.download_bytes("https://x.example/dl/1") == b"tiny"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_upload_bytes_over_cap_sends_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP should happen")
    client = make_client(handler, max_write_size=10)
    try:
        with pytest.raises(SeafileError) as exc_info:
            await client.upload_bytes("https://x.example/up/1", "/", "f.txt", b"z" * 100)
        assert exc_info.value.status_code == 413
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_update_bytes_over_cap_sends_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP should happen")
    client = make_client(handler, max_write_size=10)
    try:
        with pytest.raises(SeafileError) as exc_info:
            await client.update_bytes("https://x.example/upd/1", "/f.txt", b"z" * 100)
        assert exc_info.value.status_code == 413
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_timeout_wired_to_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])
    client = make_client(handler, timeout=7.5)
    try:
        assert client.timeout == 7.5
        await client.list_libraries("t")
    finally:
        await client.aclose()

