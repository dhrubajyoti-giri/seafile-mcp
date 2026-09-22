"""Share-link tools: create/list (safe_write), delete (full). Account token only."""

from __future__ import annotations

from ..config import Config
from ..seafile_client import SeafileClient
from ..vault import CredentialVault
from .common import account_only, resolve, resolve_repo_id
from .files import _require_path


async def create_share_link(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    path: str,
    repo_id: str | None = None,
    library_name: str | None = None,
    password: str | None = None,
    expire_days: int | None = None,
    permissions: dict[str, bool] | None = None,
    account_token: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Create a public share link for a file or folder. Only works on
    non-encrypted libraries."""
    path = _require_path(path)
    auth = await resolve(
        config, client, vault,
        account_token=account_token, user_id=user_id,
        repo_id=repo_id, library_name=library_name,
    )
    account_only(auth, "create_share_link")
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    return await client.create_share_link(
        auth.token, rid, path,
        password=password, expire_days=expire_days, permissions=permissions,
    )


async def list_share_links(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    repo_id: str | None = None,
    library_name: str | None = None,
    path: str | None = None,
    account_token: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    """List share links, optionally filtered to one library and/or path."""
    auth = await resolve(
        config, client, vault,
        account_token=account_token, user_id=user_id,
        repo_id=repo_id, library_name=library_name,
    )
    account_only(auth, "list_share_links")
    rid = None
    if repo_id or library_name:
        rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    clean_path = _require_path(path) if (path or "").strip() else None
    return await client.list_share_links(auth.token, repo_id=rid, path=clean_path)


async def delete_share_link(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    share_token: str,
    account_token: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Delete a share link by its token (the short id in the link URL).
    Only registered in full mode."""
    if not (share_token or "").strip():
        raise ValueError("share_token must not be empty.")
    auth = await resolve(
        config, client, vault, account_token=account_token, user_id=user_id
    )
    account_only(auth, "delete_share_link")
    await client.delete_share_link(auth.token, share_token.strip())
    return {"share_token": share_token.strip(), "deleted": True}
