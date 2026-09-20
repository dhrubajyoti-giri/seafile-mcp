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

    # -- low level ------------------------------------------------------

    def _schemes_to_try(self, token: str) -> list[str]:
        if self.auth_scheme != "auto":
            return [self.auth_scheme]
        cached = self._scheme_cache.get(token)
        if cached:
            return [cached]
        return ["token", "bearer"]

    async def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        last: httpx.Response | None = None
        for scheme in self._schemes_to_try(token):
            auth_value = f"{'Token' if scheme == 'token' else 'Bearer'} {token}"
            req_headers = {"Authorization": auth_value, "Accept": "application/json"}
            if headers:
                req_headers.update(headers)
            last = await self._client.request(
                method, path, params=params, data=data, json=json, headers=req_headers
            )
            if last.status_code != 401 or self.auth_scheme != "auto":
                break
            continue  # try next scheme
        assert last is not None
        # Remember which scheme worked for this token.
        if last.status_code != 401 and self.auth_scheme == "auto":
            used = "bearer" if "Bearer" in (last.request.headers.get("Authorization", "")) else "token"
            self._scheme_cache[token] = used
        if last.status_code >= 400:
            raise SeafileError(_error_message(last), status_code=last.status_code)
        return last

    async def _get_json(
        self, path: str, token: str, params: dict[str, Any] | None = None
    ) -> Any:
        resp = await self._request("GET", path, token, params=params)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

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
        """Find a library by exact name (case-insensitive fallback)."""
        for lib in await self.list_libraries(token):
            if lib.get("name") == name:
                return lib
        lowered = name.lower()
        for lib in await self.list_libraries(token):
            if str(lib.get("name", "")).lower() == lowered:
                return lib
        raise SeafileError(f'Library not found: "{name}"', status_code=404)

    # -- account: files & folders ------------------------------------------

    async def list_dir(
        self, token: str, repo_id: str, path: str = "/", recursive: bool = False
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"p": path}
        if recursive:
            params["recursive"] = 1
        data = await self._get_json(f"/api2/repos/{repo_id}/dir/", token, params=params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("dirent_list"), list):
            return data["dirent_list"]
        return []

    async def get_file_detail(
        self, token: str, repo_id: str, path: str
    ) -> dict[str, Any]:
        data = await self._get_json(
            f"/api2/repos/{repo_id}/file/detail/", token, params={"p": path}
        )
        return data if isinstance(data, dict) else {}

    async def file_operation(
        self,
        token: str,
        repo_id: str,
        path: str,
        operation: str,
        extra: dict[str, Any] | None = None,
    ) -> Any:
        """operation: create | rename | move | copy | revert (files)."""
        form: dict[str, Any] = {"operation": operation}
        if extra:
            form.update(extra)
        resp = await self._request(
            "POST", f"/api2/repos/{repo_id}/file/", token, params={"p": path}, data=form
        )
        try:
            return resp.json()
        except ValueError:
            return resp.text

    async def dir_operation(
        self,
        token: str,
        repo_id: str,
        path: str,
        operation: str,
        extra: dict[str, Any] | None = None,
    ) -> Any:
        """operation: mkdir | rename | move | copy (directories)."""
        form: dict[str, Any] = {"operation": operation}
        if extra:
            form.update(extra)
        resp = await self._request(
            "POST", f"/api2/repos/{repo_id}/dir/", token, params={"p": path}, data=form
        )
        try:
            return resp.json()
        except ValueError:
            return resp.text

    async def delete_file(self, token: str, repo_id: str, path: str) -> None:
        await self._request(
            "DELETE", f"/api2/repos/{repo_id}/file/", token, params={"p": path}
        )

    async def delete_dir(self, token: str, repo_id: str, path: str) -> None:
        await self._request(
            "DELETE", f"/api2/repos/{repo_id}/dir/", token, params={"p": path}
        )

    async def get_download_link(
        self, token: str, repo_id: str, path: str, reuse: bool = True
    ) -> str:
        resp = await self._request(
            "GET",
            f"/api2/repos/{repo_id}/file/",
            token,
            params={"p": path, "reuse": 1 if reuse else 0},
        )
        return resp.text.strip().strip('"')

    async def get_upload_link(
        self, token: str, repo_id: str, path: str = "/"
    ) -> str:
        resp = await self._request(
            "GET", f"/api2/repos/{repo_id}/upload-link/", token, params={"p": path}
        )
        return resp.text.strip().strip('"')

    async def get_update_link(
        self, token: str, repo_id: str, path: str = "/"
    ) -> str:
        resp = await self._request(
            "GET", f"/api2/repos/{repo_id}/update-link/", token, params={"p": path}
        )
        return resp.text.strip().strip('"')

    async def search_files(
        self, token: str, query: str, repo_id: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"q": query}
        if repo_id:
            params["repos"] = repo_id
        data = await self._get_json("/api2/search/", token, params=params)
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return data["results"]
        return data if isinstance(data, list) else []

    # -- account: link-based byte transfer -----------------------------------

    async def download_bytes(self, link: str) -> bytes:
        resp = await self._client.get(link)
        if resp.status_code >= 400:
            raise SeafileError(_error_message(resp), status_code=resp.status_code)
        return resp.content

    async def upload_bytes(
        self,
        upload_link: str,
        parent_dir: str,
        filename: str,
        content: bytes,
        replace: bool = False,
    ) -> Any:
        files = {"file": (filename, content)}
        data = {
            "parent_dir": parent_dir,
            "replace": 1 if replace else 0,
        }
        resp = await self._client.post(
            upload_link, params={"ret-json": 1}, files=files, data=data
        )
        if resp.status_code >= 400:
            raise SeafileError(_error_message(resp), status_code=resp.status_code)
        try:
            return resp.json()
        except ValueError:
            return resp.text

    async def update_bytes(
        self, update_link: str, target_file: str, content: bytes
    ) -> str:
        files = {"file": (target_file.rsplit("/", 1)[-1], content)}
        data = {"target_file": target_file}
        resp = await self._client.post(update_link, files=files, data=data)
        if resp.status_code >= 400:
            raise SeafileError(_error_message(resp), status_code=resp.status_code)
        return resp.text.strip().strip('"')

    # -- repo (library API) token --------------------------------------------

    async def repo_get_info(self, repo_token: str) -> dict[str, Any]:
        data = await self._get_json("/api/v2.1/via-repo-token/repo-info/", repo_token)
        return data if isinstance(data, dict) else {}

    async def repo_list_dir(
        self,
        repo_token: str,
        path: str = "/",
        recursive: bool = False,
        entry_type: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"path": path, "recursive": 1 if recursive else 0}
        if entry_type in ("f", "d"):
            params["type"] = entry_type
        data = await self._get_json("/api/v2.1/via-repo-token/dir/", repo_token, params=params)
        return data if isinstance(data, dict) else {}

    async def repo_mkdir(self, repo_token: str, path: str) -> Any:
        resp = await self._request(
            "POST",
            "/api/v2.1/via-repo-token/dir/",
            repo_token,
            json={"path": path, "operation": "mkdir"},
        )
        try:
            return resp.json()
        except ValueError:
            return resp.text

    async def repo_rename_dir(
        self, repo_token: str, path: str, new_name: str
    ) -> Any:
        resp = await self._request(
            "POST",
            "/api/v2.1/via-repo-token/dir/",
            repo_token,
            json={"path": path, "operation": "rename", "newname": new_name},
        )
        try:
            return resp.json()
        except ValueError:
            return resp.text

    async def repo_get_upload_link(self, repo_token: str, path: str = "/") -> str:
        resp = await self._request(
            "GET",
            "/api/v2.1/via-repo-token/upload-link/",
            repo_token,
            params={"path": path},
        )
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("upload_link"):
                return str(data["upload_link"])
        except ValueError:
            pass
        return resp.text.strip().strip('"')

    async def repo_get_download_link(self, repo_token: str, path: str) -> str:
        resp = await self._request(
            "GET",
            "/api/v2.1/via-repo-token/download-link/",
            repo_token,
            params={"path": path},
        )
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("download_link"):
                return str(data["download_link"])
        except ValueError:
            pass
        return resp.text.strip().strip('"')
