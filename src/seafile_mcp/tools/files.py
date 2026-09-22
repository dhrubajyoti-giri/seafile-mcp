"""File and folder tools. Dual path: account token (full ops) or repo token (scoped)."""

from __future__ import annotations

import base64

from ..config import Config
from ..seafile_client import SeafileClient
from ..sessions import SessionStore
from .common import account_only, resolve, resolve_repo_id

TEXT_PREVIEW_LIMIT = 200_000


def _require_path(path: str, what: str = "path") -> str:
    cleaned = (path or "").strip()
    if not cleaned:
        raise ValueError(f"{what} must not be empty.")
    return cleaned if cleaned.startswith("/") else "/" + cleaned


def _parent_dir(path: str) -> str:
    path = path.rstrip("/") or "/"
    if "/" not in path[1:]:
        return "/"
    return path.rsplit("/", 1)[0] or "/"


def _basename(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


async def list_directory(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str = "/",
    recursive: bool = False,
    entry_type: str | None = None,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> dict | list:
    """List a directory. Works with account or repo token."""
    path = _require_path(path)
    auth = await resolve(
        config, client, store,
        account_token=account_token, repo_token=repo_token,
        repo_id=repo_id, library_name=library_name, session_token=session_token,
    )
    if auth.kind == "repo":
        data = await client.repo_list_dir(
            auth.token, path=path, recursive=recursive, entry_type=entry_type
        )
        entries = data.get("dirent_list", [])
        if not isinstance(entries, list):
            entries = []
        if entry_type == "f":
            entries = [e for e in entries if e.get("type") == "file"]
        elif entry_type == "d":
            entries = [e for e in entries if e.get("type") == "dir"]
        return {
            "path": path,
            "entries": entries,
            "permission": data.get("user_perm"),
        }
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    entries = await client.list_dir(auth.token, rid, path=path, recursive=recursive)
    if entry_type == "f":
        entries = [e for e in entries if e.get("type") == "file"]
    elif entry_type == "d":
        entries = [e for e in entries if e.get("type") == "dir"]
    return {"repo_id": rid, "path": path, "entries": entries}


async def get_file_detail(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Get file metadata. Repo-token callers: use list_directory (Seafile has
    no via-repo-token file-detail endpoint)."""
    path = _require_path(path)
    auth = await resolve(
        config, client, store,
        account_token=account_token, repo_token=repo_token,
        repo_id=repo_id, library_name=library_name, session_token=session_token,
    )
    account_only(auth, "get_file_detail")
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    return await client.get_file_detail(auth.token, rid, path)


async def get_download_link(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Get a one-time download URL for a file."""
    path = _require_path(path)
    auth = await resolve(
        config, client, store,
        account_token=account_token, repo_token=repo_token,
        repo_id=repo_id, library_name=library_name, session_token=session_token,
    )
    if auth.kind == "repo":
        link = await client.repo_get_download_link(auth.token, path)
        return {"path": path, "download_link": link}
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    link = await client.get_download_link(auth.token, rid, path)
    return {"repo_id": rid, "path": path, "download_link": link}


async def read_file(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    max_chars: int = 50_000,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Download and read a file as text. Binary files return metadata +
    a download link instead of content."""
    path = _require_path(path)
    max_chars = min(max_chars, TEXT_PREVIEW_LIMIT)
    link_info = await get_download_link(
        config, client, store, path,
        repo_id=repo_id, library_name=library_name,
        account_token=account_token, repo_token=repo_token, session_token=session_token,
    )
    raw = await client.download_bytes(link_info["download_link"])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "path": path,
            "is_binary": True,
            "size": len(raw),
            "notice": (
                "Binary file: content is not text and was not returned. "
                "Use get_download_link to fetch the bytes."
            ),
            "download_link": link_info["download_link"],
        }
    truncated = len(text) > max_chars
    return {
        "path": path,
        "is_binary": False,
        "size": len(raw),
        "truncated": truncated,
        "content": text[:max_chars],
        "notice": f"Content truncated to {max_chars} chars." if truncated else None,
    }


async def search_files(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    query: str,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> list[dict]:
    """Full-text/filename search (account token only; requires search
    enabled on the Seafile server)."""
    if not (query or "").strip():
        raise ValueError("query must not be empty.")
    auth = await resolve(
        config, client, store,
        account_token=account_token, repo_token=repo_token,
        repo_id=repo_id, library_name=library_name, session_token=session_token,
    )
    account_only(auth, "search_files")
    rid = None
    if repo_id or library_name:
        rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    return await client.search_files(auth.token, query, repo_id=rid)


async def create_directory(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Create a folder. Missing parents are created automatically."""
    path = _require_path(path)
    if path == "/":
        raise ValueError("path must not be the library root (it already exists).")
    auth = await resolve(
        config, client, store,
        account_token=account_token, repo_token=repo_token,
        repo_id=repo_id, library_name=library_name, session_token=session_token,
    )
    if auth.kind == "repo":
        result = await client.repo_mkdir(auth.token, path)
        return {"path": path, "created": True, "result": result}
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    # p is the NEW directory path; create_parents builds missing levels.
    result = await client.dir_operation(
        auth.token, rid, path, "mkdir", {"create_parents": "true"}
    )
    return {"repo_id": rid, "path": path, "created": True, "result": result}


async def upload_file(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    content: str,
    is_base64: bool = False,
    replace: bool = False,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Upload (create) a file. content is text unless is_base64=True."""
    path = _require_path(path)
    raw = base64.b64decode(content) if is_base64 else content.encode("utf-8")
    auth = await resolve(
        config, client, store,
        account_token=account_token, repo_token=repo_token,
        repo_id=repo_id, library_name=library_name, session_token=session_token,
    )
    parent = _parent_dir(path)
    name = _basename(path)
    if auth.kind == "repo":
        link = await client.repo_get_upload_link(auth.token, parent)
        result = await client.upload_bytes(link, parent, name, raw, replace=replace)
        return {"path": path, "uploaded": True, "result": result}
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    link = await client.get_upload_link(auth.token, rid, parent)
    result = await client.upload_bytes(link, parent, name, raw, replace=replace)
    return {"repo_id": rid, "path": path, "uploaded": True, "result": result}


async def update_file(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    content: str,
    is_base64: bool = False,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Overwrite an existing file (creates a new version in file history)."""
    path = _require_path(path)
    raw = base64.b64decode(content) if is_base64 else content.encode("utf-8")
    auth = await resolve(
        config, client, store,
        account_token=account_token, repo_token=repo_token,
        repo_id=repo_id, library_name=library_name, session_token=session_token,
    )
    if auth.kind == "repo":
        # No via-repo-token update endpoint — re-upload with replace.
        parent = _parent_dir(path)
        name = _basename(path)
        link = await client.repo_get_upload_link(auth.token, parent)
        result = await client.upload_bytes(link, parent, name, raw, replace=True)
        return {"path": path, "updated": True, "result": result}
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    link = await client.get_update_link(auth.token, rid, _parent_dir(path))
    file_id = await client.update_bytes(link, path, raw)
    return {"repo_id": rid, "path": path, "updated": True, "file_id": file_id}


async def rename_item(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    new_name: str,
    is_dir: bool = False,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    repo_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Rename a file or folder. Repo tokens support folders only."""
    path = _require_path(path)
    if not (new_name or "").strip():
        raise ValueError("new_name must not be empty.")
    auth = await resolve(
        config, client, store,
        account_token=account_token, repo_token=repo_token,
        repo_id=repo_id, library_name=library_name, session_token=session_token,
    )
    if auth.kind == "repo":
        if not is_dir:
            account_only(auth, "rename file")
        result = await client.repo_rename_dir(auth.token, path, new_name)
        return {"path": path, "new_name": new_name, "renamed": True, "result": result}
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    if is_dir:
        result = await client.dir_operation(
            auth.token, rid, path, "rename", {"newname": new_name}
        )
    else:
        result = await client.file_operation(
            auth.token, rid, path, "rename", {"newname": new_name}
        )
    return {"repo_id": rid, "path": path, "new_name": new_name, "renamed": True, "result": result}


async def move_item(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    dst_dir: str,
    dst_repo_id: str | None = None,
    is_dir: bool = False,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Move a file or folder (account token only)."""
    path = _require_path(path)
    dst_dir = _require_path(dst_dir, "dst_dir")
    auth = await resolve(
        config, client, store,
        account_token=account_token, session_token=session_token,
        repo_id=repo_id, library_name=library_name,
    )
    account_only(auth, "move_item")
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    extra: dict = {"dst_repo": dst_repo_id or rid, "dst_dir": dst_dir}
    if is_dir:
        result = await client.dir_operation(auth.token, rid, path, "move", extra)
    else:
        result = await client.file_operation(auth.token, rid, path, "move", extra)
    return {"repo_id": rid, "path": path, "dst_dir": dst_dir, "moved": True, "result": result}


async def copy_item(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    dst_dir: str,
    dst_repo_id: str | None = None,
    is_dir: bool = False,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Copy a file or folder (account token only)."""
    path = _require_path(path)
    dst_dir = _require_path(dst_dir, "dst_dir")
    auth = await resolve(
        config, client, store,
        account_token=account_token, session_token=session_token,
        repo_id=repo_id, library_name=library_name,
    )
    account_only(auth, "copy_item")
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    extra: dict = {"dst_repo": dst_repo_id or rid, "dst_dir": dst_dir}
    if is_dir:
        result = await client.dir_operation(auth.token, rid, path, "copy", extra)
    else:
        result = await client.file_operation(auth.token, rid, path, "copy", extra)
    return {"repo_id": rid, "path": path, "dst_dir": dst_dir, "copied": True, "result": result}


async def delete_item(
    config: Config,
    client: SeafileClient,
    store: SessionStore | None,
    path: str,
    is_dir: bool = False,
    repo_id: str | None = None,
    library_name: str | None = None,
    account_token: str | None = None,
    session_token: str | None = None,
) -> dict:
    """Delete a file or folder (goes to library trash; account token only).
    Only registered in full mode."""
    path = _require_path(path)
    auth = await resolve(
        config, client, store,
        account_token=account_token, session_token=session_token,
        repo_id=repo_id, library_name=library_name,
    )
    account_only(auth, "delete_item")
    rid = await resolve_repo_id(client, auth, repo_id=repo_id, library_name=library_name)
    if is_dir:
        await client.delete_dir(auth.token, rid, path)
    else:
        await client.delete_file(auth.token, rid, path)
    return {"repo_id": rid, "path": path, "deleted": True}
