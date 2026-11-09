from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import select

from backend.config import settings
from backend.db.models import AppSetting, SettingsProfile
from backend.db.session import session_scope

DEFAULTS: dict[str, Any] = {
    "resource_mode": "parallel",
    "conflict_policy": "ask",
    "reserve_vram_gb": 0.8,
    "reserve_ram_gb": 3.0,
    "idle_unload_seconds": 600,
    "theme": "dark",
    "preload_models": [],
    "default_device": "gpu",
    "default_precision": "int8",
    "stt_beam_size": 5,
    "stt_temperature": 0.0,
    "stt_vad": True,
    "stt_batch_size": 1,
    "tts_speed": 1.0,
    "tts_pitch": 0.0,
    "tts_volume": 1.0,
    "vram_limit_gb": 0.0,
    "auto_restore_exclusive": True,
}

_KEY_VALUE = {
    "resource_mode",
    "conflict_policy",
    "reserve_vram_gb",
    "reserve_ram_gb",
    "idle_unload_seconds",
}


def get_settings_values() -> dict[str, Any]:
    values = dict(DEFAULTS)
    with session_scope() as session:
        for row in session.exec(select(AppSetting)).all():
            raw = row.value or {}
            if isinstance(raw, dict) and "value" in raw:
                values[row.key] = raw["value"]
            else:
                values[row.key] = raw
    return values


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    values = get_settings_values()
    for key, value in patch.items():
        if key not in DEFAULTS:
            continue
        values[key] = value
        with session_scope() as session:
            row = session.get(AppSetting, key)
            if not row:
                row = AppSetting(key=key)
            row.value = {"value": value}
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
    return values


def list_profiles() -> list[SettingsProfile]:
    with session_scope() as session:
        return list(session.exec(select(SettingsProfile).order_by(SettingsProfile.created_at)).all())


def create_profile(name: str, values: dict[str, Any], model_id: str = "", is_default: bool = False) -> SettingsProfile:
    with session_scope() as session:
        profile = SettingsProfile(name=name, scope="model" if model_id else "global", model_id=model_id, values=values, is_default=is_default)
        if is_default and model_id:
            for existing in session.exec(select(SettingsProfile).where(SettingsProfile.model_id == model_id)).all():
                existing.is_default = False
                session.add(existing)
        session.add(profile)
        session.flush()
        session.refresh(profile)
        return profile


def update_profile(profile_id: str, patch: dict[str, Any]) -> SettingsProfile | None:
    with session_scope() as session:
        profile = session.get(SettingsProfile, profile_id)
        if not profile:
            return None
        if "name" in patch:
            profile.name = str(patch["name"])
        if "values" in patch:
            profile.values = dict(patch["values"] or {})
        if "is_default" in patch:
            profile.is_default = bool(patch["is_default"])
            if profile.is_default and profile.model_id:
                for existing in session.exec(select(SettingsProfile).where(SettingsProfile.model_id == profile.model_id)).all():
                    if existing.id != profile.id:
                        existing.is_default = False
                        session.add(existing)
        profile.updated_at = datetime.now(timezone.utc)
        session.add(profile)
        return profile


def delete_profile(profile_id: str) -> bool:
    with session_scope() as session:
        profile = session.get(SettingsProfile, profile_id)
        if not profile:
            return False
        session.delete(profile)
        return True
