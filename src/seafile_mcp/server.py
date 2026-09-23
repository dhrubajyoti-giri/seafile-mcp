"""Seafile MCP server — FastMCP app with mode-gated tools and dual transports."""

from __future__ import annotations

import argparse
import asyncio
import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .auth import AuthError, ScopeError
from .config import Config
from .seafile_client import SeafileClient, SeafileError
from .tools import auth_tools, files, help as help_tools, libraries, sharing
from .sessions import SessionError, SessionStore

SERVER_NAME = "seafile-mcp"


def _friendly(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Convert auth/API errors into {"error": ...} payloads agents can act on."""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except (AuthError, ScopeError, SeafileError, SessionError, ValueError) as exc:
            status = getattr(exc, "status_code", None)
            payload: dict[str, Any] = {"error": str(exc)}
            if status is not None:
                payload["status_code"] = status
                if status == 401:
                    payload["hint"] = (
                        "Token invalid or expired. Account tokens are "
                        "invalidated by a password change — reauth with "
                        "auth_reauth (or re-mint via get_auth_help) and retry."
                    )
                elif status == 440:
                    payload["hint"] = (
                        "Seafile reports this library is encrypted. Decrypt it "
                        "in the Web UI first, then retry."
                    )
            return payload

    return wrapper


def create_server(
    config: Config,
    client: SeafileClient | None = None,
    store: SessionStore | None = None,
    host: str | None = None,
    port: int | None = None,
) -> tuple[FastMCP, SeafileClient, SessionStore]:
    """Build the FastMCP app, registering only the tools allowed by mode."""
    mcp = FastMCP(
        SERVER_NAME, host=host or config.host, port=port or config.port
    )
    client = client or SeafileClient(
        config.server_url,
        auth_scheme=config.auth_scheme,
        timeout=config.timeout,
        max_read_size=config.max_read_size,
        max_write_size=config.max_write_size,
    )
    store = store or SessionStore(config.session_path)
    mode = config.mode

    # -- session auth tools (all modes — they manage sessions, not Seafile data)
    @_friendly
    async def _auth_login(
        user_id: str,
        password: str,
        otp: str | None = None,
    ) -> Any:
        return await auth_tools.auth_login(
            config, client, store, user_id, password, otp
        )

    mcp.tool(
        name="auth_login",
        description="Validate user_id+password against Seafile and issue a "
        "full-scope session token. Password is used once, never stored.",
    )(_auth_login)

    @_friendly
    async def _auth_register_library(
        library_token: str,
        library_name: str | None = None,
        repo_id: str | None = None,
        user_id: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await auth_tools.auth_register_library(
            config, client, store, library_token,
            library_name=library_name, repo_id=repo_id,
            user_id=user_id, session_token=session_token,
        )

    mcp.tool(
        name="auth_register_library",
        description="Validate a library API token; bootstrap a scoped session "
        "or attach the library to an existing one. Returns the session token.",
    )(_auth_register_library)

    @_friendly
    async def _auth_reauth(
        session_token: str,
        password: str,
        otp: str | None = None,
    ) -> Any:
        return await auth_tools.auth_reauth(
            config, client, store, session_token, password, otp
        )

    mcp.tool(
        name="auth_reauth",
        description="Refresh a session after a password change.",
    )(_auth_reauth)

    @_friendly
    async def _auth_rotate(session_token: str) -> Any:
        return await auth_tools.auth_rotate(config, client, store, session_token)

    mcp.tool(
        name="auth_rotate",
        description="Replace a session token, keeping its credentials.",
    )(_auth_rotate)

    @_friendly
    async def _auth_revoke(session_token: str) -> Any:
        return await auth_tools.auth_revoke(config, client, store, session_token)

    mcp.tool(
        name="auth_revoke",
        description="Delete a session.",
    )(_auth_revoke)

    @_friendly
    async def _auth_add_library(
        session_token: str,
        library_token: str,
        library_name: str | None = None,
        repo_id: str | None = None,
    ) -> Any:
        return await auth_tools.auth_add_library(
            config, client, store, session_token, library_token,
            library_name=library_name, repo_id=repo_id,
        )

    mcp.tool(
        name="auth_add_library",
        description="Attach another library token to a session.",
    )(_auth_add_library)

    @_friendly
    async def _auth_remove_library(
        session_token: str, library_name: str
    ) -> Any:
        return await auth_tools.auth_remove_library(
            config, client, store, session_token, library_name
        )

    mcp.tool(
        name="auth_remove_library",
        description="Detach a library token from a session.",
    )(_auth_remove_library)

    @_friendly
    async def _auth_status(session_token: str) -> Any:
        return await auth_tools.auth_status(config, client, store, session_token)

    mcp.tool(
        name="auth_status",
        description="Show a session's scope and libraries (nothing secret).",
    )(_auth_status)

    # -- read tools (all modes) -------------------------------------------
    @_friendly
    async def _get_auth_help() -> str:
        return await help_tools.get_auth_help()

    mcp.tool(name="get_auth_help", description=help_tools.get_auth_help.__doc__ or "")(
        _get_auth_help
    )

    @_friendly
    async def _list_libraries(
        lib_type: str | None = None,
        account_token: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await libraries.list_libraries(
            config, client, store,
            lib_type=lib_type, account_token=account_token, session_token=session_token,
        )

    mcp.tool(
        name="list_libraries",
        description="List libraries visible to the account token. "
        "lib_type: mine, shared, group, mine-group, public (default: all).",
    )(_list_libraries)

    @_friendly
    async def _get_library_info(
        repo_id: str | None = None,
        library_name: str | None = None,
        account_token: str | None = None,
        repo_token: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await libraries.get_library_info(
            config, client, store, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, session_token=session_token,
        )

    mcp.tool(
        name="get_library_info",
        description="Get details of one library, by repo_id or name.",
    )(_get_library_info)

    @_friendly
    async def _resolve_library(
        library_name: str,
        account_token: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await libraries.resolve_library(
            config, client, store, library_name,
            account_token=account_token, session_token=session_token,
        )

    mcp.tool(
        name="resolve_library",
        description="Resolve a library name to its repo_id (account token only).",
    )(_resolve_library)

    @_friendly
    async def _list_directory(
        path: str = "/",
        recursive: bool = False,
        entry_type: str | None = None,
        repo_id: str | None = None,
        library_name: str | None = None,
        account_token: str | None = None,
        repo_token: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await files.list_directory(
            config, client, store, path=path, recursive=recursive,
            entry_type=entry_type, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, session_token=session_token,
        )

    mcp.tool(
        name="list_directory",
        description="List a directory. entry_type: 'f' files, 'd' folders.",
    )(_list_directory)

    @_friendly
    async def _get_file_detail(
        path: str,
        repo_id: str | None = None,
        library_name: str | None = None,
        account_token: str | None = None,
        repo_token: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await files.get_file_detail(
            config, client, store, path, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, session_token=session_token,
        )

    mcp.tool(
        name="get_file_detail",
        description="Get file metadata (account token only).",
    )(_get_file_detail)

    @_friendly
    async def _read_file(
        path: str,
        max_chars: int = 50000,
        repo_id: str | None = None,
        library_name: str | None = None,
        account_token: str | None = None,
        repo_token: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await files.read_file(
            config, client, store, path, max_chars=max_chars, repo_id=repo_id,
            library_name=library_name, account_token=account_token,
            repo_token=repo_token, session_token=session_token,
        )

    mcp.tool(
        name="read_file",
        description="Read a text file. Binary files return metadata + download link.",
    )(_read_file)

    @_friendly
    async def _get_download_link(
        path: str,
        repo_id: str | None = None,
        library_name: str | None = None,
        account_token: str | None = None,
        repo_token: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await files.get_download_link(
            config, client, store, path, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, session_token=session_token,
        )

    mcp.tool(name="get_download_link", description="Get a download URL for a file.")(
        _get_download_link
    )

    @_friendly
    async def _search_files(
        query: str,
        repo_id: str | None = None,
        library_name: str | None = None,
        account_token: str | None = None,
        repo_token: str | None = None,
        session_token: str | None = None,
    ) -> Any:
        return await files.search_files(
            config, client, store, query, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, session_token=session_token,
        )

    mcp.tool(
        name="search_files",
        description="Search files (account token only; needs search on server).",
    )(_search_files)

    # -- safe-write tools ---------------------------------------------------
    if mode in ("safe_write", "full"):

        @_friendly
        async def _create_library(
            name: str,
            password: str | None = None,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await libraries.create_library(
                config, client, store, name, password=password,
                account_token=account_token, session_token=session_token,
            )

        mcp.tool(
            name="create_library",
            description="Create a library (password -> encrypted).",
        )(_create_library)

        @_friendly
        async def _rename_library(
            name: str,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await libraries.rename_library(
                config, client, store, name, repo_id=repo_id,
                library_name=library_name, account_token=account_token,
                session_token=session_token,
            )

        mcp.tool(name="rename_library", description="Rename a library.")(_rename_library)

        @_friendly
        async def _create_directory(
            path: str,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            repo_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await files.create_directory(
                config, client, store, path, repo_id=repo_id,
                library_name=library_name, account_token=account_token,
                repo_token=repo_token, session_token=session_token,
            )

        mcp.tool(name="create_directory", description="Create a folder.")(_create_directory)

        @_friendly
        async def _upload_file(
            path: str,
            content: str,
            is_base64: bool = False,
            replace: bool = False,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            repo_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await files.upload_file(
                config, client, store, path, content, is_base64=is_base64,
                replace=replace, repo_id=repo_id, library_name=library_name,
                account_token=account_token, repo_token=repo_token, session_token=session_token,
            )

        mcp.tool(
            name="upload_file", description="Upload/create a file (text or base64)."
        )(_upload_file)

        @_friendly
        async def _update_file(
            path: str,
            content: str,
            is_base64: bool = False,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            repo_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await files.update_file(
                config, client, store, path, content, is_base64=is_base64,
                repo_id=repo_id, library_name=library_name,
                account_token=account_token, repo_token=repo_token, session_token=session_token,
            )

        mcp.tool(
            name="update_file", description="Overwrite a file (new version in history)."
        )(_update_file)

        @_friendly
        async def _rename_item(
            path: str,
            new_name: str,
            is_dir: bool = False,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            repo_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await files.rename_item(
                config, client, store, path, new_name, is_dir=is_dir,
                repo_id=repo_id, library_name=library_name,
                account_token=account_token, repo_token=repo_token, session_token=session_token,
            )

        mcp.tool(
            name="rename_item",
            description="Rename a file or folder (repo token: folders only).",
        )(_rename_item)

        @_friendly
        async def _move_item(
            path: str,
            dst_dir: str,
            dst_repo_id: str | None = None,
            is_dir: bool = False,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await files.move_item(
                config, client, store, path, dst_dir, dst_repo_id=dst_repo_id,
                is_dir=is_dir, repo_id=repo_id, library_name=library_name,
                account_token=account_token, session_token=session_token,
            )

        mcp.tool(
            name="move_item", description="Move a file or folder (account token only)."
        )(_move_item)

        @_friendly
        async def _copy_item(
            path: str,
            dst_dir: str,
            dst_repo_id: str | None = None,
            is_dir: bool = False,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await files.copy_item(
                config, client, store, path, dst_dir, dst_repo_id=dst_repo_id,
                is_dir=is_dir, repo_id=repo_id, library_name=library_name,
                account_token=account_token, session_token=session_token,
            )

        mcp.tool(
            name="copy_item", description="Copy a file or folder (account token only)."
        )(_copy_item)

        @_friendly
        async def _create_share_link(
            path: str,
            repo_id: str | None = None,
            library_name: str | None = None,
            password: str | None = None,
            expire_days: int | None = None,
            permissions: dict[str, bool] | None = None,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await sharing.create_share_link(
                config, client, store, path, repo_id=repo_id,
                library_name=library_name, password=password,
                expire_days=expire_days, permissions=permissions,
                account_token=account_token, session_token=session_token,
            )

        mcp.tool(
            name="create_share_link",
            description="Create a public share link for a file/folder "
            "(non-encrypted libraries only).",
        )(_create_share_link)

        @_friendly
        async def _list_share_links(
            repo_id: str | None = None,
            library_name: str | None = None,
            path: str | None = None,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await sharing.list_share_links(
                config, client, store, repo_id=repo_id,
                library_name=library_name, path=path,
                account_token=account_token, session_token=session_token,
            )

        mcp.tool(
            name="list_share_links",
            description="List share links, optionally filtered by library/path.",
        )(_list_share_links)

    # -- full mode: destructive tools ----------------------------------------
    if mode == "full":

        @_friendly
        async def _delete_library(
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await libraries.delete_library(
                config, client, store, repo_id=repo_id, library_name=library_name,
                account_token=account_token, session_token=session_token,
            )

        mcp.tool(
            name="delete_library",
            description="Delete a library PERMANENTLY (full mode only).",
        )(_delete_library)

        @_friendly
        async def _delete_item(
            path: str,
            is_dir: bool = False,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await files.delete_item(
                config, client, store, path, is_dir=is_dir, repo_id=repo_id,
                library_name=library_name, account_token=account_token,
                session_token=session_token,
            )

        mcp.tool(
            name="delete_item",
            description="Delete a file/folder to trash (full mode only).",
        )(_delete_item)

        @_friendly
        async def _delete_share_link(
            share_token: str,
            account_token: str | None = None,
            session_token: str | None = None,
        ) -> Any:
            return await sharing.delete_share_link(
                config, client, store, share_token,
                account_token=account_token, session_token=session_token,
            )

        mcp.tool(
            name="delete_share_link",
            description="Delete a share link by its token (full mode only).",
        )(_delete_share_link)

    return mcp, client, store


def _takes_host_port(fn: Any) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "host" in params and "port" in params


async def run_transport(
    mcp: Any, transport: str, host: str | None = None, port: int | None = None
) -> None:
    """Start the MCP transport on mcp v1 and v2 runtimes.

    v1.30+/v2 expose run_stdio_async/run_sse_async/run_streamable_http_async
    (v1 takes host/port from the constructor, v2 as kwargs); very old v1
    releases only had run_async(transport=...).
    """
    name = (transport or "stdio").strip().lower()
    if name not in ("stdio", "sse", "streamable-http"):
        raise ValueError(
            f"Unknown transport {name!r}. Use stdio, sse, or streamable-http."
        )
    if name == "stdio" and hasattr(mcp, "run_stdio_async"):
        await mcp.run_stdio_async()
        return
    if name == "streamable-http" and hasattr(mcp, "run_streamable_http_async"):
        fn = mcp.run_streamable_http_async
        if _takes_host_port(fn) and host is not None and port is not None:
            await fn(host=host, port=port)
        else:
            await fn()
        return
    if name == "sse" and hasattr(mcp, "run_sse_async"):
        fn = mcp.run_sse_async
        if _takes_host_port(fn) and host is not None and port is not None:
            await fn(host=host, port=port)
        else:
            await fn()
        return
    if hasattr(mcp, "run_async"):  # legacy mcp v1
        await mcp.run_async(transport=name)
        return
    raise AttributeError(
        f"Cannot start transport {name!r}: MCP server object has none of "
        "run_stdio_async/run_sse_async/run_streamable_http_async/run_async."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="seafile-mcp", description="Seafile MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=None,
        help="Transport (default: SEAFILE_TRANSPORT or stdio).",
    )
    parser.add_argument("--host", default=None, help="HTTP host (streamable-http).")
    parser.add_argument("--port", type=int, default=None, help="HTTP port.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    try:
        args = parse_args(argv)
    except SystemExit:
        raise
    try:
        config = Config.from_env()
    except ValueError as exc:
        import sys
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        print("Copy .env.example to .env and set SEAFILE_SERVER_URL.", file=sys.stderr)
        sys.exit(2)
    transport = args.transport or config.transport
    host = args.host or config.host
    port = args.port or config.port

    async def _run() -> None:
        mcp: Any = None
        client: SeafileClient | None = None
        try:
            mcp, client, _store = create_server(config, host=host, port=port)
            await run_transport(mcp, transport, host=host, port=port)
        except Exception as exc:
            import sys, traceback
            traceback.print_exc(file=sys.stderr)
            print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
            raise
        finally:
            try:
                if client is not None:
                    await client.aclose()
            except Exception:
                pass

    asyncio.run(_run())


if __name__ == "__main__":
    main()
