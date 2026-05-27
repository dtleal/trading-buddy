"""FastAPI app factory.

Runs alongside the dashboard tick loop in the same container. The two share
the `broadcaster` singleton: the loop publishes ticks; the WS route streams
them; REST routes serve the latest cached snapshot and on-demand history.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import brief as brief_route
from api.routes import tick as tick_route
from api.routes import vix as vix_route
from api.routes import ws as ws_route
from settings import get_settings

logger = logging.getLogger(__name__)


# Local-dev frontend origins. Production deploys would override via env.
DEFAULT_CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Also allow any private RFC1918 LAN origin so the user can open the frontend
# from a phone or another device on the same Wi-Fi (e.g. http://192.168.x.x:3000).
# Covers 10.0.0.0/8, 172.16-31.0.0/12, 192.168.0.0/16 + the .local mDNS suffix.
LAN_ORIGIN_REGEX = (
    r"^https?://"
    r"("
    r"localhost|127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"[A-Za-z0-9-]+\.local"
    r")"
    r"(:\d+)?$"
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("FastAPI starting (REST + WS)")
    yield
    logger.info("FastAPI shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="trading-buddy API",
        version="0.1.0",
        description=(
            "REST + WebSocket surface for the trading-buddy frontend. "
            "Snapshots are produced by the dashboard tick loop running in "
            "the same process."
        ),
        lifespan=_lifespan,
    )

    extras_raw = get_settings().cors_extra_origins.strip()
    extra_origins = [o.strip() for o in extras_raw.split(",") if o.strip()]
    allow_origins = [*DEFAULT_CORS_ORIGINS, *extra_origins]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_origin_regex=LAN_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(tick_route.router)
    app.include_router(vix_route.router)
    app.include_router(brief_route.router)
    app.include_router(ws_route.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
