"""run_transport dispatch across mcp runtimes (fakes, no network)."""

import pytest

from seafile_mcp.server import run_transport


class V1Fake:
    """mcp v1.30 shape: transport methods take no host/port."""
    def __init__(self):
        self.calls = []
    async def run_stdio_async(self):
        self.calls.append(("stdio",))
    async def run_sse_async(self):
        self.calls.append(("sse",))
    async def run_streamable_http_async(self):
        self.calls.append(("http",))


class V2Fake:
    """mcp v2 shape: http methods take host/port kwargs."""
    def __init__(self):
        self.calls = []
    async def run_stdio_async(self):
        self.calls.append(("stdio",))
    async def run_sse_async(self, *, host="127.0.0.1", port=8000):
        self.calls.append(("sse", host, port))
    async def run_streamable_http_async(self, *, host="127.0.0.1", port=8000):
        self.calls.append(("http", host, port))


class LegacyFake:
    """Very old mcp v1: only run_async(transport=...)."""
    def __init__(self):
        self.calls = []
    async def run_async(self, transport):
        self.calls.append(transport)


class EmptyFake:
    pass


@pytest.mark.asyncio
async def test_run_transport_v1_bare_calls():
    mcp = V1Fake()
    await run_transport(mcp, "stdio")
    await run_transport(mcp, "sse")
    await run_transport(mcp, "streamable-http", host="0.0.0.0", port=9000)
    assert mcp.calls == [("stdio",), ("sse",), ("http",)]


@pytest.mark.asyncio
async def test_run_transport_v2_host_port():
    mcp = V2Fake()
    await run_transport(mcp, "streamable-http", host="0.0.0.0", port=9000)
    await run_transport(mcp, "sse", host="h", port=1)
    assert mcp.calls == [("http", "0.0.0.0", 9000), ("sse", "h", 1)]


@pytest.mark.asyncio
async def test_run_transport_legacy():
    mcp = LegacyFake()
    await run_transport(mcp, "stdio")
    assert mcp.calls == ["stdio"]


@pytest.mark.asyncio
async def test_run_transport_unknown():
    with pytest.raises(ValueError, match="Unknown transport"):
        await run_transport(V1Fake(), "carrier-pigeon")


@pytest.mark.asyncio
async def test_run_transport_no_method():
    with pytest.raises(AttributeError, match="Cannot start transport"):
        await run_transport(EmptyFake(), "stdio")
