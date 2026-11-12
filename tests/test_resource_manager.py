import time

import pytest

from backend.engines.worker_client import WorkerError
from backend.services.resource_manager import ModelRuntime, ResourceError, resources
from tests.conftest import FakeWorker, set_installed

TINY = "faster-whisper-tiny"


@pytest.fixture()
def installed(client, fake_worker, monkeypatch):
    monkeypatch.setattr(resources, "_policy", "ask")
    monkeypatch.setattr(resources, "_mode", "parallel")
    set_installed(TINY, "cpu-int8")
    yield
    resources.unload_all(force=True)
    set_installed(TINY, "cpu-int8", "not_installed")


def _fake_runtime(model_id: str, *, idle_for: float = 0.0, busy: bool = False, device: str = "cuda:0", worker=None) -> ModelRuntime:
    worker = worker or FakeWorker({})
    worker._alive = True
    runtime = ModelRuntime(model_id=model_id, variant_id=f"{model_id}:x", model_name=model_id, device=device,
                           precision="fp16", worker=worker, vram_mb=1024.0)
    runtime.last_used = time.monotonic() - idle_for
    runtime.busy = busy
    resources._runtimes[model_id] = runtime
    return runtime


@pytest.fixture()
def clean_runtimes(fake_worker):
    resources._runtimes.clear()
    yield
    resources._runtimes.clear()


def test_load_reuse_and_unload(installed, fake_worker) -> None:
    runtime = resources.ensure_loaded(TINY)
    assert runtime.state == "loaded" and runtime.device == "cpu"
    assert resources.ensure_loaded(TINY) is runtime and len(fake_worker.instances) == 1
    assert resources.loaded()[0]["model_id"] == TINY
    result = resources.unload(TINY)
    assert result["unloaded"] is True and not runtime.worker.alive and not resources.is_loaded(TINY)
    assert resources.unload(TINY) == {"unloaded": False}


def test_infer_requires_loaded_model(installed) -> None:
    with pytest.raises(ResourceError) as info:
        resources.infer(TINY, {})
    assert info.value.code == "MODEL_NOT_LOADED"


def test_oom_unloads_model_and_is_retryable(installed, fake_worker) -> None:
    resources.ensure_loaded(TINY)
    fake_worker.fail_infer_code = "OOM"
    with pytest.raises(ResourceError) as info:
        resources.infer(TINY, {"audio_path": "x"})
    assert info.value.code == "OOM" and info.value.details["retryable"] is True
    assert not resources.is_loaded(TINY)


@pytest.mark.parametrize("code", ["WORKER_DIED", "WORKER_TIMEOUT"])
def test_dead_worker_is_dropped_and_killed(installed, fake_worker, code) -> None:
    runtime = resources.ensure_loaded(TINY)
    fake_worker.fail_infer_code = code
    with pytest.raises(ResourceError) as info:
        resources.infer(TINY, {"audio_path": "x"})
    assert info.value.code == code
    assert not resources.is_loaded(TINY) and not runtime.worker.alive and runtime.busy is False


def test_busy_model_cannot_be_unloaded_without_force(installed) -> None:
    runtime = resources.ensure_loaded(TINY)
    runtime.busy = True
    with pytest.raises(ResourceError) as info:
        resources.unload(TINY)
    assert info.value.code == "MODEL_BUSY"
    runtime.busy = False
    assert resources.unload(TINY, force=True)["unloaded"] is True


def test_load_failure_cleans_up_reservation(installed, monkeypatch) -> None:
    class Boom(FakeWorker):
        def start(self, timeout=900.0):
            self._alive = True
            raise WorkerError("WORKER_START_FAILED", "no cuda")

    from backend.services import resource_manager as rm
    monkeypatch.setattr(rm, "WorkerClient", Boom)
    with pytest.raises(ResourceError) as info:
        resources.ensure_loaded(TINY)
    assert info.value.code == "WORKER_START_FAILED"
    assert not resources.is_loaded(TINY) and resources._reserved_ram_gb == 0 and resources._reserved_vram_gb == 0


def test_not_installed_model_is_refused(client, fake_worker) -> None:
    with pytest.raises(ResourceError) as info:
        resources.ensure_loaded("kokoro-82m")
    assert info.value.code in ("MODEL_NOT_INSTALLED", "VARIANT_NOT_INSTALLED")


def test_evict_lru_unloads_oldest_idle_first_and_skips_busy(clean_runtimes) -> None:
    _fake_runtime("old", idle_for=300)
    _fake_runtime("busy", idle_for=900, busy=True)
    _fake_runtime("new", idle_for=10)
    evicted = resources.evict_lru(required_gb=0.0)
    assert len(evicted) == 1 and not resources.is_loaded("old")
    assert resources.is_loaded("busy") and resources.is_loaded("new")


def test_evict_lru_respects_exclude_and_cpu(clean_runtimes) -> None:
    _fake_runtime("keep", idle_for=500)
    _fake_runtime("cpu-one", idle_for=900, device="cpu")
    assert resources.evict_lru(required_gb=0.0, exclude="keep") == []


def test_unload_idle_only_idle_and_survives_a_stuck_model(clean_runtimes, monkeypatch) -> None:
    class Stuck(FakeWorker):
        def kill(self) -> None:  # process refuses to die
            pass

        def unload(self) -> None:
            raise RuntimeError("stuck")

    monkeypatch.setattr(resources, "_idle_seconds", 60)
    _fake_runtime("stuck", idle_for=500, worker=Stuck({}))
    _fake_runtime("idle", idle_for=500)
    _fake_runtime("fresh", idle_for=1)
    _fake_runtime("busy", idle_for=500, busy=True)
    results = resources.unload_idle()
    assert [r["unloaded"] for r in results] == [True]
    assert not resources.is_loaded("idle") and resources.is_loaded("fresh") and resources.is_loaded("busy")
    assert resources.is_loaded("stuck")


def test_unload_idle_disabled_with_zero(clean_runtimes, monkeypatch) -> None:
    monkeypatch.setattr(resources, "_idle_seconds", 0)
    _fake_runtime("idle", idle_for=10_000)
    assert resources.unload_idle() == [] and resources.is_loaded("idle")
    assert len(resources.unload_idle(force=True)) == 1


def test_exclusive_mode_unloads_other_gpu_models(clean_runtimes, monkeypatch) -> None:
    from backend.services.model_registry import registry
    monkeypatch.setattr(resources, "_mode", "exclusive")
    _fake_runtime("other", idle_for=5)
    model, variant = registry.get(TINY), registry.get_variant(TINY, "int8")
    resources._enforce_mode(model, variant)
    assert not resources.is_loaded("other")
    assert resources._exclusive_snapshot == [("other", "other:x")]
    resources._exclusive_snapshot, resources._exclusive_target = [], ""


def test_exclusive_mode_refuses_while_gpu_is_busy(clean_runtimes, monkeypatch) -> None:
    from backend.services.model_registry import registry
    monkeypatch.setattr(resources, "_mode", "exclusive")
    _fake_runtime("busy", busy=True)
    with pytest.raises(ResourceError) as info:
        resources._enforce_mode(registry.get(TINY), registry.get_variant(TINY, "int8"))
    assert info.value.code == "GPU_BUSY"


def test_plan_verdicts(installed, monkeypatch) -> None:
    plan = resources.plan(TINY, "cpu-int8", "cpu")
    assert plan.verdict == "fits" and plan.options == [] and plan.need_vram_gb == 0
    set_installed(TINY, "int8")
    tight = {"free_vram_gb": 1.3, "free_ram_gb": 48.0}
    monkeypatch.setattr(resources, "_mem", lambda: dict(tight))
    assert resources.plan(TINY, "int8").verdict == "tight"
    monkeypatch.setattr(resources, "_mem", lambda: {"free_vram_gb": 0.2, "free_ram_gb": 48.0})
    no = resources.plan(TINY, "int8")
    assert no.verdict == "no" and {o["action"] for o in no.options} >= {"cpu", "cancel"}
    assert len({o["id"] for o in no.options}) == len(no.options)
    set_installed(TINY, "int8", "not_installed")


def test_plan_uses_installed_variant_when_none_requested(installed) -> None:
    assert resources.plan(TINY).variant_id.endswith(":cpu-int8")


def test_plan_errors(client) -> None:
    with pytest.raises(ResourceError) as info:
        resources.plan("missing")
    assert info.value.code == "MODEL_NOT_FOUND"
    with pytest.raises(ResourceError) as info:
        resources.plan(TINY)
    assert info.value.code == "MODEL_NOT_INSTALLED"


def test_set_mode_validation() -> None:
    with pytest.raises(ResourceError):
        resources.set_mode("turbo")


def test_resources_endpoints(client, installed) -> None:
    status = client.get("/api/resources/status").json()
    assert status["memory"]["free_vram_gb"] >= 0
    assert client.post("/api/resources/plan", json={"model_id": TINY}).json()["verdict"] == "fits"
    assert client.post("/api/resources/plan", json={"model_id": "missing"}).json()["error"]["code"] == "MODEL_NOT_FOUND"
    loaded = client.post(f"/api/models/{TINY}/load", json={}).json()
    assert loaded["loaded"] is True and loaded["runtime"]["state"] == "loaded"
    assert client.post("/api/resources/evict", json={"model_id": TINY}).json()["unloaded"] is True
    client.post(f"/api/models/{TINY}/load", json={})
    assert client.post("/api/resources/unload-all").json()["count"] == 1
    assert client.post("/api/models/kokoro-82m/load", json={}).status_code == 409
    assert client.get(f"/api/models/{TINY}/compatibility").json()["verdict"] == "fits"
