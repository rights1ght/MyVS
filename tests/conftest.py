"""Shared pytest fixtures.

The data directory is redirected to a throw-away temp folder *before* any
``backend`` module is imported, so running the suite never touches the real
``data/`` directory (database, uploads, user_models.yaml, HF cache).
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="myvs-tests-"))
os.environ["MYVS_DATA_DIR"] = str(_TMP / "data")
os.environ["MYVS_DISABLE_NVML"] = "1"
os.environ["MYVS_AUTO_BROWSER"] = "0"
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import soundfile as sf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.config import settings  # noqa: E402


def make_wav(path: Path, seconds: float = 6.0, sample_rate: int = 24000, amplitude: float = 0.2) -> Path:
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)
    audio = (amplitude * np.sin(2 * np.pi * 180 * t) * envelope).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, sample_rate, subtype="PCM_16")
    return path


@pytest.fixture(scope="session", autouse=True)
def _guard_data_dir() -> None:
    assert str(settings.data_dir).startswith(str(_TMP)), "tests must not use the real data dir"


@pytest.fixture()
def wav_file(tmp_path: Path) -> Path:
    return make_wav(tmp_path / "ref.wav")


@pytest.fixture()
def client() -> Any:
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# --------------------------------------------------------------------- fakes
class FakeWorker:
    """In-process stand-in for the subprocess ``WorkerClient``."""

    instances: list["FakeWorker"] = []
    fail_infer_code: str | None = None

    def __init__(self, spec: dict[str, Any], *, log_prefix: str = "worker") -> None:
        self.spec = spec
        self.pid = 4242
        self._alive = False
        self.infer_calls: list[dict[str, Any]] = []
        FakeWorker.instances.append(self)

    @property
    def alive(self) -> bool:
        return self._alive

    def start(self, timeout: float = 900.0) -> dict[str, Any]:
        self._alive = True
        device = "cuda:0" if self.spec.get("device") == "gpu" else "cpu"
        return {"device": device, "ram_rss_mb": 256.0, "vram_allocated_mb": 0.0, "load_seconds": 0.01}

    def call(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def infer(self, payload: dict[str, Any], on_progress: Any = None) -> dict[str, Any]:
        from backend.engines.worker_client import WorkerError

        self.infer_calls.append(payload)
        if FakeWorker.fail_infer_code:
            raise WorkerError(FakeWorker.fail_infer_code, "boom")
        if "audio_path" in payload:
            return {
                "text": "привет мир",
                "language": "ru",
                "language_probability": 0.99,
                "audio_duration_sec": 2.0,
                "infer_seconds": 0.01,
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "привет"},
                    {"start": 1.0, "end": 2.0, "text": "мир"},
                ],
            }
        amplitude = 0.3
        path = Path(payload["output_path"])
        make_wav(path, seconds=1.0, amplitude=amplitude)
        return {"output_path": str(path), "sample_rate": 24000, "infer_seconds": 0.01}

    def unload(self) -> None:
        self._alive = False

    def kill(self) -> None:
        self._alive = False


@pytest.fixture()
def fake_worker(monkeypatch: pytest.MonkeyPatch) -> type[FakeWorker]:
    from backend.services import resource_manager as rm

    FakeWorker.instances = []
    FakeWorker.fail_infer_code = None
    monkeypatch.setattr(rm, "WorkerClient", FakeWorker)
    plentiful = {
        "gpu_total_gb": 24.0, "gpu_used_gb": 1.0, "free_vram_gb": 20.0,
        "ram_total_gb": 64.0, "ram_used_gb": 8.0, "free_ram_gb": 48.0,
        "reserve_vram_gb": 0.8, "reserve_ram_gb": 3.0, "reserved_vram_gb": 0.0, "gpu_available": True,
    }
    monkeypatch.setattr(rm.resources, "_mem", lambda: dict(plentiful))
    yield FakeWorker
    rm.resources.unload_all(force=True)


def set_installed(model_id: str, variant_suffix: str | None = None, state: str = "installed") -> str:
    """Mark a catalog variant as installed straight in the DB. Returns variant id."""
    from backend.db.models import ModelVariant
    from backend.db.session import session_scope
    from backend.services.model_registry import registry

    variants = registry.variants(model_id)
    variant = next((v for v in variants if variant_suffix is None or v.id.endswith(f":{variant_suffix}")), None)
    assert variant is not None, f"{model_id}:{variant_suffix} not in catalog"
    with session_scope() as session:
        row = session.get(ModelVariant, variant.id)
        row.install_state = state
        session.add(row)
    return variant.id


def wait_for_task(client: TestClient, task_id: str, *, timeout: float = 15.0, until: tuple[str, ...] = ("completed", "failed", "cancelled", "awaiting_decision")) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = client.get(f"/api/tasks/{task_id}").json()
        if last.get("status") in until:
            return last
        time.sleep(0.1)
    raise AssertionError(f"task {task_id} stuck in {last.get('status')}: {last}")
