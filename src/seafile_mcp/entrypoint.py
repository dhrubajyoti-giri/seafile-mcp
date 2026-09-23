#!/usr/bin/env python3
"""Container-safe entrypoint with visible startup / errors."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
try:
    from seafile_mcp.config import Config
    from seafile_mcp.server import create_server, run_transport
    cfg = Config.from_env()
    print(f"seafile-mcp READY mode={cfg.mode} transport={cfg.transport} store={cfg.session_path}", flush=True)
    import asyncio
    mcp, client, store = create_server(cfg)
    asyncio.run(run_transport(mcp, cfg.transport or "stdio", host=cfg.host, port=cfg.port))
except SystemExit:
    raise
except Exception as exc:
    import traceback
    traceback.print_exc(file=sys.stderr)
    print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)
