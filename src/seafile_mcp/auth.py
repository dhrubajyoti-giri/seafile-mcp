"""Hybrid multi-user auth resolution.

Resolution order for every tool call:
  1. Explicit per-call parameters (account_token OR repo_token).
  2. The per-user vault record for user_id (registered via register_user).
  3. Server defaults from environment (SEAFILE_ACCOUNT_TOKEN,
     SEAFILE_REPO_TOKENS_JSON[library_name]) — single-user fallback.
  4. Otherwise raise AuthError telling the caller exactly what to provide.

Tokens only — this server never accepts passwords (see README for the
one-time curl command that mints an account token).

Scope rule:
  - account token -> full scope (all libraries, all tools).
  - repo (library API) token -> only that library, and only the endpoints
    Seafile exposes under /api/v2.1/via-repo-token/ (browse, read, mkdir,
    rename-dir, upload, download). Library management, move/copy/delete and
    search require an account token.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .vault import CredentialVault, VaultError


class AuthError(Exception):
    """Raised when no usable credential is available, or scope is exceeded."""


class ScopeError(Exception):
    """Raised when an operation is not available for the credential type."""


@dataclass
class AuthContext:
    server_url: str
    kind: str  # "account" | "repo"
    token: str
    # Repo mode identifiers. repo_id may be None when only library_name was
    # given; callers resolve it via the repo token's own "repo info" endpoint.
    repo_id: str | None = None
    library_name: str | None = None
    auth_scheme: str = "auto"


def resolve_auth(
    config: Config,
    *,
    account_token: str | None = None,
    repo_token: str | None = None,
    repo_id: str | None = None,
    library_name: str | None = None,
    user_id: str | None = None,
    vault: CredentialVault | None = None,
) -> AuthContext:
    """Resolve which credential a tool call runs with."""
    account_token = (account_token or "").strip() or None
    repo_token = (repo_token or "").strip() or None
    repo_id = (repo_id or "").strip() or None
    library_name = (library_name or "").strip() or None
    user_id = (user_id or "").strip() or None

    if account_token and repo_token:
        raise AuthError(
            "Pass either account_token or repo_token, not both."
        )

    # 1. Explicit per-call account token -> full scope.
    if account_token:
        return AuthContext(
            server_url=config.server_url,
            kind="account",
            token=account_token,
            auth_scheme=config.auth_scheme,
        )

    # 2. Explicit per-call repo token -> scoped to one library.
    if repo_token:
        if not repo_id and not library_name:
            raise AuthError(
                "repo_token was given but neither repo_id nor library_name. "
                "Pass one so the server knows which library to access."
            )
        return AuthContext(
            server_url=config.server_url,
            kind="repo",
            token=repo_token,
            repo_id=repo_id,
            library_name=library_name,
            auth_scheme=config.auth_scheme,
        )

    # 3. Per-user vault record.
    if user_id:
        if vault is None:
            raise AuthError("Credential vault is not configured on this server.")
        try:
            record = vault.get(user_id)
        except VaultError as exc:
            raise AuthError(str(exc)) from exc
        if record is None:
            raise AuthError(
                f'Unknown user_id {user_id!r}. Register first with register_user '
                "(user_id + account_token and/or library tokens), then pass "
                "only user_id on later calls."
            )
        if record.account_token:
            return AuthContext(
                server_url=config.server_url,
                kind="account",
                token=record.account_token,
                auth_scheme=config.auth_scheme,
            )
        if library_name and library_name in record.repo_tokens:
            return AuthContext(
                server_url=config.server_url,
                kind="repo",
                token=record.repo_tokens[library_name],
                library_name=library_name,
                auth_scheme=config.auth_scheme,
            )
        if library_name and record.repo_tokens:
            known = ", ".join(sorted(record.repo_tokens))
            raise AuthError(
                f'No token registered for library {library_name!r} '
                f"under user_id {user_id!r}. Registered libraries: {known}. "
                "Add it with add_library_tokens."
            )
        if record.repo_tokens and not library_name:
            raise AuthError(
                f"user_id {user_id!r} has only library tokens registered; "
                "pass library_name to select one "
                f"({', '.join(sorted(record.repo_tokens))})."
            )
        raise AuthError(
            f"user_id {user_id!r} is registered but has no credentials. "
            "Add an account token (update_account_token) or library tokens "
            "(add_library_tokens)."
        )

    # 4. Server default: account token.
    if config.account_token:
        return AuthContext(
            server_url=config.server_url,
            kind="account",
            token=config.account_token,
            auth_scheme=config.auth_scheme,
        )

    # 5. Server default: per-library token map (requires library_name).
    if library_name and library_name in config.repo_tokens:
        return AuthContext(
            server_url=config.server_url,
            kind="repo",
            token=config.repo_tokens[library_name],
            library_name=library_name,
            auth_scheme=config.auth_scheme,
        )
    if library_name and config.repo_tokens:
        known = ", ".join(sorted(config.repo_tokens))
        raise AuthError(
            f'No token configured for library {library_name!r}. '
            f"Libraries with tokens: {known}. "
            "Pass repo_token explicitly or add it to SEAFILE_REPO_TOKENS_JSON."
        )

    # 6. Nothing usable.
    raise AuthError(
        "No Seafile credential available. Either register once with "
        "register_user (then pass only user_id), pass account_token "
        "(full access — mint it once with the curl command in the README), "
        "or pass repo_token (+ repo_id or library_name) for single-library "
        "access. Server defaults can be set via SEAFILE_ACCOUNT_TOKEN / "
        "SEAFILE_REPO_TOKENS_JSON."
    )


def require_account(auth: AuthContext, operation: str) -> None:
    """Guard operations Seafile does not expose to repo (library API) tokens."""
    if auth.kind != "account":
        raise ScopeError(
            f"{operation} requires an account token, but this call is using a "
            "library API token. Seafile only exposes library-management, "
            "move/copy/delete and search endpoints to account tokens. "
            "Re-run with account_token to use full scope."
        )
