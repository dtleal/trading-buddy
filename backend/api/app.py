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

from api.routes import tick as tick_route
from api.routes import vix as vix_route
from api.routes import ws as ws_route

logger = logging.getLogger(__name__)


# Local-dev frontend origins. Production deploys would override via env.
DEFAULT_CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEFAULT_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(tick_route.router)
    app.include_router(vix_route.router)
    app.include_router(ws_route.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
