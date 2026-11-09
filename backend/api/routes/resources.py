from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.errors import AppError
from backend.services.resource_manager import ResourceError, resources
from backend.services.settings_service import update_settings

router = APIRouter(prefix="/api/resources", tags=["resources"])


class PlanPayload(BaseModel):
    model_id: str
    variant_id: str | None = None
    device: str | None = None


class ModePayload(BaseModel):
    mode: str


class EvictPayload(BaseModel):
    model_id: str


class UnloadAllPayload(BaseModel):
    force: bool = True


@router.get("/status")
def status() -> dict[str, Any]:
    return resources.status()


@router.get("/presets")
def presets() -> list[dict[str, Any]]:
    return resources.presets()


@router.post("/plan")
def plan(payload: PlanPayload) -> dict[str, Any]:
    try:
        return resources.plan(payload.model_id, payload.variant_id, payload.device).as_dict()
    except ResourceError as exc:
        raise AppError(exc.code, str(exc), 409, details=exc.details) from exc


@router.post("/unload-all")
def unload_all(payload: UnloadAllPayload | None = None) -> dict[str, Any]:
    force = True if payload is None else payload.force
    loaded = resources.loaded()
    results = resources.unload_all(force=force)
    return {
        "unloaded": results,
        "count": len([item for item in results if item.get("unloaded")]),
        "loaded_before": [item["model_id"] for item in loaded],
        "memory": resources.status()["memory"],
    }


@router.post("/evict")
def evict(payload: EvictPayload) -> dict[str, Any]:
    try:
        return resources.unload(payload.model_id, reason="manual")
    except ResourceError as exc:
        raise AppError(exc.code, str(exc), 409) from exc


@router.put("/mode")
def set_mode(payload: ModePayload) -> dict[str, Any]:
    try:
        resources.set_mode(payload.mode)
    except ResourceError as exc:
        raise AppError(exc.code, str(exc), 400) from exc
    # Persist, otherwise the idle watcher's refresh_settings() reverts the mode within 15 s.
    update_settings({"resource_mode": payload.mode})
    return resources.status()
