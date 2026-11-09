from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StartupPhaseOut(BaseModel):
    name: str
    duration_ms: int
    status: str = "ok"
    detail: str = ""


class StartupInfo(BaseModel):
    started_at: str
    ready_at: str | None
    total_ms: int
    ready: bool
    version: str
    phases: list[StartupPhaseOut]


class StartupHistoryItem(BaseModel):
    id: str
    app_version: str
    started_at: str
    ready_at: str | None
    total_ms: int
    ok: bool
    error: str
    phases: list[StartupPhaseOut]


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    ready: bool
    data_dir: str


class SystemInfo(BaseModel):
    app: str
    version: str
    platform: str
    python: str
    host: str
    port: int
    gpu: dict[str, Any]
    data_dir: str
    frontend_built: bool
    reserve_vram_gb: float
    reserve_ram_gb: float
    disk_free_gb: float


class MonitorSnapshot(BaseModel):
    seq: int
    ts: str
    cpu: dict[str, Any]
    gpu: dict[str, Any]
    ram: dict[str, Any]
    disk: dict[str, Any]
    models: list[dict[str, Any]] = Field(default_factory=list)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    platform: str
