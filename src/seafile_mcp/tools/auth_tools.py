"""Session auth tools: login/register once, then call with session_token only."""

from __future__ import annotations

from ..auth import AuthError
from ..config import Config
from ..seafile_client import SeafileClient, SeafileError
from ..sessions import SessionError, SessionRecord, SessionStore, mask_token


def _issue(store: SessionStore, record: SessionRecord) -> dict:
    token = store.issue(record)
    return {
        "session_token": token,
        "user_id": record.user_id,
        "scope": "full" if record.account_token else "libraries",
        "libraries": sorted(record.repo_tokens),
        "notice": "Save this session_token — it is shown once and cannot be recovered.",
    }


def _require_session(store: SessionStore, session_token: str) -> SessionRecord:
    try:
        record = store.lookup(session_token)
    except SessionError as exc:
        raise AuthError(str(exc)) from exc
    if record is None:
        raise AuthError(
            "Unknown or revoked session token. Log in again with auth_login "
            "or auth_register_library."
        )
    return record


async def auth_login(
    config: Config,
    client: SeafileClient,
    store: SessionStore,
    user_id: str,
    password: str,
    otp: str | None = None,
) -> dict:
    """Validate user_id+password against Seafile and issue a full-scope
    session token. The password is used once and never stored."""
    user_id = (user_id or "").strip()
    if not user_id:
        raise AuthError("user_id must not be empty.")
    if not (password or "").strip():
        raise AuthError("password must not be empty.")
    try:
        account_token = await client.obtain_account_token(user_id, password, otp)
    except SeafileError as exc:
        hint = " (wrong password, or 2FA code missing/invalid — pass otp)" if exc.status_code in (400, 403) else ""
        raise AuthError(f"Seafile rejected the login: {exc}{hint}") from exc
    try:
        return _issue(store, SessionRecord(user_id=user_id, account_token=account_token))
    except SessionError as exc:
        raise AuthError(str(exc)) from exc


async def auth_register_library(
    config: Config,
    client: SeafileClient,
    store: SessionStore,
    library_token: str,
    library_name: str | None = None,
    repo_id: str | None = None,
    user_id: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Validate a library API token and attach it to a session.

    Without session_token this bootstraps a new scoped session and returns
    its token; with one it attaches the library to that session (and returns
    the same token back for convenience).
    """
    library_token = (library_token or "").strip()
    if not library_token:
        raise AuthError("library_token must not be empty.")
    label = (library_name or "").strip() or (repo_id or "").strip()
    if not label:
        raise AuthError("Pass library_name or repo_id to label this library.")
    try:
        info = await client.repo_get_info(library_token)
    except SeafileError as exc:
        raise AuthError(f"Seafile rejected the library token: {exc}") from exc
    if repo_id and info.get("repo_id") and str(info["repo_id"]) != repo_id.strip():
        raise AuthError(
            "Library token does not belong to the given repo_id. "
            "Check the library and token match."
        )
    try:
        if (session_token or "").strip():
            record = _require_session(store, session_token)
            record.repo_tokens[label] = library_token
            store.update(session_token, record)
            return {
                "session_token": session_token.strip(),
                "user_id": record.user_id,
                "scope": "full" if record.account_token else "libraries",
                "libraries": sorted(record.repo_tokens),
            }
        record = SessionRecord(
            user_id=(user_id or "").strip() or "library-user",
            repo_tokens={label: library_token},
        )
        return _issue(store, record)
    except SessionError as exc:
        raise AuthError(str(exc)) from exc


async def auth_reauth(
    config: Config,
    client: SeafileClient,
    store: SessionStore,
    session_token: str,
    password: str,
    otp: str | None = None,
) -> dict:
    """Refresh a session's stored account token after a password change."""
    record = _require_session(store, session_token)
    if not (password or "").strip():
        raise AuthError("password must not be empty.")
    try:
        record.account_token = await client.obtain_account_token(
            record.user_id, password, otp
        )
    except SeafileError as exc:
        raise AuthError(f"Seafile rejected the reauth: {exc}") from exc
    try:
        store.update(session_token, record)
    except SessionError as exc:
        raise AuthError(str(exc)) from exc
    return {
        "session_token": session_token.strip(),
        "user_id": record.user_id,
        "scope": "full",
        "reauthenticated": True,
    }


async def auth_rotate(
    config: Config, client: SeafileClient, store: SessionStore, session_token: str
) -> dict:
    """Replace a session token, keeping its credentials. Old token dies."""
    try:
        new_token = store.rotate(session_token)
        record = store.lookup(new_token)
    except SessionError as exc:
        raise AuthError(str(exc)) from exc
    return {
        "session_token": new_token,
        "user_id": record.user_id if record else "",
        "scope": "full" if (record and record.account_token) else "libraries",
        "libraries": sorted(record.repo_tokens) if record else [],
        "notice": "Save this session_token — the previous one no longer works.",
    }


async def auth_revoke(
    config: Config, client: SeafileClient, store: SessionStore, session_token: str
) -> dict:
    """Delete a session. Returns True if one existed."""
    try:
        return {"revoked": store.revoke(session_token)}
    except SessionError as exc:
        raise AuthError(str(exc)) from exc


async def auth_add_library(
    config: Config,
    client: SeafileClient,
    store: SessionStore,
    session_token: str,
    library_token: str,
    library_name: str | None = None,
    repo_id: str | None = None,
) -> dict:
    """Attach another library token to an existing session."""
    return await auth_register_library(
        config, client, store, library_token,
        library_name=library_name, repo_id=repo_id, session_token=session_token,
    )


async def auth_remove_library(
    config: Config,
    client: SeafileClient,
    store: SessionStore,
    session_token: str,
    library_name: str,
) -> dict:
    """Detach a library token from a session."""
    record = _require_session(store, session_token)
    label = (library_name or "").strip()
    if not label:
        raise AuthError("library_name must not be empty.")
    record.repo_tokens.pop(label, None)
    try:
        store.update(session_token, record)
    except SessionError as exc:
        raise AuthError(str(exc)) from exc
    return {
        "user_id": record.user_id,
        "scope": "full" if record.account_token else "libraries",
        "libraries": sorted(record.repo_tokens),
        "removed": label,
    }


async def auth_status(
    config: Config, client: SeafileClient, store: SessionStore, session_token: str
) -> dict:
    """Show a session's scope and libraries. Nothing secret is revealed."""
    record = _require_session(store, session_token)
    masked = record.masked()
    masked["user_id"] = record.user_id
    if record.account_token:
        masked["account_token_preview"] = mask_token(record.account_token)
    return masked
