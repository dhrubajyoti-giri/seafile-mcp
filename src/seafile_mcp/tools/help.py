"""Auth help tool — tells users (and agents) how to obtain Seafile tokens.

Verified against official Seafile API docs (seafile-api.readme.io):
  - Account tokens have NO Web UI path. They are minted ONLY via
    POST /api2/auth-token/ with username + password.
  - Library (repo) API tokens ARE available in the Web UI:
    library menu -> Advanced -> API Token.
"""

from __future__ import annotations

AUTH_HELP = """# Seafile credentials for this MCP server (tokens only — never passwords)

Register ONCE with register_user, then pass only user_id on later calls:
- register_user(user_id="you", account_token="<token>") → full scope.
- register_user(user_id="you", repo_tokens={"LibName": "<token>"}) → scoped.
- Maintain with update_account_token / add_library_tokens /
  remove_library_tokens / remove_account_token / revoke_user.
- Explicit per-call tokens always override the saved record.

## Mode A — Account token (FULL scope: all libraries, all tools)
Mint it ONCE with curl (replace values). It never expires; re-mint only
after a password change:

curl -d "username=YOUR_EMAIL&password=YOUR_PASSWORD" \\
  https://YOUR_SEAFILE_SERVER/api2/auth-token/

With 2FA enabled, add: -H 'X-SEAFILE-OTP: <6-digit-code>'

Response: {"token": "40-char-token"}. Use it as `account_token` on any tool,
or set SEAFILE_ACCOUNT_TOKEN on the server as the default.

Note: there is NO Web UI page for account tokens — the API call above is
the only way (unless the server admin enabled profile-page tokens).

## Mode B — Library API tokens (SCOPED: only those libraries)
In the Seafile Web UI: library menu (⋯) -> Advanced -> API Token -> create
with `r` (read) or `rw` (read-write). Valid until deleted.

Use as `repo_token` (+ `repo_id` or `library_name`) on file tools, or map
names in SEAFILE_REPO_TOKENS_JSON. Library management, move/copy/delete
and search are NOT available in this mode — Seafile exposes no such
endpoints for repo tokens; those tools return a clear error telling you
to re-run with an account token.
"""


async def get_auth_help() -> str:
    """Explain how to obtain Seafile account and library API tokens."""
    return AUTH_HELP
