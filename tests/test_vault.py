"""Tests for the per-user credential vault and vault-based auth resolution."""

import json

import pytest

from seafile_mcp.auth import AuthError, ScopeError, resolve_auth
from seafile_mcp.config import Config
from seafile_mcp.vault import CredentialVault, UserRecord, VaultError, mask_token


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(str(tmp_path / "vault.json"))


@pytest.fixture
def config():
    return Config.from_env({"SEAFILE_SERVER_URL": "https://seafile.example.com"})


def test_register_and_get_roundtrip(vault):
    record = vault.register(
        "alice", account_token="acct-tok", repo_tokens={"Docs": "repo-tok"}
    )
    assert isinstance(record, UserRecord)
    loaded = vault.get("alice")
    assert loaded is not None
    assert loaded.account_token == "acct-tok"
    assert loaded.repo_tokens == {"Docs": "repo-tok"}


def test_register_requires_something(vault):
    with pytest.raises(VaultError, match="Nothing to register"):
        vault.register("bob")


def test_register_merges_on_update(vault):
    vault.register("alice", repo_tokens={"Docs": "t1"})
    updated = vault.register("alice", repo_tokens={"Pics": "t2"})
    assert updated.repo_tokens == {"Docs": "t1", "Pics": "t2"}


def test_set_account_token_unknown_user(vault):
    with pytest.raises(VaultError, match="Unknown user_id"):
        vault.set_account_token("ghost", "tok")


def test_add_remove_library_tokens(vault):
    vault.register("alice", account_token="acct")
    vault.add_repo_tokens("alice", {"Docs": "t1", "Pics": "t2"})
    assert vault.get("alice").repo_tokens == {"Docs": "t1", "Pics": "t2"}
    vault.remove_repo_tokens("alice", ["Docs"])
    assert vault.get("alice").repo_tokens == {"Pics": "t2"}


def test_revoke_user(vault):
    vault.register("alice", account_token="acct")
    assert vault.revoke_user("alice") is True
    assert vault.get("alice") is None
    assert vault.revoke_user("alice") is False


def test_masked_never_reveals_tokens(vault):
    vault.register("alice", account_token="acct-token-xyz", repo_tokens={"D": "r-t"})
    masked = vault.get("alice").masked()
    dumped = json.dumps(masked)
    assert "acct-token-xyz" not in dumped and "r-t" not in dumped
    assert masked["has_account_token"] is True
    assert masked["libraries"] == ["D"]


def test_mask_token_short():
    assert mask_token("abc") == "****"


def test_vault_file_permissions(vault):
    import os
    import stat

    vault.register("alice", account_token="acct")
    mode = stat.S_IMODE(os.stat(vault.path).st_mode)
    assert mode == 0o600


def test_resolve_via_vault_account(config, vault):
    vault.register("alice", account_token="acct-tok")
    auth = resolve_auth(config, user_id="alice", vault=vault)
    assert auth.kind == "account" and auth.token == "acct-tok"


def test_resolve_via_vault_library(config, vault):
    vault.register("alice", repo_tokens={"Docs": "repo-tok"})
    auth = resolve_auth(config, user_id="alice", library_name="Docs", vault=vault)
    assert auth.kind == "repo" and auth.token == "repo-tok"


def test_resolve_unknown_user_id(config, vault):
    with pytest.raises(AuthError, match="Unknown user_id"):
        resolve_auth(config, user_id="ghost", vault=vault)


def test_explicit_token_beats_vault(config, vault):
    vault.register("alice", account_token="vault-tok")
    auth = resolve_auth(config, user_id="alice", vault=vault, account_token="call-tok")
    assert auth.token == "call-tok"


def test_vault_repo_user_blocked_from_account_ops(config, vault):
    from seafile_mcp.auth import require_account

    vault.register("alice", repo_tokens={"Docs": "repo-tok"})
    auth = resolve_auth(config, user_id="alice", library_name="Docs", vault=vault)
    with pytest.raises(ScopeError, match="requires an account token"):
        require_account(auth, "delete_library")


def test_vault_library_only_user_needs_library_name(config, vault):
    vault.register("alice", repo_tokens={"Docs": "repo-tok"})
    with pytest.raises(AuthError, match="pass library_name"):
        resolve_auth(config, user_id="alice", vault=vault)
