"""Los lotes: varios documentos que se procesan y se miran juntos."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...application.control import RunState
from ..contexto import Ctx
from ..jobs import IN_FLIGHT, JobState
from .trabajos import _discard_outputs

router = APIRouter()


@router.post("/api/batches", status_code=201)
async def create_batch(ctx: Ctx, payload: dict | None = None) -> dict[str, object]:
    name = (payload or {}).get("name") or "Lote sin nombre"
    batch = ctx.registry.create_batch(str(name))
    return {"id": batch.id, "name": batch.name, "created_at": batch.created_at}

@router.get("/api/batches")
async def list_batches(ctx: Ctx) -> dict[str, object]:
    return {"batches": [ctx.registry.batch_summary(batch) for batch in ctx.registry.list_batches()]}

@router.get("/api/batches/{batch_id}")
async def get_batch(ctx: Ctx, batch_id: str) -> dict[str, object]:
    batch = ctx.registry.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="El lote no existe")
    return ctx.registry.batch_summary(batch)

@router.patch("/api/batches/{batch_id}")
async def rename_batch(ctx: Ctx, batch_id: str, payload: dict) -> dict[str, object]:
    batch = ctx.registry.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="El lote no existe")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar vacio")
    batch.name = name
    for job_id in batch.job_ids:
        job = ctx.registry.get(job_id)
        if job is not None:
            ctx.registry.publish(job)
    return ctx.registry.batch_summary(batch)

@router.delete("/api/batches/{batch_id}")
async def delete_batch(ctx: Ctx, batch_id: str, purge: bool = False) -> dict[str, object]:
    """Clear a whole batch off the screen. Documents still running are kept."""
    batch = ctx.registry.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="El lote no existe")

    removed: list[str] = []
    for job_id in list(batch.job_ids):
        if ctx.registry.remove(job_id) is None:
            continue
        removed.append(job_id)
        if purge:
            _discard_outputs(ctx, job_id)
    return {"removed": len(removed), "ids": removed, "purged": purge}

@router.post("/api/batches/{batch_id}/{action}")
async def steer_batch(ctx: Ctx, batch_id: str, action: str) -> dict[str, object]:
    """Lo mismo para un lote entero, que es como se procesa de verdad.

    Pausar de uno en uno cincuenta documentos no es una función, es un castigo.
    """
    estados = {
        "pause": RunState.PAUSED,
        "resume": RunState.RUNNING,
        "cancel": RunState.CANCELLED,
    }
    if action not in estados:
        raise HTTPException(status_code=404, detail=f"Acción desconocida: {action}")

    batch = ctx.registry.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="El lote no existe")

    afectados: list[str] = []
    for job_id in list(batch.job_ids):
        job = ctx.registry.get(job_id)
        if job is None or job.state not in IN_FLIGHT:
            continue
        ctx.controls[job_id] = str(estados[action])
        if action == "pause" and job.state is JobState.RUNNING:
            ctx.registry.mark_paused(job)
        elif action == "resume" and job.state is JobState.PAUSED:
            ctx.registry.mark_resumed(job)
        afectados.append(job_id)
    return {"batch_id": batch_id, "action": action, "jobs": afectados}
