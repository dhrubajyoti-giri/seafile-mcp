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

import json
import os
import tempfile
from dataclasses import dataclass, field


class VaultError(Exception):
    """Raised for unknown users or invalid vault operations."""


def mask_token(token: str) -> str:
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}…{token[-2:]}"


@dataclass
class UserRecord:
    user_id: str
    account_token: str | None = None
    repo_tokens: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "account_token": self.account_token,
            "repo_tokens": dict(self.repo_tokens),
        }

    def masked(self) -> dict:
        return {
            "user_id": self.user_id,
            "has_account_token": self.account_token is not None,
            "account_token_preview": mask_token(self.account_token)
            if self.account_token
            else None,
            "libraries": sorted(self.repo_tokens),
            "library_token_previews": {
                name: mask_token(tok) for name, tok in sorted(self.repo_tokens.items())
            },
        }


def _validate_user_id(user_id: str) -> str:
    user_id = (user_id or "").strip()
    if not user_id:
        raise VaultError("user_id must not be empty.")
    if len(user_id) > 128:
        raise VaultError("user_id is too long (max 128 chars).")
    return user_id


def _validate_token(token: str, what: str) -> str:
    token = (token or "").strip()
    if not token:
        raise VaultError(f"{what} must not be empty.")
    return token


class CredentialVault:
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
            raise VaultError(f"Credential vault unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise VaultError("Credential vault is corrupt (top level not an object).")
        return data

    def _save_all(self, data: dict[str, dict]) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".vault-", suffix=".tmp")
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
            raise VaultError(f"Could not write credential vault: {exc}") from exc

    # -- operations --------------------------------------------------------

    def register(
        self,
        user_id: str,
        account_token: str | None = None,
        repo_tokens: dict[str, str] | None = None,
    ) -> UserRecord:
        """Create or update a user's record (upsert)."""
        user_id = _validate_user_id(user_id)
        if account_token is not None:
            account_token = _validate_token(account_token, "account_token")
        clean_repos: dict[str, str] = {}
        for name, tok in (repo_tokens or {}).items():
            name = (name or "").strip()
            if not name:
                raise VaultError("Library names must not be empty.")
            clean_repos[name] = _validate_token(tok, f"token for library {name!r}")

        data = self._load_all()
        existing = data.get(user_id, {})
        record = UserRecord(
            user_id=user_id,
            account_token=account_token
            if account_token is not None
            else existing.get("account_token"),
            repo_tokens={**(existing.get("repo_tokens") or {}), **clean_repos},
        )
        if record.account_token is None and not record.repo_tokens:
            raise VaultError(
                "Nothing to register: pass account_token and/or repo_tokens "
                "(a {library_name: token} object)."
            )
        data[user_id] = record.to_dict()
        self._save_all(data)
        return record

    def set_account_token(self, user_id: str, account_token: str) -> UserRecord:
        user_id = _validate_user_id(user_id)
        data = self._load_all()
        if user_id not in data:
            raise VaultError(
                f'Unknown user_id {user_id!r}. Register first with register_user.'
            )
        data[user_id]["account_token"] = _validate_token(account_token, "account_token")
        self._save_all(data)
        return self.get(user_id)  # type: ignore[return-value]

    def add_repo_tokens(
        self, user_id: str, repo_tokens: dict[str, str]
    ) -> UserRecord:
        if not repo_tokens:
            raise VaultError("repo_tokens must not be empty.")
        # Reuse register's merge logic via a direct update.
        user_id = _validate_user_id(user_id)
        data = self._load_all()
        if user_id not in data:
            raise VaultError(
                f'Unknown user_id {user_id!r}. Register first with register_user.'
            )
        repos = data[user_id].setdefault("repo_tokens", {})
        for name, tok in repo_tokens.items():
            name = (name or "").strip()
            if not name:
                raise VaultError("Library names must not be empty.")
            repos[name] = _validate_token(tok, f"token for library {name!r}")
        self._save_all(data)
        return self.get(user_id)  # type: ignore[return-value]

    def remove_repo_tokens(
        self, user_id: str, library_names: list[str]
    ) -> UserRecord:
        user_id = _validate_user_id(user_id)
        data = self._load_all()
        if user_id not in data:
            raise VaultError(f"Unknown user_id {user_id!r}. Nothing to remove.")
        repos = data[user_id].get("repo_tokens") or {}
        for name in library_names:
            repos.pop(name, None)
        data[user_id]["repo_tokens"] = repos
        self._save_all(data)
        return self.get(user_id)  # type: ignore[return-value]

    def remove_account_token(self, user_id: str) -> UserRecord:
        user_id = _validate_user_id(user_id)
        data = self._load_all()
        if user_id not in data:
            raise VaultError(f"Unknown user_id {user_id!r}. Nothing to remove.")
        data[user_id]["account_token"] = None
        self._save_all(data)
        return self.get(user_id)  # type: ignore[return-value]

    def revoke_user(self, user_id: str) -> bool:
        """Delete a user's entire record. Returns True if one existed."""
        user_id = _validate_user_id(user_id)
        data = self._load_all()
        if user_id not in data:
            return False
        del data[user_id]
        self._save_all(data)
        return True

    def get(self, user_id: str) -> UserRecord | None:
        user_id = _validate_user_id(user_id)
        raw = self._load_all().get(user_id)
        if raw is None:
            return None
        return UserRecord(
            user_id=user_id,
            account_token=raw.get("account_token"),
            repo_tokens=dict(raw.get("repo_tokens") or {}),
        )

    def list_user_ids(self) -> list[str]:
        return sorted(self._load_all())
