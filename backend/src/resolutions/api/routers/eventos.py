"""El progreso en vivo, por Server-Sent Events."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..contexto import Ctx

router = APIRouter()


HEARTBEAT_SECONDS = 15.0

@router.get("/api/events")
async def events(ctx: Ctx) -> StreamingResponse:
    queue = ctx.registry.subscribe()

    async def stream():
        try:
            # Replay current state on connect, so a tab that reconnects after a
            # dropped socket resynchronises without any extra request.
            for job in ctx.registry.list():
                yield _sse(job.as_dict())
            for run in ctx.folders.list():
                yield _sse(run.as_dict())
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(payload)
        finally:
            ctx.registry.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
