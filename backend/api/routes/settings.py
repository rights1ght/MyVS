from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.api.errors import AppError
from backend.services.resource_manager import resources
from backend.services.settings_service import (
    create_profile,
    delete_profile,
    get_settings_values,
    list_profiles,
    update_profile,
    update_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_all() -> dict[str, Any]:
    return {
        "values": get_settings_values(),
        "profiles": [profile.model_dump() for profile in list_profiles()],
    }


@router.put("")
def put_all(payload: dict[str, Any]) -> dict[str, Any]:
    values = update_settings(payload)
    resources.refresh_settings()
    return {"values": values, "profiles": [profile.model_dump() for profile in list_profiles()]}


class ProfilePayload(BaseModel):
    name: str
    values: dict[str, Any] = Field(default_factory=dict)
    model_id: str = ""
    is_default: bool = False


@router.post("/profiles")
def create(payload: ProfilePayload) -> dict[str, Any]:
    profile = create_profile(payload.name, payload.values, payload.model_id, payload.is_default)
    return profile.model_dump()


class ProfilePatch(BaseModel):
    name: str | None = None
    values: dict[str, Any] | None = None
    is_default: bool | None = None


@router.patch("/profiles/{profile_id}")
def patch(profile_id: str, payload: ProfilePatch) -> dict[str, Any]:
    profile = update_profile(profile_id, payload.model_dump(exclude_none=True))
    if not profile:
        raise AppError("PROFILE_NOT_FOUND", "Профиль не найден.", 404)
    return profile.model_dump()


@router.delete("/profiles/{profile_id}")
def remove(profile_id: str) -> dict[str, bool]:
    if not delete_profile(profile_id):
        raise AppError("PROFILE_NOT_FOUND", "Профиль не найден.", 404)
    return {"deleted": True}
