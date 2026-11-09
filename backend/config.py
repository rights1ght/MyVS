from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Runtime configuration. Values can be overridden with MYVS_* variables."""

    model_config = SettingsConfigDict(
        env_prefix="MYVS_",
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MyVS"
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = ROOT_DIR / "data"
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"
    models_yaml: Path = ROOT_DIR / "backend" / "models.yaml"
    user_models_yaml: Path = ROOT_DIR / "data" / "user_models.yaml"
    hf_cache: Path = Path(os.environ.get("HF_HOME", ROOT_DIR / "data" / "models" / "hf-cache"))

    reserve_vram_gb: float = 0.8
    reserve_ram_gb: float = 3.0
    idle_unload_seconds: int = 600
    resource_mode: str = "parallel"  # parallel | economy | exclusive
    conflict_policy: str = "ask"  # ask | auto
    auto_browser: bool = True
    disable_nvml: bool = False
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def frontend_index(self) -> Path:
        return self.frontend_dist / "index.html"

    def ensure_dirs(self) -> None:
        for name in ("", "models", "voices", "outputs", "uploads", "tmp", "logs"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Keep environment visible to child workers without passing secrets around.
os.environ.setdefault("MYVS_ROOT", str(ROOT_DIR))
