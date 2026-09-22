# seafile-mcp

Model Context Protocol server for [Seafile](https://www.seafile.com/) file storage.
Multi-user, with two token-based auth modes and full file/folder/library management.

Built with [FastMCP](https://github.com/jlowin/fastmcp) (`mcp<2`). Inspired by
[`setugk/seafile-mcp`](https://github.com/setugk/seafile-mcp) (tool coverage),
[`virtUOS/seafile-mcp`](https://github.com/virtUOS/seafile-mcp) (multi-user +
safety modes) and [`5p00kyy/seafile-mcp`](https://github.com/5p00kyy/seafile-mcp)
(dual account/repo-token env config).

## Auth: register once, then pass only `user_id` (tokens only — never passwords)

No tokens are fixed in `.env`. Each user registers once; the server saves the
tokens in a vault file (`SEAFILE_VAULT_PATH`, default `~/.seafile-mcp/vault.json`,
mode `0600`). All later calls pass only `user_id`:

1. `register_user(user_id="alice", account_token="<token>")` — full scope, or
   `register_user(user_id="bob", repo_tokens={"Docs": "<token>"})` — scoped.
2. Use any tool with `user_id="alice"` — no tokens per call.
3. Maintain with `update_account_token`, `add_library_tokens`,
   `remove_library_tokens`, `remove_account_token`, `revoke_user`;
   inspect with `my_credentials` (tokens always masked, never revealed).

Resolution order per call: explicit `account_token`/`repo_token` params →
vault record for `user_id` → env defaults (`SEAFILE_ACCOUNT_TOKEN` /
`SEAFILE_REPO_TOKENS_JSON`, single-user fallback only).

| Credential in vault | Scope |
|---|---|
| **Account token** | Full: all libraries, all tools |
| **Library API tokens** | Only those libraries; browse/read/upload/rename-folders. Library management, move/copy/delete and search return a clear "requires an account token" error (Seafile exposes no such endpoints for repo tokens) |

> **Security note:** `user_id` is self-asserted by the caller — a namespace, not
> an identity proof. Anyone reaching the endpoint could pass another user's id
> and use their stored tokens. Protect multi-user HTTP deployments per user
> (reverse-proxy auth, VPN/Tailscale). For local single-user use, stdio +
> optional env defaults avoid the vault entirely.

### Getting an account token (one-time, never expires)

There is **no Web UI page** for account tokens. Mint it with your username and
password (add `-H 'X-SEAFILE-OTP: <6-digit>'` if you use 2FA):

```bash
curl -d "username=YOUR_EMAIL&password=YOUR_PASSWORD" \
  https://YOUR_SEAFILE_SERVER/api2/auth-token/
# {"token": "24fd3c026886e3121b2ca630805ed425c272cb96"}
```

The token is permanent — re-mint only after a password change (which invalidates
it), then save the new one with `update_account_token`. The `get_auth_help`
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

## Tools (29)

User vault (all modes): `register_user`, `update_account_token`,
`add_library_tokens`, `remove_library_tokens`, `remove_account_token`,
`revoke_user`, `my_credentials` · Help: `get_auth_help`, `resolve_library` ·
Libraries (account only):
`list_libraries`, `get_library_info`, `create_library`, `rename_library`,
`delete_library` (full mode) · Files: `list_directory`, `get_file_detail`
(account only), `read_file`, `get_download_link`, `search_files` (account only),
`create_directory` (parents auto-created), `upload_file`, `update_file`,
`rename_item`, `move_item` (account only), `copy_item` (account only),
`delete_item` (full mode, account only) · Share links (account only):
`create_share_link`, `list_share_links`, `delete_share_link` (full mode).

Every file/library tool accepts `user_id` (vault), `repo_id` **or**
`library_name`, plus optional `account_token` / `repo_token` overrides
(explicit params win over the vault). `read_file` returns text (truncated
with notice) or, for binaries, metadata + download link. `upload_file` /
`update_file` take text or base64 (`is_base64: true`).

## Tests

```bash
.venv/bin/python -m pytest -q   # 40 tests, mocked HTTP (no live server needed)
```

## Roadmap

- PDF/Office text extraction (currently binaries return metadata + link)
- Optional endpoint bearer-auth for the HTTP transport
- Background search index for repo-token libraries (cf. `dm7500/seafile-vault-mcp`)

## License

MIT
