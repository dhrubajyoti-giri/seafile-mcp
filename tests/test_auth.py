"""Tests for config parsing and hybrid auth resolution."""

import pytest

from seafile_mcp.auth import AuthError, ScopeError, require_account, resolve_auth
from seafile_mcp.config import Config


def make_config(**overrides):
    env = {
        "SEAFILE_SERVER_URL": "https://seafile.example.com",
        **overrides,
    }
    return Config.from_env(env)


def test_config_defaults():
    cfg = make_config()
    assert cfg.server_url == "https://seafile.example.com"
    assert cfg.mode == "safe_write"
    assert cfg.auth_scheme == "auto"
    assert cfg.account_token is None
    assert cfg.repo_tokens == {}


def test_config_strips_trailing_slash():
    cfg = make_config(SEAFILE_SERVER_URL="https://x.example.com/")
    assert cfg.server_url == "https://x.example.com"


def test_config_requires_server_url():
    with pytest.raises(ValueError, match="SEAFILE_SERVER_URL"):
        Config.from_env({})


def test_config_repo_tokens_json():
    cfg = make_config(SEAFILE_REPO_TOKENS_JSON='{"Docs": "aaa", "Pics": "bbb"}')
    assert cfg.repo_tokens == {"Docs": "aaa", "Pics": "bbb"}


def test_config_bad_repo_tokens_json():
    with pytest.raises(ValueError, match="SEAFILE_REPO_TOKENS_JSON"):
        make_config(SEAFILE_REPO_TOKENS_JSON="not-json")


def test_config_bad_mode():
    with pytest.raises(ValueError, match="SEAFILE_MCP_MODE"):
        make_config(SEAFILE_MCP_MODE="yolo")


def test_resolve_explicit_account_token():
    cfg = make_config(SEAFILE_ACCOUNT_TOKEN="env-token")
    auth = resolve_auth(cfg, account_token="call-token")
    assert auth.kind == "account" and auth.token == "call-token"


def test_resolve_env_account_token():
    cfg = make_config(SEAFILE_ACCOUNT_TOKEN="env-token")
    auth = resolve_auth(cfg)
    assert auth.kind == "account" and auth.token == "env-token"


def test_resolve_explicit_repo_token():
    cfg = make_config()
    auth = resolve_auth(cfg, repo_token="repo-tok", library_name="Docs")
    assert auth.kind == "repo" and auth.token == "repo-tok"


def test_resolve_repo_token_needs_library():
    cfg = make_config()
    with pytest.raises(AuthError, match="repo_id nor library_name"):
        resolve_auth(cfg, repo_token="repo-tok")


def test_resolve_env_repo_token_map():
    cfg = make_config(SEAFILE_REPO_TOKENS_JSON='{"Docs": "aaa"}')
    auth = resolve_auth(cfg, library_name="Docs")
    assert auth.kind == "repo" and auth.token == "aaa"


def test_resolve_unknown_library_name():
    cfg = make_config(SEAFILE_REPO_TOKENS_JSON='{"Docs": "aaa"}')
    with pytest.raises(AuthError, match="No token configured"):
        resolve_auth(cfg, library_name="Other")


def test_resolve_nothing_configured():
    cfg = make_config()
    with pytest.raises(AuthError, match="No Seafile credential"):
        resolve_auth(cfg)


def test_resolve_both_tokens_rejected():
    cfg = make_config()
    with pytest.raises(AuthError, match="not both"):
        resolve_auth(cfg, account_token="a", repo_token="r", library_name="Docs")


def test_require_account_blocks_repo_token():
    cfg = make_config(SEAFILE_REPO_TOKENS_JSON='{"Docs": "aaa"}')
    auth = resolve_auth(cfg, library_name="Docs")
    with pytest.raises(ScopeError, match="requires an account token"):
        require_account(auth, "delete_item")
