"""WebSocket endpoint: broadcast each new DashboardTick to subscribers."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.broadcaster import broadcaster

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/ticks")
async def ticks_ws(websocket: WebSocket) -> None:
    """Stream DashboardTick JSON to the client.

    The broadcaster replays the latest tick on connect, then pushes each new
    tick as the data loop produces one. The client may send arbitrary text;
    we accept but ignore it (keeps proxies happy with two-way traffic).
    """
    await websocket.accept()
    logger.info("WS client connected: %s", websocket.client)
    try:
        async for tick in broadcaster.subscribe():
            await websocket.send_json(tick.model_dump(mode="json"))
    except WebSocketDisconnect:
        logger.info("WS client disconnected: %s", websocket.client)
    except Exception:
        logger.exception("WS handler crashed for %s", websocket.client)
        try:
            await websocket.close(code=1011)
        except Exception:  # pragma: no cover - already closed
            pass
