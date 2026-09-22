"""Tests for session store: issue/lookup/update/rotate/revoke, hashing."""

import json

import pytest

from seafile_mcp.auth import AuthError, ScopeError, resolve_auth
from seafile_mcp.config import Config
from seafile_mcp.sessions import SessionError, SessionRecord, SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(str(tmp_path / "sessions.json"))


@pytest.fixture
def config():
    return Config.from_env({"SEAFILE_SERVER_URL": "https://seafile.example.com"})


def test_issue_lookup_roundtrip(store):
    token = store.issue(SessionRecord(user_id="alice", account_token="acct"))
    record = store.lookup(token)
    assert record is not None
    assert record.user_id == "alice"
    assert record.account_token == "acct"


def test_raw_token_never_persisted(store):
    token = store.issue(SessionRecord(user_id="alice", account_token="acct-tok"))
    dumped = open(store.path, encoding="utf-8").read()
    assert token not in dumped
    assert "acct-tok" in dumped  # Seafile tokens must work; session tokens must not
    data = json.loads(dumped)
    assert len(data) == 1
    key = next(iter(data))
    assert len(key) == 64  # sha256 hex


def test_lookup_unknown_returns_none(store):
    assert store.lookup("nope") is None
    assert store.lookup("") is None
    assert store.lookup("   ") is None


def test_update_and_rotate(store):
    token = store.issue(SessionRecord(user_id="alice", repo_tokens={"D": "t"}))
    record = store.lookup(token)
    record.repo_tokens["P"] = "t2"
    store.update(token, record)
    assert store.lookup(token).repo_tokens == {"D": "t", "P": "t2"}

    new_token = store.rotate(token)
    assert new_token != token
    assert store.lookup(token) is None
    rotated = store.lookup(new_token)
    assert rotated.repo_tokens == {"D": "t", "P": "t2"}


def test_rotate_unknown_raises(store):
    with pytest.raises(SessionError, match="[Uu]nknown or revoked"):
        store.rotate("ghost")


def test_revoke(store):
    token = store.issue(SessionRecord(user_id="alice", account_token="a"))
    assert store.revoke(token) is True
    assert store.lookup(token) is None
    assert store.revoke(token) is False


def test_store_file_permissions(store):
    import os
    import stat

    store.issue(SessionRecord(user_id="alice", account_token="a"))
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


def test_resolve_via_session_account(config, store):
    token = store.issue(SessionRecord(user_id="alice", account_token="acct"))
    auth = resolve_auth(config, session_token=token, store=store)
    assert auth.kind == "account" and auth.token == "acct"


def test_resolve_via_session_library(config, store):
    token = store.issue(SessionRecord(user_id="bob", repo_tokens={"Docs": "rt"}))
    auth = resolve_auth(
        config, session_token=token, library_name="Docs", store=store
    )
    assert auth.kind == "repo" and auth.token == "rt"


def test_resolve_unknown_session(config, store):
    with pytest.raises(AuthError, match="[Uu]nknown or revoked"):
        resolve_auth(config, session_token="ghost", store=store)


def test_explicit_token_beats_session(config, store):
    token = store.issue(SessionRecord(user_id="alice", account_token="vault-tok"))
    auth = resolve_auth(config, session_token=token, store=store, account_token="call")
    assert auth.token == "call"


def test_session_repo_user_blocked_from_account_ops(config, store):
    from seafile_mcp.auth import require_account

    token = store.issue(SessionRecord(user_id="bob", repo_tokens={"Docs": "rt"}))
    auth = resolve_auth(config, session_token=token, library_name="Docs", store=store)
    with pytest.raises(ScopeError, match="account-token session"):
        require_account(auth, "delete_library")


def test_session_library_only_needs_library_name(config, store):
    token = store.issue(SessionRecord(user_id="bob", repo_tokens={"Docs": "rt"}))
    with pytest.raises(AuthError, match="pass library_name"):
        resolve_auth(config, session_token=token, store=store)
