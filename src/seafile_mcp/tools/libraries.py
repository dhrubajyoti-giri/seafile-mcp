"""Library (repo) management tools. Account token only."""

from __future__ import annotations

from ..config import Config
from ..seafile_client import SeafileClient
from ..vault import CredentialVault
from .common import account_only, resolve, resolve_repo_id


async def list_libraries(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    lib_type: str | None = None,
    account_token: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    """List libraries visible to the account token."""
    auth = await resolve(
        config, client, vault, account_token=account_token, user_id=user_id
    )
    account_only(auth, "list_libraries")
    return await client.list_libraries(auth.token, lib_type=lib_type)


async def get_library_info(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Get details of one library. Repo-token callers get their own library's info."""
    auth = await resolve(
        config,
        client,
        vault,
        account_token=account_token,
        repo_token=repo_token,
        repo_id=repo_id,
        library_name=library_name,
        user_id=user_id,
    )
    if auth.kind == "repo":
        return await client.repo_get_info(auth.token)
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    return await client.get_library(auth.token, rid)


async def resolve_library(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    library_name: str,
    account_token: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Resolve a library name to its repo_id and metadata (account token)."""
    auth = await resolve(
        config, client, vault, account_token=account_token, user_id=user_id
    )
    account_only(auth, "resolve_library")
    return await client.resolve_library_name(auth.token, library_name)


async def create_library(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    name: str,
    password: str | None = None,
    account_token: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Create a library. Pass password to create an encrypted library."""
    auth = await resolve(
        config, client, vault, account_token=account_token, user_id=user_id
    )
    account_only(auth, "create_library")
    return await client.create_library(auth.token, name, password=password)


async def rename_library(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    name: str,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Rename a library."""
    auth = await resolve(
        config, client, vault, account_token=account_token, user_id=user_id
    )
    account_only(auth, "rename_library")
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    await client.rename_library(auth.token, rid, name)
    return {"repo_id": rid, "name": name, "renamed": True}


async def delete_library(
    config: Config,
    client: SeafileClient,
    vault: CredentialVault | None,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Delete a library permanently. Only registered in full mode."""
    auth = await resolve(
        config, client, vault, account_token=account_token, user_id=user_id
    )
    account_only(auth, "delete_library")
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    await client.delete_library(auth.token, rid)
    return {"repo_id": rid, "deleted": True}
