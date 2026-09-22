"""Bearer-token auth resolution.

Resolution order for every tool call:
  1. Explicit per-call parameters (account_token OR repo_token).
  2. The session record for session_token (issued by auth_login or
     auth_register_library, stored hash-keyed in the session store).
  3. Server defaults from environment (SEAFILE_ACCOUNT_TOKEN,
     SEAFILE_REPO_TOKENS_JSON[library_name]) — single-user fallback.
  4. Otherwise raise AuthError telling the caller exactly what to provide.

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
from .sessions import SessionError, SessionStore


class AuthError(Exception):
    """Raised when no usable credential is available, or scope is exceeded."""


class ScopeError(Exception):
    """Raised when an operation is not available for the credential type."""


@dataclass
class AuthContext:
    server_url: str
    kind: str  # "account" | "repo"
    token: str
    repo_id: str | None = None
    library_name: str | None = None
    auth_scheme: str = "auto"


def _account_ctx(config: Config, token: str) -> AuthContext:
    return AuthContext(
        server_url=config.server_url,
        kind="account",
        token=token,
        auth_scheme=config.auth_scheme,
    )


def _repo_ctx(
    config: Config,
    token: str,
    repo_id: str | None,
    library_name: str | None,
) -> AuthContext:
    return AuthContext(
        server_url=config.server_url,
        kind="repo",
        token=token,
        repo_id=repo_id,
        library_name=library_name,
        auth_scheme=config.auth_scheme,
    )


def resolve_auth(
    config: Config,
    *,
    account_token: str | None = None,
    repo_token: str | None = None,
    repo_id: str | None = None,
    library_name: str | None = None,
    session_token: str | None = None,
    store: SessionStore | None = None,
) -> AuthContext:
    """Resolve which credential a tool call runs with."""
    account_token = (account_token or "").strip() or None
    repo_token = (repo_token or "").strip() or None
    repo_id = (repo_id or "").strip() or None
    library_name = (library_name or "").strip() or None
    session_token = (session_token or "").strip() or None

    if account_token and repo_token:
        raise AuthError("Pass either account_token or repo_token, not both.")

    # 1. Explicit per-call account token -> full scope.
    if account_token:
        return _account_ctx(config, account_token)

    # 2. Explicit per-call repo token -> scoped to one library.
    if repo_token:
        if not repo_id and not library_name:
            raise AuthError(
                "repo_token was given but neither repo_id nor library_name. "
                "Pass one so the server knows which library to access."
            )
        return _repo_ctx(config, repo_token, repo_id, library_name)

    # 3. Session bearer token.
    if session_token:
        if store is None:
            raise AuthError("Session store is not configured on this server.")
        try:
            record = store.lookup(session_token)
        except SessionError as exc:
            raise AuthError(str(exc)) from exc
        if record is None:
            raise AuthError(
                "Unknown or revoked session token. Log in again with "
                "auth_login (account) or auth_register_library (library)."
            )
        if record.account_token:
            return _account_ctx(config, record.account_token)
        if library_name and library_name in record.repo_tokens:
            return _repo_ctx(
                config, record.repo_tokens[library_name], None, library_name
            )
        if library_name and record.repo_tokens:
            known = ", ".join(sorted(record.repo_tokens))
            raise AuthError(
                f"No token registered for library {library_name!r} "
                f"in this session. Session libraries: {known}. "
                "Attach it with auth_add_library."
            )
        if record.repo_tokens and not library_name:
            raise AuthError(
                "This session holds only library tokens; pass library_name "
                f"to select one ({', '.join(sorted(record.repo_tokens))})."
            )
        raise AuthError(
            "This session has no credentials stored. Attach an account token "
            "(auth_reauth) or library tokens (auth_add_library)."
        )

    # 4. Server default: account token.
    if config.account_token:
        return _account_ctx(config, config.account_token)

    # 5. Server default: per-library token map (requires library_name).
    if library_name and library_name in config.repo_tokens:
        return _repo_ctx(config, config.repo_tokens[library_name], None, library_name)
    if library_name and config.repo_tokens:
        known = ", ".join(sorted(config.repo_tokens))
        raise AuthError(
            f"No token configured for library {library_name!r}. "
            f"Libraries with tokens: {known}. "
            "Pass repo_token explicitly or add it to SEAFILE_REPO_TOKENS_JSON."
        )

    # 6. Nothing usable.
    raise AuthError(
        "No Seafile credential available. Log in with auth_login "
        "(then pass only session_token), register a library with "
        "auth_register_library, or pass account_token / repo_token "
        "explicitly. Server defaults can be set via SEAFILE_ACCOUNT_TOKEN / "
        "SEAFILE_REPO_TOKENS_JSON."
    )


def require_account(auth: AuthContext, operation: str) -> None:
    """Guard operations Seafile does not expose to repo (library API) tokens."""
    if auth.kind != "account":
        raise ScopeError(
            f"{operation} requires an account-token session, but this session "
            "holds only library tokens. Seafile only exposes "
            "library-management, move/copy/delete and search endpoints to "
            "account tokens. Log in with auth_login for full scope."
        )
