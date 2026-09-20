"""User credential tools: register once, then call with only user_id."""

from __future__ import annotations

from ..config import Config
from ..vault import CredentialVault, VaultError


def _wrap(fn_name: str, action):
    try:
        record = action()
    except VaultError as exc:
        return {"error": str(exc), "tool": fn_name}
    return {"user_id": record.user_id, **record.masked()}


async def register_user(
    config: Config,
    vault: CredentialVault,
    user_id: str,
    account_token: str | None = None,
    repo_tokens: dict[str, str] | None = None,
) -> dict:
    """Register (or update) a user's credentials. Later calls need only user_id."""
    return _wrap(
        "register_user",
        lambda: vault.register(
            user_id, account_token=account_token, repo_tokens=repo_tokens
        ),
    )


async def update_account_token(
    config: Config, vault: CredentialVault, user_id: str, account_token: str
) -> dict:
    """Set or replace the stored account token (e.g. after a password change)."""
    return _wrap(
        "update_account_token",
        lambda: vault.set_account_token(user_id, account_token),
    )


async def add_library_tokens(
    config: Config,
    vault: CredentialVault,
    user_id: str,
    repo_tokens: dict[str, str],
) -> dict:
    """Add {library_name: token} pairs to a user's record."""
    return _wrap(
        "add_library_tokens", lambda: vault.add_repo_tokens(user_id, repo_tokens)
    )


async def remove_library_tokens(
    config: Config, vault: CredentialVault, user_id: str, library_names: list[str]
) -> dict:
    """Remove library tokens from a user's record."""
    return _wrap(
        "remove_library_tokens",
        lambda: vault.remove_repo_tokens(user_id, library_names),
    )


async def remove_account_token(
    config: Config, vault: CredentialVault, user_id: str
) -> dict:
    """Delete the stored account token (keeps library tokens)."""
    return _wrap(
        "remove_account_token", lambda: vault.remove_account_token(user_id)
    )


async def revoke_user(config: Config, vault: CredentialVault, user_id: str) -> dict:
    """Delete a user's entire credential record."""
    try:
        existed = vault.revoke_user(user_id)
    except VaultError as exc:
        return {"error": str(exc), "tool": "revoke_user"}
    return {"user_id": user_id.strip(), "revoked": existed}


async def my_credentials(
    config: Config, vault: CredentialVault, user_id: str
) -> dict:
    """Show what is registered for a user_id (tokens masked, never revealed)."""
    try:
        record = vault.get(user_id)
    except VaultError as exc:
        return {"error": str(exc), "tool": "my_credentials"}
    if record is None:
        return {
            "error": f"Unknown user_id {user_id.strip()!r}. "
            "Register first with register_user.",
            "tool": "my_credentials",
        }
    return record.masked()
