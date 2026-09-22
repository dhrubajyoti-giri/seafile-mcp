"""Seafile MCP server — FastMCP app with mode-gated tools and dual transports."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .auth import AuthError, ScopeError
from .config import Config
from .seafile_client import SeafileClient, SeafileError
from .tools import files, help as help_tools, libraries, sharing, users
from .vault import CredentialVault, VaultError

SERVER_NAME = "seafile-mcp"


def _friendly(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Convert auth/API errors into {"error": ...} payloads agents can act on."""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except (AuthError, ScopeError, SeafileError, VaultError, ValueError) as exc:
            status = getattr(exc, "status_code", None)
            payload: dict[str, Any] = {"error": str(exc)}
            if status is not None:
                payload["status_code"] = status
                if status == 401:
                    payload["hint"] = (
                        "Token invalid or expired. Account tokens are "
                        "invalidated by a password change — re-mint with the "
                        "curl command from get_auth_help, save it with "
                        "update_account_token, and retry."
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
    vault: CredentialVault | None = None,
    host: str | None = None,
    port: int | None = None,
) -> tuple[FastMCP, SeafileClient, CredentialVault]:
    """Build the FastMCP app, registering only the tools allowed by mode."""
    mcp = FastMCP(
        SERVER_NAME, host=host or config.host, port=port or config.port
    )
    client = client or SeafileClient(config.server_url, auth_scheme=config.auth_scheme)
    vault = vault or CredentialVault(config.vault_path)
    mode = config.mode

    # -- user credential tools (all modes — they manage the vault, not Seafile)
    @_friendly
    async def _register_user(
        user_id: str,
        account_token: str | None = None,
        repo_tokens: dict[str, str] | None = None,
    ) -> Any:
        return await users.register_user(
            config, vault, user_id,
            account_token=account_token, repo_tokens=repo_tokens,
        )

    mcp.tool(
        name="register_user",
        description="Register credentials once (account_token and/or "
        "{library_name: token} map). Later calls need only user_id.",
    )(_register_user)

    @_friendly
    async def _update_account_token(user_id: str, account_token: str) -> Any:
        return await users.update_account_token(config, vault, user_id, account_token)

    mcp.tool(
        name="update_account_token",
        description="Set/replace the stored account token (e.g. after password change).",
    )(_update_account_token)

    @_friendly
    async def _add_library_tokens(
        user_id: str, repo_tokens: dict[str, str]
    ) -> Any:
        return await users.add_library_tokens(config, vault, user_id, repo_tokens)

    mcp.tool(
        name="add_library_tokens",
        description="Add {library_name: token} pairs to a user's record.",
    )(_add_library_tokens)

    @_friendly
    async def _remove_library_tokens(
        user_id: str, library_names: list[str]
    ) -> Any:
        return await users.remove_library_tokens(config, vault, user_id, library_names)

    mcp.tool(
        name="remove_library_tokens",
        description="Remove library tokens from a user's record.",
    )(_remove_library_tokens)

    @_friendly
    async def _remove_account_token(user_id: str) -> Any:
        return await users.remove_account_token(config, vault, user_id)

    mcp.tool(
        name="remove_account_token",
        description="Delete the stored account token (keeps library tokens).",
    )(_remove_account_token)

    @_friendly
    async def _revoke_user(user_id: str) -> Any:
        return await users.revoke_user(config, vault, user_id)

    mcp.tool(
        name="revoke_user",
        description="Delete a user's entire credential record.",
    )(_revoke_user)

    @_friendly
    async def _my_credentials(user_id: str) -> Any:
        return await users.my_credentials(config, vault, user_id)

    mcp.tool(
        name="my_credentials",
        description="Show what is registered for a user_id (tokens masked).",
    )(_my_credentials)

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
        user_id: str | None = None,
    ) -> Any:
        return await libraries.list_libraries(
            config, client, vault,
            lib_type=lib_type, account_token=account_token, user_id=user_id,
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
        user_id: str | None = None,
    ) -> Any:
        return await libraries.get_library_info(
            config, client, vault, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, user_id=user_id,
        )

    mcp.tool(
        name="get_library_info",
        description="Get details of one library, by repo_id or name.",
    )(_get_library_info)

    @_friendly
    async def _resolve_library(
        library_name: str,
        account_token: str | None = None,
        user_id: str | None = None,
    ) -> Any:
        return await libraries.resolve_library(
            config, client, vault, library_name,
            account_token=account_token, user_id=user_id,
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
        user_id: str | None = None,
    ) -> Any:
        return await files.list_directory(
            config, client, vault, path=path, recursive=recursive,
            entry_type=entry_type, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, user_id=user_id,
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
        user_id: str | None = None,
    ) -> Any:
        return await files.get_file_detail(
            config, client, vault, path, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, user_id=user_id,
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
        user_id: str | None = None,
    ) -> Any:
        return await files.read_file(
            config, client, vault, path, max_chars=max_chars, repo_id=repo_id,
            library_name=library_name, account_token=account_token,
            repo_token=repo_token, user_id=user_id,
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
        user_id: str | None = None,
    ) -> Any:
        return await files.get_download_link(
            config, client, vault, path, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, user_id=user_id,
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
        user_id: str | None = None,
    ) -> Any:
        return await files.search_files(
            config, client, vault, query, repo_id=repo_id, library_name=library_name,
            account_token=account_token, repo_token=repo_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await libraries.create_library(
                config, client, vault, name, password=password,
                account_token=account_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await libraries.rename_library(
                config, client, vault, name, repo_id=repo_id,
                library_name=library_name, account_token=account_token,
                user_id=user_id,
            )

        mcp.tool(name="rename_library", description="Rename a library.")(_rename_library)

        @_friendly
        async def _create_directory(
            path: str,
            repo_id: str | None = None,
            library_name: str | None = None,
            account_token: str | None = None,
            repo_token: str | None = None,
            user_id: str | None = None,
        ) -> Any:
            return await files.create_directory(
                config, client, vault, path, repo_id=repo_id,
                library_name=library_name, account_token=account_token,
                repo_token=repo_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await files.upload_file(
                config, client, vault, path, content, is_base64=is_base64,
                replace=replace, repo_id=repo_id, library_name=library_name,
                account_token=account_token, repo_token=repo_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await files.update_file(
                config, client, vault, path, content, is_base64=is_base64,
                repo_id=repo_id, library_name=library_name,
                account_token=account_token, repo_token=repo_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await files.rename_item(
                config, client, vault, path, new_name, is_dir=is_dir,
                repo_id=repo_id, library_name=library_name,
                account_token=account_token, repo_token=repo_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await files.move_item(
                config, client, vault, path, dst_dir, dst_repo_id=dst_repo_id,
                is_dir=is_dir, repo_id=repo_id, library_name=library_name,
                account_token=account_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await files.copy_item(
                config, client, vault, path, dst_dir, dst_repo_id=dst_repo_id,
                is_dir=is_dir, repo_id=repo_id, library_name=library_name,
                account_token=account_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await sharing.create_share_link(
                config, client, vault, path, repo_id=repo_id,
                library_name=library_name, password=password,
                expire_days=expire_days, permissions=permissions,
                account_token=account_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await sharing.list_share_links(
                config, client, vault, repo_id=repo_id,
                library_name=library_name, path=path,
                account_token=account_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await libraries.delete_library(
                config, client, vault, repo_id=repo_id, library_name=library_name,
                account_token=account_token, user_id=user_id,
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
            user_id: str | None = None,
        ) -> Any:
            return await files.delete_item(
                config, client, vault, path, is_dir=is_dir, repo_id=repo_id,
                library_name=library_name, account_token=account_token,
                user_id=user_id,
            )

        mcp.tool(
            name="delete_item",
            description="Delete a file/folder to trash (full mode only).",
        )(_delete_item)

        @_friendly
        async def _delete_share_link(
            share_token: str,
            account_token: str | None = None,
            user_id: str | None = None,
        ) -> Any:
            return await sharing.delete_share_link(
                config, client, vault, share_token,
                account_token=account_token, user_id=user_id,
            )

        mcp.tool(
            name="delete_share_link",
            description="Delete a share link by its token (full mode only).",
        )(_delete_share_link)

    return mcp, client, vault


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="seafile-mcp", description="Seafile MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="Transport (default: SEAFILE_TRANSPORT or stdio).",
    )
    parser.add_argument("--host", default=None, help="HTTP host (streamable-http).")
    parser.add_argument("--port", type=int, default=None, help="HTTP port.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = Config.from_env()
    transport = args.transport or config.transport
    host = args.host or config.host
    port = args.port or config.port

    async def _run() -> None:
        mcp, client, _vault = create_server(config, host=host, port=port)
        try:
            await mcp.run_async(transport=transport)
        finally:
            await client.aclose()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
