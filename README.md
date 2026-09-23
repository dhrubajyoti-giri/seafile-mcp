# seafile-mcp

Model Context Protocol server for [Seafile](https://www.seafile.com/) file storage.
Multi-user, with two token-based auth modes and full file/folder/library management.

Built with [FastMCP](https://github.com/jlowin/fastmcp) (`mcp<2`). Inspired by
[`setugk/seafile-mcp`](https://github.com/setugk/seafile-mcp) (tool coverage),
[`virtUOS/seafile-mcp`](https://github.com/virtUOS/seafile-mcp) (multi-user +
safety modes) and [`5p00kyy/seafile-mcp`](https://github.com/5p00kyy/seafile-mcp)
(dual account/repo-token env config).

## Auth: log in once, then pass only `session_token`

No tokens are fixed in `.env`. Each user authenticates once; the server keeps
the Seafile credentials in a session store (`SEAFILE_SESSION_PATH`, default
`~/.seafile-mcp/sessions.json`, mode `0600`) keyed by **SHA-256 hash** of an
opaque bearer token. All later calls present only that token:

1. `auth_login(user_id="alice", password="...")` — validates against Seafile
   and issues a **full-scope** session token (password used once, never
   stored; add `otp="123456"` with 2FA). Or `auth_register_library(
   library_token="<token>", library_name="Docs")` — validates the library
   token and issues a **scoped** session token.
2. Use any tool with `session_token="<token>"` — no Seafile tokens per call.
3. Maintain with `auth_reauth` (after a password change), `auth_rotate`,
   `auth_revoke`, `auth_add_library`, `auth_remove_library`;
   inspect with `auth_status` (nothing secret is revealed).

Resolution order per call: explicit `account_token`/`repo_token` params →
session record for `session_token` → env defaults (`SEAFILE_ACCOUNT_TOKEN` /
`SEAFILE_REPO_TOKENS_JSON`, single-user fallback only).

| Session scope | Allowed |
|---|---|
| **Full** (account login) | All libraries, all tools |
| **Scoped** (library tokens) | Only those libraries; browse/read/upload/rename-folders. Library management, move/copy/delete and search return a clear error (Seafile exposes no such endpoints for repo tokens) |

> **Security note:** a session token is a bearer secret — whoever holds it may
> use the stored Seafile credentials, and it travels with every call, so
> always use TLS and protect multi-user HTTP deployments (reverse-proxy auth,
> VPN/Tailscale). The store file holds Seafile tokens plus only hashes of
> session tokens; rotate/revoke sessions any time without touching Seafile.

### Getting an account token (one-time, never expires)

Normally you never do this by hand — `auth_login` exchanges your password
for a Seafile token and stores it in the session. For reference, there is
**no Web UI page** for account tokens; the manual equivalent is (add
`-H 'X-SEAFILE-OTP: <6-digit>'` with 2FA):

```bash
curl -d "username=YOUR_EMAIL&password=YOUR_PASSWORD" \
  https://YOUR_SEAFILE_SERVER/api2/auth-token/
# {"token": "24fd3c026886e3121b2ca630805ed425c272cb96"}
```

The token is permanent — after a password change it is invalidated, so run
`auth_reauth` to refresh the session. The `get_auth_help`
tool repeats these instructions for agents.

### Getting a library API token (scoped, `r` or `rw`, valid until deleted)

Seafile Web UI: library menu (`⋯`) → **Advanced → API Token** → create with
read or read-write permission. Or via API with an account token:

```bash
curl -H "Authorization: Token <account-token>" -H 'Content-Type: application/json' \
  -d '{"app_name": "my-assistant", "permission": "rw"}' \
  https://YOUR_SEAFILE_SERVER/api/v2.1/repos/<repo-id>/repo-api-tokens/
```

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # set SEAFILE_SERVER_URL; tokens are registered at runtime
```

Requires `SEAFILE_SERVER_URL` (no trailing slash). Auth header scheme defaults to
`auto` (`Token`, falling back to `Bearer` on 401 — covers Seafile < 11 and ≥ 11).

Transfer guardrails (all optional): `SEAFILE_TIMEOUT` seconds (default 60),
`SEAFILE_MAX_READ_SIZE` bytes (default 10485760 — `read_file` refuses bigger
downloads with a clear 413 error), `SEAFILE_MAX_WRITE_SIZE` bytes (default
52428800 — uploads/updates over this are refused before sending).

## Run

```bash
# Local single-user (Claude Desktop / Code / OpenCode)
seafile-mcp --transport stdio

# Multi-user HTTP
seafile-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Put the HTTP endpoint behind a reverse proxy / VPN for remote use — it has no
built-in endpoint auth; Seafile tokens travel per tool call.

### Client config examples

stdio (`claude_desktop_config.json` / `.mcp.json`):

```json
{ "mcpServers": { "seafile": {
  "command": "/abs/path/seafile-mcp/.venv/bin/seafile-mcp",
  "args": ["--transport", "stdio"],
  "env": { "SEAFILE_SERVER_URL": "https://seafile.example.com",
            "SEAFILE_ACCOUNT_TOKEN": "<token>" }
} } }
```

Streamable HTTP + Docker: `cp .env.example .env`, set values, `docker compose up`.

## Safety modes (`SEAFILE_MCP_MODE`)

- `read_only` — mutating tools are not registered at all.

- `safe_write` (default) — create/rename/move/copy/upload allowed; deletes hidden.

- `full` — also registers `delete_library` (permanent!) and `delete_item` (to trash).

Overwrites create new versions in Seafile file history; deletes go to library
trash. The trash-purge endpoint is deliberately not exposed.

## Tools (30)

Session auth (all modes): `auth_login`, `auth_register_library`,
`auth_reauth`, `auth_rotate`, `auth_revoke`, `auth_add_library`,
`auth_remove_library`, `auth_status` · Help: `get_auth_help`,
`resolve_library` ·
Libraries (account only):
`list_libraries`, `get_library_info`, `create_library`, `rename_library`,
`delete_library` (full mode) · Files: `list_directory`, `get_file_detail`
(account only), `read_file`, `get_download_link`, `search_files` (account only),
`create_directory` (parents auto-created), `upload_file`, `update_file`,
`rename_item`, `move_item` (account only), `copy_item` (account only),
`delete_item` (full mode, account only) · Share links (account only):
`create_share_link`, `list_share_links`, `delete_share_link` (full mode).

Every file/library tool accepts `session_token`, `repo_id` **or**
`library_name`, plus optional `account_token` / `repo_token` overrides
(explicit params win over the session). `read_file` returns text (truncated
with notice) or, for binaries, metadata + download link. `upload_file` /
`update_file` take text or base64 (`is_base64: true`).

## Tests

```bash
.venv/bin/python -m pytest -q   # 72 tests, mocked HTTP (no live server needed)
```

## Roadmap

- PDF/Office text extraction (currently binaries return metadata + link)

- Optional endpoint bearer-auth for the HTTP transport

- Background search index for repo-token libraries (cf. `dm7500/seafile-vault-mcp`)

## License

MIT

