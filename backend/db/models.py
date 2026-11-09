from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import JSON, Column, Index, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    description: str = ""
    color: str = "#f5b942"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ModelRecord(SQLModel, table=True):
    __tablename__ = "models"

    id: str = Field(primary_key=True)
    name: str
    category: str = Field(index=True)  # stt | tts | clone
    adapter: str
    description: str = ""
    license: str = "unknown"
    license_url: str = ""
    commercial: bool = False
    russian_status: str = "verify"  # confirmed | verify | none
    languages: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    capabilities: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    warnings: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    requires_exclusive: bool = False
    requires_consent: bool = False
    watermark: bool = False
    is_custom: bool = False
    enabled: bool = True
    source: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ModelVariant(SQLModel, table=True):
    __tablename__ = "model_variants"

    id: str = Field(primary_key=True)
    model_id: str = Field(foreign_key="models.id", index=True)
    label: str = ""
    device: str = "gpu"  # gpu | cpu
    precision: str = "fp16"
    vram_estimate_gb: float = 0.0
    ram_estimate_gb: float = 0.0
    disk_gb: float = 0.0
    source: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    install_state: str = "not_installed"  # not_installed|downloading|paused|verifying|installed|error
    install_path: str = ""
    revision: str = ""
    sha256: str = ""
    installed_bytes: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ModelMeasurement(SQLModel, table=True):
    __tablename__ = "model_measurements"

    id: str = Field(default_factory=new_id, primary_key=True)
    model_id: str = Field(foreign_key="models.id", index=True)
    variant_id: str = Field(foreign_key="model_variants.id", index=True)
    device: str = "gpu"
    precision: str = "fp16"
    context_vram_gb: float = 0.0
    steady_vram_gb: float = 0.0
    peak_vram_gb: float = 0.0
    ram_gb: float = 0.0
    load_ms: int = 0
    warmup_ms: int = 0
    runtime_signature: str = ""
    sample_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    measured_at: datetime = Field(default_factory=utcnow, index=True)


class ModelRuntimeEvent(SQLModel, table=True):
    __tablename__ = "model_runtime_events"

    id: str = Field(default_factory=new_id, primary_key=True)
    model_id: str = Field(index=True)
    variant_id: str = ""
    action: str  # load | unload | kill | measure
    device: str = ""
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    ok: bool = True
    vram_before_mb: float = 0.0
    vram_after_mb: float = 0.0
    pid: Optional[int] = None
    error: str = ""


class Download(SQLModel, table=True):
    __tablename__ = "downloads"

    id: str = Field(default_factory=new_id, primary_key=True)
    model_id: str = Field(index=True)
    variant_id: str = Field(index=True)
    status: str = "queued"  # queued|downloading|paused|verifying|completed|error
    bytes_total: int = 0
    bytes_done: int = 0
    speed_bps: float = 0.0
    resumable: bool = True
    dest_path: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Voice(SQLModel, table=True):
    __tablename__ = "voices"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    kind: str = "builtin"  # builtin | cloned | designed
    model_id: Optional[str] = Field(default=None, foreign_key="models.id", index=True)
    engine_voice_id: str = ""
    language: str = "ru"
    gender: str = ""
    description: str = ""
    reference_path: str = ""
    reference_sha256: str = ""
    duration_sec: float = 0.0
    quality_score: Optional[float] = None
    quality_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    consent_accepted: bool = False
    consent_at: Optional[datetime] = None
    license: str = ""
    commercial: bool = False
    preview_path: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class VoiceCache(SQLModel, table=True):
    __tablename__ = "voice_cache"

    id: str = Field(default_factory=new_id, primary_key=True)
    voice_id: str = Field(foreign_key="voices.id", index=True)
    model_id: str = Field(index=True)
    variant_id: str = ""
    kind: str = ""
    path: str = ""
    sha256: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime = Field(default_factory=utcnow)


class TaskRecord(SQLModel, table=True):
    __tablename__ = "tasks"

    id: str = Field(default_factory=new_id, primary_key=True)
    project_id: Optional[str] = Field(default=None, foreign_key="projects.id", index=True)
    type: str = Field(index=True)  # stt | tts | clone | preview | model_load
    status: str = Field(default="queued", index=True)
    priority: int = 10
    model_id: str = Field(default="", index=True)
    variant_id: str = ""
    voice_id: Optional[str] = Field(default=None, index=True)
    device: str = "gpu"
    precision: str = "fp16"
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    input_path: str = ""
    output_paths: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    text: str = ""
    language: str = ""
    audio_duration_sec: float = 0.0
    queued_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    queue_ms: int = 0
    load_ms: int = 0
    infer_ms: int = 0
    post_ms: int = 0
    total_ms: int = 0
    rtf_infer: float = 0.0
    rtf_total: float = 0.0
    peak_cpu_pct: float = 0.0
    peak_gpu_pct: float = 0.0
    peak_vram_mb: float = 0.0
    peak_ram_mb: float = 0.0
    peak_gpu_temp_c: float = 0.0
    warnings: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    error_code: str = ""
    error_message: str = ""
    retry_of: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TaskEvent(SQLModel, table=True):
    __tablename__ = "task_events"

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    phase: str = ""
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class ResourceAlert(SQLModel, table=True):
    __tablename__ = "resource_alerts"

    id: str = Field(default_factory=new_id, primary_key=True)
    ts: datetime = Field(default_factory=utcnow, index=True)
    severity: str = "warning"  # warning | high | critical
    metric: str = ""
    value: float = 0.0
    threshold: float = 0.0
    model_id: str = ""
    task_id: str = ""
    message: str = ""
    acknowledged: bool = False


class SettingsProfile(SQLModel, table=True):
    __tablename__ = "settings_profiles"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    scope: str = "global"  # global | model
    model_id: str = ""
    values: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    is_default: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AppSetting(SQLModel, table=True):
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)


class StartupRun(SQLModel, table=True):
    __tablename__ = "startup_runs"

    id: str = Field(default_factory=new_id, primary_key=True)
    app_version: str = ""
    started_at: datetime = Field(default_factory=utcnow, index=True)
    ready_at: Optional[datetime] = None
    total_ms: int = 0
    ok: bool = True
    error: str = ""


class StartupPhase(SQLModel, table=True):
    __tablename__ = "startup_phases"

    id: str = Field(default_factory=new_id, primary_key=True)
    run_id: str = Field(foreign_key="startup_runs.id", index=True)
    name: str = ""
    started_at: datetime = Field(default_factory=utcnow)
    duration_ms: int = 0
    status: str = "ok"
    detail: str = ""


# Useful indexes for history filters.
Index("ix_tasks_type_status", TaskRecord.type, TaskRecord.status)
Index("ix_tasks_model_created", TaskRecord.model_id, TaskRecord.created_at)
Index("ix_alerts_metric_ts", ResourceAlert.metric, ResourceAlert.ts)
