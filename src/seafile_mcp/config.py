"""Server configuration loaded from environment (.env supported)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

VALID_MODES = ("read_only", "safe_write", "full")
VALID_SCHEMES = ("auto", "token", "bearer")
VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


def _parse_repo_tokens(raw: str) -> dict[str, str]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "SEAFILE_REPO_TOKENS_JSON is not valid JSON. "
            'Expected e.g. {"My Library": "token..."}.'
        ) from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError(
            "SEAFILE_REPO_TOKENS_JSON must be a JSON object mapping "
            "library name (string) to token (string)."
        )
    return data


def _parse_positive_float(raw, name, default):
    try:
        value = float((raw or "").strip() or default)
    except ValueError as exc:
        raise ValueError(name + " must be a number.") from exc
    if value <= 0:
        raise ValueError(name + " must be > 0.")
    return value


def _parse_positive_int(raw, name, default):
    try:
        value = int((raw or "").strip() or default)
    except ValueError as exc:
        raise ValueError(name + " must be an integer.") from exc
    if value <= 0:
        raise ValueError(name + " must be > 0.")
    return value


@dataclass
class Config:
    server_url: str
    account_token: str | None = None
    repo_tokens: dict[str, str] = field(default_factory=dict)
    auth_scheme: str = "auto"
    mode: str = "safe_write"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    session_path: str = "~/.seafile-mcp/sessions.json"
    timeout: float = 60.0
    max_read_size: int = 10485760
    max_write_size: int = 52428800

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        src = env if env is not None else os.environ
        server_url = (src.get("SEAFILE_SERVER_URL") or "").strip().rstrip("/")
        if not server_url:
            raise ValueError(
                "SEAFILE_SERVER_URL is not set. Copy .env.example to .env "
                "and set it to your Seafile server base URL (no trailing slash)."
            )
        account_token = (src.get("SEAFILE_ACCOUNT_TOKEN") or "").strip() or None
        repo_tokens = _parse_repo_tokens(src.get("SEAFILE_REPO_TOKENS_JSON") or "")

        auth_scheme = (src.get("SEAFILE_AUTH_SCHEME") or "auto").strip().lower()
        if auth_scheme not in VALID_SCHEMES:
            raise ValueError(
                "Invalid SEAFILE_AUTH_SCHEME=" + repr(auth_scheme) + ". "
                "Valid: " + ", ".join(VALID_SCHEMES) + "."
            )
        mode = (src.get("SEAFILE_MCP_MODE") or "safe_write").strip().lower()
        if mode not in VALID_MODES:
            raise ValueError(
                "Invalid SEAFILE_MCP_MODE=" + repr(mode) + ". Valid: " + ", ".join(VALID_MODES) + "."
            )
        transport = (src.get("SEAFILE_TRANSPORT") or "stdio").strip().lower()
        if transport not in VALID_TRANSPORTS:
            raise ValueError(
                "Invalid SEAFILE_TRANSPORT=" + repr(transport) + ". "
                "Valid: " + ", ".join(VALID_TRANSPORTS) + "."
            )
        try:
            port = int(src.get("SEAFILE_PORT") or 8000)
        except ValueError as exc:
            raise ValueError("SEAFILE_PORT must be an integer.") from exc
        host = (src.get("SEAFILE_HOST") or "127.0.0.1").strip()
        session_path = (
            src.get("SEAFILE_SESSION_PATH") or "~/.seafile-mcp/sessions.json"
        ).strip()
        timeout = _parse_positive_float(src.get("SEAFILE_TIMEOUT"), "SEAFILE_TIMEOUT", 60.0)
        max_read_size = _parse_positive_int(
            src.get("SEAFILE_MAX_READ_SIZE"), "SEAFILE_MAX_READ_SIZE", 10485760
        )
        max_write_size = _parse_positive_int(
            src.get("SEAFILE_MAX_WRITE_SIZE"), "SEAFILE_MAX_WRITE_SIZE", 52428800
        )
        return cls(
            server_url=server_url,
            account_token=account_token,
            repo_tokens=repo_tokens,
            auth_scheme=auth_scheme,
            mode=mode,
            transport=transport,
            host=host,
            port=port,
            session_path=session_path,
            timeout=timeout,
            max_read_size=max_read_size,
            max_write_size=max_write_size,
        )
