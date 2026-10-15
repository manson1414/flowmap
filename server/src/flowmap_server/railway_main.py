"""Railway / cloud entrypoint for the FlowMap server.

Upstream ``python -m flowmap_server`` enforces a loopback-only bind
(spec section 11) because the server has no authentication. Railway
(and any PaaS) requires the process to bind ``0.0.0.0`` on the injected
``$PORT``, so this entrypoint:

1. Builds :class:`Config` through the normal ``Config.from_env`` validation,
   then overrides only ``host``/``port`` via ``msgspec.structs.replace``
   (direct struct construction is not subject to the loopback rejection).
2. Binds ``0.0.0.0`` on ``$PORT`` (Railway), falling back to
   ``FLOWMAP_PORT`` / ``8720``.
3. Serves the built React SPA from the SAME origin (``FLOWMAP_CLIENT_DIST``,
   default ``/app/client-dist``). Same-origin means the client's REST calls
   and ``/ws`` need no CORS exceptions, and the ``/ws`` origin gate can be
   satisfied with the exact public domain.
4. Sets ``FLOWMAP_WS_ALLOWED_ORIGINS`` from ``RAILWAY_PUBLIC_DOMAIN`` when
   the operator did not set it explicitly (``api/_env.py`` reads
   ``os.environ`` at call time, so setting it here before ``uvicorn.run``
   takes effect).

SECURITY NOTE: exposing this server publicly means anyone on the internet
can hit ``/api/*`` and open ``/ws`` streams — there is no auth by design.
Only deploy it behind your own access control if the data matters, and
consider ``FLOWMAP_WS_MAX_CONNECTIONS`` / a Railway private network.

Set ``FLOWMAP_RECORDING_ENABLED=0`` if you do not want parquet recordings
written to the container's ephemeral disk (they are lost on redeploy;
attach a Railway volume + ``FLOWMAP_DATA_DIR`` to keep them).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import msgspec
import uvicorn
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response

from flowmap_server.__main__ import configure_logging
from flowmap_server.api.app import create_app
from flowmap_server.config import Config

log = logging.getLogger("flowmap_server.railway_main")


class SPAStaticFiles(StaticFiles):
    """Static files with SPA fallback.

    Real files (``/assets/*.js``, favicon, ...) are served as-is. Any other
    path that is not ``/api/*`` or ``/ws`` falls back to ``index.html`` so
    client-side routing keeps working. API/WS 404s are preserved untouched.
    """

    async def get_response(self, path: str, scope) -> Response:  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Modern Starlette raises 404 instead of returning a 404 response.
            if exc.status_code == 404 and not (
                path == "api" or path.startswith("api/") or path == "ws"
            ):
                return await super().get_response("index.html", scope)
            raise


def _client_dist() -> Path | None:
    override = os.environ.get("FLOWMAP_CLIENT_DIST")
    candidates = [Path(override)] if override else []
    # Docker image layout first, then repo-relative layout for local runs.
    candidates += [
        Path("/app/client-dist"),
        Path(__file__).resolve().parents[4] / "client" / "dist",
    ]
    for cand in candidates:
        if (cand / "index.html").is_file():
            return cand
    return None


def main() -> None:
    # 1. Normal env validation (ranges, types), with a loopback placeholder
    #    host so from_env() does not reject us; we override right after.
    env = dict(os.environ)
    env.setdefault("FLOWMAP_HOST", "127.0.0.1")
    cfg = Config.from_env(env)

    port = int(os.environ.get("PORT") or env.get("FLOWMAP_PORT") or 8720)
    cfg = msgspec.structs.replace(cfg, host="0.0.0.0", port=port)

    # 2. WS origin gate: exact public domain when Railway tells us what it is.
    if not os.environ.get("FLOWMAP_WS_ALLOWED_ORIGINS"):
        domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        if domain:
            os.environ["FLOWMAP_WS_ALLOWED_ORIGINS"] = f"https://{domain}"
            log.info("FLOWMAP_WS_ALLOWED_ORIGINS=https://%s (from RAILWAY_PUBLIC_DOMAIN)", domain)

    app = create_app(cfg)

    # 3. Same-origin SPA.
    dist = _client_dist()
    if dist is None:
        log.warning(
            "no built client found (FLOWMAP_CLIENT_DIST=%r); serving API only",
            os.environ.get("FLOWMAP_CLIENT_DIST"),
        )
    else:
        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="spa")
        log.info("serving SPA from %s", dist)

    log_level = os.environ.get("FLOWMAP_LOG_LEVEL", "info")
    configure_logging(log_level, os.environ.get("FLOWMAP_LOG_FILE") or None)
    log.warning(
        "binding 0.0.0.0:%d — the FlowMap server has NO auth; "
        "do not expose this publicly without your own access control",
        port,
    )
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level=log_level)


if __name__ == "__main__":
    main()
