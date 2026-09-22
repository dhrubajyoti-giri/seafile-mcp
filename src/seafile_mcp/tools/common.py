"""Shared helpers for tool implementations."""

from __future__ import annotations

from ..auth import AuthContext, require_account, resolve_auth
from ..config import Config
from ..seafile_client import SeafileClient
from ..sessions import SessionStore


async def resolve(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    *,
    account_token: str | None = None,
    repo_token: str | None = None,
    repo_id: str | None = None,
    library_name: str | None = None,
    session_token: str | None = None,
) -> AuthContext:
    """Resolve per-call auth params against session record and server defaults."""
    return resolve_auth(
        config,
        account_token=account_token,
        repo_token=repo_token,
        repo_id=repo_id,
        library_name=library_name,
        session_token=session_token,
        store=store,
    )


async def resolve_repo_id(
    client: SeafileClient,
    auth: AuthContext,
    *,
    repo_id: str | None = None,
    library_name: str | None = None,
) -> str:
    """Return a concrete repo_id for account-scope calls.

    Accepts either a direct repo_id or a library name (resolved via the API).
    """
    if repo_id:
        return repo_id
    if library_name:
        lib = await client.resolve_library_name(auth.token, library_name)
        lib_id = lib.get("id") or lib.get("repo_id")
        if lib_id:
            return str(lib_id)
    raise ValueError(
        "This operation needs a library: pass repo_id or library_name."
    )


def account_only(auth: AuthContext, operation: str) -> None:
    require_account(auth, operation)
