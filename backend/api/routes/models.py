from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlmodel import desc, select

from backend.api.errors import AppError
from backend.config import settings
from backend.db.models import ModelMeasurement, ModelRecord, ModelVariant
from backend.db.session import session_scope
from backend.services.downloads import DownloadError, downloads
from backend.services.model_registry import registry
from backend.services.resource_manager import ResourceError, resources

router = APIRouter(prefix="/api", tags=["models"])


def _public(model: ModelRecord) -> dict[str, Any]:
    item = registry.model_public(model.id) or {}
    source = item.get("source") or {}
    item.pop("source", None)
    item["warnings"] = model.warnings
    item["capabilities"] = model.capabilities
    item["languages"] = model.languages
    return item


@router.get("/models")
def list_models(
    category: str | None = None,
    license: str | None = None,
    language: str | None = None,
    commercial: bool | None = None,
    russian: str | None = None,
    installed: bool | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    models = registry.all(category)
    result: list[dict[str, Any]] = []
    for model in models:
        if license and model.license.lower() != license.lower():
            continue
        if language and language not in (model.languages or []):
            continue
        if commercial is not None and model.commercial != commercial:
            continue
        if russian and model.russian_status != russian:
            continue
        item = _public(model)
        if installed is not None and bool(item.get("installed")) != installed:
            continue
        if q and q.lower() not in f"{model.name} {model.description}".lower():
            continue
        result.append(item)
    return result


@router.get("/models/{model_id}")
def get_model(model_id: str) -> dict[str, Any]:
    model = registry.get(model_id)
    if not model:
        raise AppError("MODEL_NOT_FOUND", "Модель не найдена.", 404)
    return _public(model)


@router.get("/models/{model_id}/compatibility")
def compatibility(model_id: str, variant_id: str | None = None, device: str | None = None) -> dict[str, Any]:
    try:
        plan = resources.plan(model_id, variant_id, device)
    except ResourceError as exc:
        raise AppError(exc.code, str(exc), 409, details=exc.details) from exc
    return plan.as_dict()


@router.get("/models/{model_id}/measurements")
def measurements(model_id: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.exec(
            select(ModelMeasurement).where(ModelMeasurement.model_id == model_id).order_by(desc(ModelMeasurement.measured_at)).limit(50)
        ).all()
    return [row.model_dump() for row in rows]


@router.post("/models/{model_id}/download")
def download_model(model_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    variant_id = payload.get("variant_id")
    variant = registry.get_variant(model_id, variant_id)
    if not variant:
        raise AppError("VARIANT_NOT_FOUND", "Вариант модели не найден.", 404)
    try:
        row = downloads.start(model_id, variant.id)
    except DownloadError as exc:
        raise AppError("DOWNLOAD_FAILED", str(exc), 400) from exc
    return row.model_dump() | {"id": row.id}


@router.get("/downloads")
def list_downloads() -> list[dict[str, Any]]:
    return [row.model_dump() for row in downloads.list()]


@router.get("/downloads/{download_id}")
def get_download(download_id: str) -> dict[str, Any]:
    row = downloads.get(download_id)
    if not row:
        raise AppError("DOWNLOAD_NOT_FOUND", "Загрузка не найдена.", 404)
    return row.model_dump()


@router.post("/downloads/{download_id}/pause")
def pause_download(download_id: str) -> dict[str, Any]:
    row = downloads.pause(download_id)
    if not row:
        raise AppError("DOWNLOAD_NOT_FOUND", "Загрузка не найдена.", 404)
    return row.model_dump()


@router.post("/downloads/{download_id}/resume")
def resume_download(download_id: str) -> dict[str, Any]:
    try:
        row = downloads.resume(download_id)
    except DownloadError as exc:
        raise AppError("DOWNLOAD_FAILED", str(exc), 400) from exc
    if not row:
        raise AppError("DOWNLOAD_NOT_FOUND", "Загрузка не найдена.", 404)
    return row.model_dump()


@router.post("/downloads/{download_id}/cancel")
def cancel_download(download_id: str) -> dict[str, Any]:
    row = downloads.cancel(download_id)
    if not row:
        raise AppError("DOWNLOAD_NOT_FOUND", "Загрузка не найдена.", 404)
    return row.model_dump()


@router.post("/models/{model_id}/verify")
def verify_model(model_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    variant = registry.get_variant(model_id, payload.get("variant_id"))
    if not variant:
        raise AppError("VARIANT_NOT_FOUND", "Вариант модели не найден.", 404)
    try:
        return downloads.verify(model_id, variant.id)
    except DownloadError as exc:
        raise AppError("VERIFY_FAILED", str(exc), 400) from exc


@router.post("/models/{model_id}/load")
def load_model(model_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    try:
        runtime = resources.ensure_loaded(model_id, payload.get("variant_id"), device=payload.get("device"), force=bool(payload.get("force")))
        return {"loaded": True, "runtime": runtime.public(), "plan": resources.plan(model_id, runtime.variant_id, payload.get("device")).as_dict()}
    except ResourceError as exc:
        raise AppError(exc.code, str(exc), 409, details=exc.details, retryable=exc.code != "MODEL_NOT_INSTALLED") from exc


@router.post("/models/{model_id}/unload")
def unload_model(model_id: str) -> dict[str, Any]:
    try:
        return resources.unload(model_id, reason="manual")
    except ResourceError as exc:
        raise AppError(exc.code, str(exc), 409) from exc


@router.delete("/models/{model_id}")
def uninstall_model(model_id: str, delete_files: bool = False) -> dict[str, Any]:
    variants = registry.variants(model_id)
    if not variants:
        raise AppError("MODEL_NOT_FOUND", "Модель не найдена.", 404)
    if resources.is_loaded(model_id):
        resources.unload(model_id, reason="delete", force=True)
    removed: list[str] = []
    if delete_files:
        for variant in variants:
            path = Path(variant.install_path) if variant.install_path else settings.data_dir / "models" / model_id
            if path.exists() and settings.data_dir / "models" in path.parents:
                shutil.rmtree(path, ignore_errors=True)
                removed.append(str(path))
            with session_scope() as session:
                row = session.get(ModelVariant, variant.id)
                if row:
                    row.install_state = "not_installed"
                    row.installed_bytes = 0
                    session.add(row)
    return {"deleted_files": removed, "model_id": model_id}


class CustomModelPayload(BaseModel):
    id: str
    name: str
    category: str = "tts"
    adapter: str
    description: str = ""
    license: str = "unknown"
    license_url: str = ""
    commercial: bool = False
    russian: str = "verify"
    languages: list[str] = Field(default_factory=lambda: ["ru"])
    capabilities: list[str] = Field(default_factory=list)
    path: str = ""
    variant: dict[str, Any] = Field(default_factory=dict)


@router.post("/models/custom")
def add_custom_model(payload: CustomModelPayload) -> dict[str, Any]:
    try:
        model = registry.add_custom(payload.model_dump())
    except ValueError as exc:
        raise AppError("CUSTOM_MODEL_INVALID", str(exc), 400) from exc
    return _public(model)
