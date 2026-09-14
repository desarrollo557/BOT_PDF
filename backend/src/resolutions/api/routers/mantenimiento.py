"""La limpieza de lo que ya nadie va a bajar."""

from __future__ import annotations

from fastapi import APIRouter

from ..contexto import Ctx

router = APIRouter()


@router.get("/api/cache")
async def cache_status(ctx: Ctx) -> dict[str, object]:
    return {
        "idle": ctx.registry.pending == 0,
        "would_sweep": ctx.janitor.should_sweep(),
        "last_sweep": ctx.janitor.last.as_dict() if ctx.janitor.last else None,
        "interval_seconds": ctx.settings.sweep_seconds,
    }

@router.post("/api/cache/sweep")
async def sweep_cache(ctx: Ctx) -> dict[str, object]:
    """Run the idle sweep now, if the queue allows it."""
    result = await ctx.janitor.sweep_if_idle(force=True)
    if result is None:
        return {"swept": False, "reason": "hay documentos en proceso"}
    return {"swept": True, **result.as_dict()}
