"""Per-user credential vault.

Multi-user flow without fixed tokens in .env:
  - A client registers once: user_id + account_token and/or
    {library_name: repo_token} pairs. Saved to a JSON file (mode 0600).
  - Later calls pass only user_id; the vault supplies the tokens.
  - Clients can update, add/remove libraries, or revoke everything.

Security notes (also in README):
  - user_id is self-asserted by the caller — it is a namespace, not an
    identity proof. Protect the HTTP endpoint per user (reverse-proxy auth
    or VPN); otherwise anyone could pass another user's id.
  - Tokens rest in a JSON file with owner-only permissions. Back up and
    protect the host accordingly. Writes are atomic (temp file + rename),
    but concurrent writes from parallel requests can clobber each other
    (last writer wins); registration calls are infrequent enough that this
    is accepted rather than adding a file-lock dependency.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass, field


class SessionError(Exception):
    """Raised for unknown/expired sessions or invalid session operations."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_token(token: str) -> str:
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}…{token[-2:]}"


@dataclass
class SessionRecord:
    user_id: str
    account_token: str | None = None
    repo_tokens: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "account_token": self.account_token,
            "repo_tokens": dict(self.repo_tokens),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, user_id: str, raw: dict) -> "SessionRecord":
        return cls(
            user_id=user_id,
            account_token=raw.get("account_token"),
            repo_tokens=dict(raw.get("repo_tokens") or {}),
            created_at=float(raw.get("created_at") or 0),
        )

    def masked(self) -> dict:
        return {
            "has_account_token": self.account_token is not None,
            "libraries": sorted(self.repo_tokens),
            "created_at": self.created_at,
        }


def _validate_user_id(user_id: str) -> str:
    user_id = (user_id or "").strip()
    if not user_id:
        raise SessionError("user_id must not be empty.")
    if len(user_id) > 128:
        raise SessionError("user_id is too long (max 128 chars).")
    return user_id


def _validate_token(token: str, what: str) -> str:
    token = (token or "").strip()
    if not token:
        raise SessionError(f"{what} must not be empty.")
    return token


class SessionStore:
    def __init__(self, path: str) -> None:
        self.path = os.path.expanduser(path)

    # -- persistence -----------------------------------------------------

    def _load_all(self) -> dict[str, dict]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            raise SessionError(f"Session store unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise SessionError("Session store is corrupt (top level not an object).")
        return data

    def _save_all(self, data: dict[str, dict]) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".sessions-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise SessionError(f"Could not write session store: {exc}") from exc

    # -- sessions ----------------------------------------------------------

    def issue(self, record: SessionRecord) -> str:
        """Store a record, returning a fresh bearer token (shown once)."""
        token = secrets.token_urlsafe(32)
        data = self._load_all()
        data[_hash(token)] = {"user_id": record.user_id, **record.to_dict()}
        self._save_all(data)
        return token

    def lookup(self, session_token: str) -> SessionRecord | None:
        session_token = (session_token or "").strip()
        if not session_token:
            return None
        raw = self._load_all().get(_hash(session_token))
        if raw is None:
            return None
        return SessionRecord.from_dict(raw.get("user_id", ""), raw)

    def update(self, session_token: str, record: SessionRecord) -> None:
        key = _hash((session_token or "").strip())
        data = self._load_all()
        if key not in data:
            raise SessionError("Unknown or revoked session token.")
        data[key] = {"user_id": record.user_id, **record.to_dict()}
        self._save_all(data)

    def rotate(self, session_token: str) -> str:
        """Replace a session token, keeping the record. Returns the new token."""
        key = _hash((session_token or "").strip())
        data = self._load_all()
        raw = data.pop(key, None)
        if raw is None:
            raise SessionError("Unknown or revoked session token.")
        new_token = secrets.token_urlsafe(32)
        data[_hash(new_token)] = raw
        self._save_all(data)
        return new_token

    def revoke(self, session_token: str) -> bool:
        """Delete a session. Returns True if one existed."""
        key = _hash((session_token or "").strip())
        data = self._load_all()
        if key not in data:
            return False
        del data[key]
        self._save_all(data)
        return True
