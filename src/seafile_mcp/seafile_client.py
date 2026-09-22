"""Async HTTP client for the Seafile Web API (v2.1 / api2).

Two credential paths:
  - account token -> /api2/... endpoints (full scope).
  - repo (library API) token -> /api/v2.1/via-repo-token/... (one library).

Auth header scheme is configurable (auto | token | bearer). "auto" sends
``Token`` first (works on every Seafile version) and retries once with
``Bearer`` on a 401, caching the working scheme per token.
"""

from __future__ import annotations

from typing import Any

import httpx


class SeafileError(Exception):
    """Seafile API returned an error status."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        msg = data.get("error_msg") or data.get("error") or data.get("detail")
        if msg:
            return str(msg)
    text = (response.text or "").strip()
    return text[:300] if text else f"HTTP {response.status_code}"


class SeafileClient:
    def __init__(
        self,
        server_url: str,
        auth_scheme: str = "auto",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        if auth_scheme not in ("auto", "token", "bearer"):
            raise ValueError("auth_scheme must be auto, token or bearer")
        self.auth_scheme = auth_scheme
        self._client = httpx.AsyncClient(
            base_url=self.server_url, transport=transport, timeout=timeout
        )
        # token -> working scheme ("token" or "bearer"), learned on 401 retry.
        self._scheme_cache: dict[str, str] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- authentication --------------------------------------------------------

    async def obtain_account_token(
        self, username: str, password: str, otp: str | None = None
    ) -> str:
        """Exchange username+password for an account token.

        Used once per login/reauth; the password is never stored.
        Raises SeafileError on bad credentials (400) or missing 2FA (403).
        """
        headers: dict[str, str] = {}
        if (otp or "").strip():
            headers["X-SEAFILE-OTP"] = otp.strip()
        resp = await self._client.post(
            "/api2/auth-token/",
            data={"username": username.strip(), "password": password},
            headers={"Accept": "application/json", **headers},
        )
        if resp.status_code >= 400:
            raise SeafileError(_error_message(resp), status_code=resp.status_code)
        try:
            token = resp.json().get("token", "")
        except ValueError:
            token = ""
        if not token:
            raise SeafileError("Login succeeded but no token was returned.")
        return str(token)

    # -- account: libraries ----------------------------------------------

    async def list_libraries(
        self, token: str, lib_type: str | None = None
    ) -> list[dict[str, Any]]:
        params = {"type": lib_type} if lib_type else None
        data = await self._get_json("/api2/repos/", token, params=params)
        return data if isinstance(data, list) else []

    async def get_library(self, token: str, repo_id: str) -> dict[str, Any]:
        data = await self._get_json(f"/api2/repos/{repo_id}/", token)
        return data if isinstance(data, dict) else {}

    async def create_library(
        self, token: str, name: str, password: str | None = None
    ) -> dict[str, Any]:
        form: dict[str, Any] = {"name": name}
        if password:
            form["passwd"] = password
        resp = await self._request("POST", "/api2/repos/", token, data=form)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {"repo_id": resp.text.strip('" ')}

    async def rename_library(self, token: str, repo_id: str, name: str) -> None:
        await self._request(
            "POST", f"/api2/repos/{repo_id}/", token, params={"op": "rename"}, data={"repo_name": name}
        )

    async def delete_library(self, token: str, repo_id: str) -> None:
        await self._request("DELETE", f"/api2/repos/{repo_id}/", token)

    async def resolve_library_name(self, token: str, name: str) -> dict[str, Any]:
        """Find a library by exact name (case-insensitive fallback), one call."""
        lowered = name.lower()
        fallback: dict[str, Any] | None = None
        for lib in await self.list_libraries(token):
            lib_name = str(lib.get("name", ""))
            if lib_name == name:
                return lib
            if fallback is None and lib_name.lower() == lowered:
                fallback = lib
        if fallback is not None:
            return fallback
        raise SeafileError(f'Library not found: "{name}"', status_code=404)
