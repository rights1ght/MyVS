from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, desc, select

from backend.config import settings
from backend.db.models import ModelMeasurement, ModelRecord, ModelVariant
from backend.db.session import session_scope

logger = logging.getLogger(__name__)

KNOWN_ADAPTERS = {
    "faster_whisper",
    "gigaam",
    "piper",
    "silero",
    "kokoro",
    "chatterbox",
    "chatterbox_turbo",
    "qwen3_tts",
    "qwen3_tts_design",
    "voxcpm2",
    "omnivoice",
}


def package_available(package: str) -> bool:
    if importlib.util.find_spec(package):
        return True
    root = Path(__file__).resolve().parents[2]
    envs = {
        "gigaam": "gigaam",
        "omnivoice": "omnivoice",
        "chatterbox": "chatterbox",
        "voxcpm": "voxcpm",
        "qwen_tts": "qwen",
    }
    env = envs.get(package)
    if env:
        python = root / ".venvs" / env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        return python.exists()
    return False


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class ModelRegistry:
    def __init__(self) -> None:
        self.catalog: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        data = _read_yaml(settings.models_yaml)
        models = list(data.get("models") or [])
        user = _read_yaml(settings.user_models_yaml)
        models.extend(user.get("models") or [])
        merged: dict[str, dict[str, Any]] = {}
        for item in models:
            model_id = str(item.get("id", "")).strip()
            if not model_id:
                logger.warning("catalog entry without id skipped")
                continue
            if model_id in merged:
                logger.warning("duplicate model id %s; user entry ignored", model_id)
                continue
            item.setdefault("category", "stt")
            item.setdefault("adapter", "faster_whisper")
            item.setdefault("languages", [])
            item.setdefault("capabilities", [])
            item.setdefault("warnings", [])
            item.setdefault("commercial", False)
            item.setdefault("russian", "verify")
            item.setdefault("variants", [])
            item.setdefault("requires_exclusive", False)
            item.setdefault("requires_consent", False)
            item.setdefault("watermark", False)
            item.setdefault("enabled", True)
            if item["adapter"] not in KNOWN_ADAPTERS:
                item["enabled"] = False
                item["warnings"] = list(item["warnings"]) + [
                    f"Адаптер {item['adapter']} не установлен в этой сборке."
                ]
            merged[model_id] = item
        self.catalog = merged

    def sync(self) -> None:
        self.load()
        custom_ids = {str(item.get("id")) for item in (_read_yaml(settings.user_models_yaml).get("models") or [])}
        with session_scope() as session:
            for model_id, spec in self.catalog.items():
                record = session.get(ModelRecord, model_id)
                if record is None:
                    record = ModelRecord(id=model_id)
                    session.add(record)
                record.name = str(spec.get("name") or model_id)
                record.category = str(spec.get("category") or "stt")
                record.adapter = str(spec.get("adapter") or "faster_whisper")
                record.description = str(spec.get("description") or "")
                record.license = str(spec.get("license") or "unknown")
                record.license_url = str(spec.get("license_url") or "")
                record.commercial = bool(spec.get("commercial"))
                record.russian_status = str(spec.get("russian") or "verify")
                record.languages = list(spec.get("languages") or [])
                record.capabilities = list(spec.get("capabilities") or [])
                record.warnings = list(spec.get("warnings") or [])
                record.requires_exclusive = bool(spec.get("requires_exclusive"))
                record.requires_consent = bool(spec.get("requires_consent"))
                record.watermark = bool(spec.get("watermark"))
                record.is_custom = model_id in custom_ids
                record.enabled = bool(spec.get("enabled", True))
                record.source = spec
                session.add(record)

                for variant_spec in spec.get("variants") or []:
                    variant_id = f"{model_id}:{variant_spec.get('id', 'default')}"
                    variant = session.get(ModelVariant, variant_id)
                    if variant is None:
                        variant = ModelVariant(id=variant_id, model_id=model_id)
                        session.add(variant)
                    variant.label = str(variant_spec.get("label") or variant_spec.get("id") or "")
                    variant.device = str(variant_spec.get("device") or "gpu")
                    variant.precision = str(variant_spec.get("precision") or "fp16")
                    variant.vram_estimate_gb = float(variant_spec.get("vram_gb") or 0)
                    variant.ram_estimate_gb = float(variant_spec.get("ram_gb") or 0)
                    variant.disk_gb = float(variant_spec.get("disk_gb") or 0)
                    variant.source = dict(variant_spec.get("download") or {})
                    download = variant.source or {}
                    if download.get("type") == "package":
                        package = str(download.get("package") or "")
                        if package and package_available(package):
                            if variant.install_state in ("not_installed", "error", ""):
                                variant.install_state = "installed"
                        elif variant.install_state not in ("downloaded", "downloading", "paused"):
                            variant.install_state = "not_installed"
                    elif download.get("type") in ("hf", "hf_files", "url_files"):
                        expected = settings.data_dir / "models" / model_id / str(variant_spec.get("id") or "default")
                        if not variant.install_path:
                            variant.install_path = str(expected)
                        if (expected / ".myvs-complete").exists():
                            variant.install_state = "installed"
                        elif variant.install_state not in ("downloading", "paused", "error"):
                            variant.install_state = "not_installed"
                        # Reuse an existing Hugging Face cache when the whole repo is already there.
                        repo = str(download.get("repo") or "")
                        if repo and variant.install_state == "not_installed":
                            cache_folder = settings.hf_cache / f"models--{repo.replace('/', '--')}" / "snapshots"
                            snapshots = sorted(cache_folder.glob("*")) if cache_folder.exists() else []
                            if snapshots:
                                variant.install_state = "installed"
                                variant.install_path = str(snapshots[-1])
                    elif download.get("type") == "local":
                        path = Path(str(download.get("path") or ""))
                        variant.install_path = str(path)
                        if path.exists() and variant.install_state != "downloading":
                            variant.install_state = "installed"
                    session.add(variant)
        # Remove catalog variants that no longer exist in YAML, but keep custom models.
        known_ids = {f"{mid}:{v.get('id', 'default')}" for mid, spec in self.catalog.items() for v in spec.get("variants", [])}
        with session_scope() as session:
            for variant in session.exec(select(ModelVariant)).all():
                if variant.id not in known_ids and not variant.id.split(":", 1)[0].startswith("custom-"):
                    # Preserve downloaded artifacts on disk, only hide the row.
                    session.delete(variant)

    def all(self, category: str | None = None) -> list[ModelRecord]:
        with session_scope() as session:
            statement = select(ModelRecord).order_by(ModelRecord.category, ModelRecord.name)
            if category:
                statement = statement.where(ModelRecord.category == category)
            return list(session.exec(statement).all())

    def get(self, model_id: str) -> ModelRecord | None:
        with session_scope() as session:
            return session.get(ModelRecord, model_id)

    def variants(self, model_id: str) -> list[ModelVariant]:
        with session_scope() as session:
            return list(session.exec(select(ModelVariant).where(ModelVariant.model_id == model_id)).all())

    def get_variant(self, model_id: str, variant_id: str | None = None) -> ModelVariant | None:
        variants = self.variants(model_id)
        if not variants:
            return None
        if variant_id:
            for variant in variants:
                if variant.id == variant_id or variant.id.endswith(f":{variant_id}"):
                    return variant
            return None
        return variants[0]

    def default_variant(self, model_id: str) -> ModelVariant | None:
        variants = self.variants(model_id)
        gpu = [v for v in variants if v.device == "gpu" and v.install_state == "installed"]
        if gpu:
            return gpu[0]
        installed = [v for v in variants if v.install_state == "installed"]
        return installed[0] if installed else (variants[0] if variants else None)

    def latest_measurement(self, model_id: str, variant_id: str) -> ModelMeasurement | None:
        with session_scope() as session:
            return session.exec(
                select(ModelMeasurement)
                .where(ModelMeasurement.model_id == model_id, ModelMeasurement.variant_id == variant_id)
                .order_by(desc(ModelMeasurement.measured_at))
                .limit(1)
            ).first()

    def model_public(self, model_id: str) -> dict[str, Any] | None:
        model = self.get(model_id)
        if not model:
            return None
        variants = []
        for variant in self.variants(model_id):
            measurement = self.latest_measurement(model_id, variant.id)
            variants.append(
                {
                    **variant.model_dump(),
                    "measurement": measurement.model_dump() if measurement else None,
                }
            )
        return {
            **model.model_dump(),
            "variants": variants,
            "installed": any(v.install_state == "installed" for v in self.variants(model_id)),
        }

    def remove_custom(self, model_id: str) -> bool:
        data = _read_yaml(settings.user_models_yaml)
        models = list(data.get("models") or [])
        filtered = [item for item in models if str(item.get("id")) != model_id]
        if len(filtered) == len(models):
            return False
        data["models"] = filtered
        with settings.user_models_yaml.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
        self.sync()
        return True

    def add_custom(self, payload: dict[str, Any]) -> ModelRecord:
        model_id = str(payload.get("id") or "").strip()
        if not model_id:
            raise ValueError("id is required")
        if model_id in self.catalog:
            raise ValueError("model id already exists")
        if payload.get("adapter") not in KNOWN_ADAPTERS:
            raise ValueError("unknown adapter")
        variant = payload.get("variant") or {}
        local_path = str(payload.get("path") or variant.get("path") or "")
        download_spec = variant.get("download") or {"type": "local", "path": local_path}
        if download_spec.get("type") == "local":
            download_spec = {"type": "local", "path": local_path or download_spec.get("path", "")}
        entry = {
            "id": model_id,
            "name": payload.get("name") or model_id,
            "category": payload.get("category") or "tts",
            "adapter": payload.get("adapter"),
            "description": payload.get("description") or "Пользовательская модель",
            "license": payload.get("license") or "unknown",
            "license_url": payload.get("license_url") or "",
            "commercial": bool(payload.get("commercial")),
            "russian": payload.get("russian") or "verify",
            "languages": payload.get("languages") or ["ru"],
            "capabilities": payload.get("capabilities") or [],
            "warnings": ["Пользовательская модель; качество и лицензия не проверены приложением."],
            "variants": [
                {
                    "id": "custom",
                    "label": "custom",
                    "device": variant.get("device") or "gpu",
                    "precision": variant.get("precision") or "fp16",
                    "vram_gb": float(variant.get("vram_gb") or 0),
                    "ram_gb": float(variant.get("ram_gb") or 0),
                    "disk_gb": float(variant.get("disk_gb") or 0),
                    "download": download_spec,
                }
            ],
        }
        data = _read_yaml(settings.user_models_yaml)
        models = list(data.get("models") or [])
        models.append(entry)
        data["models"] = models
        settings.user_models_yaml.parent.mkdir(parents=True, exist_ok=True)
        with settings.user_models_yaml.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
        self.sync()
        record = self.get(model_id)
        if record is None:
            raise RuntimeError("failed to add model")
        return record


registry = ModelRegistry()
