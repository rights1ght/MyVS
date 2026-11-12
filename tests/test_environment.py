"""Missing-dependency handling: HF listing without huggingface_hub, GPU via nvidia-smi, start-up self-check."""
import hashlib
import http.server
import json
import shutil
import socketserver
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

from backend.config import settings
from backend.services import nvml
from backend.services.downloads import DownloadError, downloads
from backend.services.hf_api import HubError, hf_endpoint, list_repo_files, resolve_url
from backend.services.model_registry import registry
from backend.services.preflight import check_environment, read_requirements
from tests.conftest import set_installed

REPO = "Systran/faster-whisper-tiny"


# ============================================================ fake Hugging Face Hub
class FakeHub:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.lfs: set[str] = set()
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.status = 200
        self.page_size = 1000

    def tree(self) -> list[dict]:
        entries = [{"type": "directory", "path": "onnx"}]
        for path, data in sorted(self.files.items()):
            entry = {"type": "file", "path": path, "size": len(data)}
            if path in self.lfs:
                entry["lfs"] = {"oid": hashlib.sha256(data).hexdigest(), "size": len(data), "pointerSize": 130}
            entries.append(entry)
        return entries


@pytest.fixture()
def hub(monkeypatch):
    state = FakeHub()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            state.requests.append((self.path, dict(self.headers)))
            if state.status != 200:
                self.send_response(state.status)
                self.end_headers()
                return
            if "/tree/" in parsed.path:
                entries, cursor = state.tree(), int(dict(p.split("=") for p in parsed.query.split("&") if "=" in p).get("cursor", 0))
                page = entries[cursor:cursor + state.page_size]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                if cursor + state.page_size < len(entries):
                    self.send_header("Link", f'<http://127.0.0.1:{server.server_address[1]}{parsed.path}?recursive=true&cursor={cursor + state.page_size}>; rel="next"')
                body = json.dumps(page).encode()
            else:
                name = parsed.path.split("/resolve/", 1)[-1].split("/", 1)[-1]
                if name not in state.files:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = state.files[name]
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("HF_ENDPOINT", f"http://127.0.0.1:{server.server_address[1]}/")
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)  # prove the package is not needed
    yield state
    server.shutdown()
    server.server_close()


def test_endpoint_and_urls(monkeypatch) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    assert hf_endpoint() == "https://huggingface.co"
    assert resolve_url("a/b", "main", "dir/we ird#.bin") == "https://huggingface.co/a/b/resolve/main/dir/we%20ird%23.bin"
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.example/")
    assert resolve_url("a/b", "refs/pr/1", "x.bin") == "https://hf-mirror.example/a/b/resolve/refs%2Fpr%2F1/x.bin"


def test_listing_parses_files_sizes_and_lfs_hashes(hub) -> None:
    hub.files = {"config.json": b"{}", "model.bin": b"w" * 100, "README.md": b"#"}
    hub.lfs = {"model.bin"}
    files = {f["path"]: f for f in list_repo_files(REPO, "abc123", token="secret")}
    assert set(files) == {"config.json", "model.bin", "README.md"}  # the directory entry is skipped
    assert files["model.bin"]["sha256"] == hashlib.sha256(b"w" * 100).hexdigest() and files["model.bin"]["size"] == 100
    assert files["config.json"]["sha256"] == ""
    path, headers = hub.requests[0]
    assert path.startswith(f"/api/models/{REPO}/tree/abc123?recursive=true") and headers["Authorization"] == "Bearer secret"


def test_listing_follows_pagination(hub) -> None:
    hub.files = {f"f{i:02d}.bin": b"x" for i in range(25)}
    hub.page_size = 10
    assert len(list_repo_files(REPO)) == 25 and len(hub.requests) == 3
    assert "Authorization" not in hub.requests[0][1]


@pytest.mark.parametrize(("status", "needle"), [(404, "не найден"), (401, "HF_TOKEN"), (403, "HF_TOKEN")])
def test_listing_errors_are_explained(hub, status, needle) -> None:
    hub.status = status
    with pytest.raises(HubError, match=needle):
        list_repo_files(REPO)


def test_unreachable_hub_mentions_mirror(monkeypatch) -> None:
    monkeypatch.setenv("HF_ENDPOINT", "http://127.0.0.1:9")  # nothing listens here
    with pytest.raises(HubError, match="HF_ENDPOINT"):
        list_repo_files(REPO)


def test_manifest_applies_include_filter_and_skips_readme(client, hub) -> None:
    variant = registry.get_variant("faster-whisper-tiny", "cpu-int8")
    spec = dict(variant.source)
    hub.files = {name: b"data" for name in ("config.json", "model.bin", "README.md", ".gitattributes", "unrelated.onnx")}
    files, _dest = downloads._manifest("faster-whisper-tiny", variant, spec)
    names = {f["path"] for f in files}
    assert names and "README.md" not in names and ".gitattributes" not in names
    assert all(any(__import__("fnmatch").fnmatch(n, pat) for pat in spec.get("include") or ["*"]) for n in names)
    assert all(f["url"].startswith(hf_endpoint()) and f["url"].startswith(f"{hf_endpoint()}/{spec['repo']}/resolve/{spec['revision']}/") for f in files)


def test_manifest_errors_become_download_errors(client, hub) -> None:
    variant = registry.get_variant("faster-whisper-tiny", "cpu-int8")
    hub.status = 404
    with pytest.raises(DownloadError, match="не найден"):
        downloads._manifest("faster-whisper-tiny", variant, dict(variant.source))
    hub.status = 200
    hub.files = {"unrelated.txt": b"x"}
    spec = {**variant.source, "include": ["config.json"]}
    with pytest.raises(DownloadError, match="подходящих файлов"):
        downloads._manifest("faster-whisper-tiny", variant, spec)
    with pytest.raises(DownloadError, match="не указан"):
        downloads._manifest("faster-whisper-tiny", variant, {"type": "hf"})


def test_hf_download_end_to_end_without_huggingface_hub(client, hub, monkeypatch) -> None:
    variant = registry.get_variant("faster-whisper-tiny", "cpu-int8")
    include = variant.source.get("include") or ["config.json", "model.bin"]
    hub.files = {pat.replace("*", "x"): (b"weights-" + pat.encode()) * 50 for pat in include}
    hub.lfs = set(hub.files)
    monkeypatch.setattr(settings, "hf_cache", settings.data_dir / "empty-hf-cache")
    try:
        job = downloads.start("faster-whisper-tiny", variant.id)
        deadline = time.time() + 20
        while time.time() < deadline and downloads.get(job.id).status not in ("completed", "error"):
            time.sleep(0.05)
        row = downloads.get(job.id)
        assert row.status == "completed", row.error
        installed = registry.get_variant("faster-whisper-tiny", "cpu-int8")
        assert installed.install_state == "installed"
        for name, data in hub.files.items():
            assert (Path(installed.install_path) / name).read_bytes() == data
    finally:
        # registry.sync() re-detects installs from the .myvs-complete marker on disk, so delete the files too
        shutil.rmtree(settings.data_dir / "models" / "faster-whisper-tiny", ignore_errors=True)
        set_installed("faster-whisper-tiny", "cpu-int8", "not_installed")


# ============================================================ nvidia-smi shim
SMI_ROW = "0, NVIDIA GeForce RTX 4070, 12282, 2048, 10234, 37, 55, 41.50, 1920"


@pytest.fixture()
def smi(monkeypatch):
    shim = nvml._SmiNvml("nvidia-smi")
    calls: list[tuple[str, ...]] = []
    outputs = {"gpu": SMI_ROW + "\n", "apps": "4242, 1500\n999, [N/A]\nnot-a-pid, 5\n"}

    def run(*args):
        calls.append(args)
        return outputs["apps" if "--query-compute-apps=pid,used_memory" in args else "gpu"]

    monkeypatch.setattr(shim, "_run", run)
    shim.calls, shim.outputs = calls, outputs
    return shim


def test_shim_matches_pynvml_semantics(smi) -> None:
    smi.nvmlInit()
    assert smi.nvmlDeviceGetCount() == 1
    handle = smi.nvmlDeviceGetHandleByIndex(0)
    assert smi.nvmlDeviceGetName(handle) == "NVIDIA GeForce RTX 4070"
    memory = smi.nvmlDeviceGetMemoryInfo(handle)
    assert (memory.total, memory.used, memory.free) == (12282 * 1048576, 2048 * 1048576, 10234 * 1048576)
    assert smi.nvmlDeviceGetUtilizationRates(handle).gpu == 37
    assert smi.nvmlDeviceGetTemperature(handle, smi.NVML_TEMPERATURE_GPU) == 55
    assert smi.nvmlDeviceGetPowerUsage(handle) == 41500.0  # NVML reports milliwatts
    assert smi.nvmlDeviceGetClockInfo(handle, smi.NVML_CLOCK_GRAPHICS) == 1920
    with pytest.raises(nvml.NVMLError):
        smi.nvmlDeviceGetHandleByIndex(3)


def test_shim_spawns_one_process_per_ttl_window(smi) -> None:
    for _ in range(10):
        smi.nvmlDeviceGetMemoryInfo(0)
        smi.nvmlDeviceGetUtilizationRates(0)
    assert len(smi.calls) == 1
    smi._cache = (time.monotonic() - 10, smi._cache[1])
    smi.nvmlDeviceGetName(0)
    assert len(smi.calls) == 2


def test_shim_handles_unsupported_fields_and_processes(smi) -> None:
    smi.outputs["gpu"] = "0, Tesla T4, 15360, 100, 15260, [N/A], [Not Supported], [N/A], 1500\n"
    smi._cache = None
    assert smi.nvmlDeviceGetMemoryInfo(0).total == 15360 * 1048576
    for call in (smi.nvmlDeviceGetUtilizationRates, smi.nvmlDeviceGetTemperature, smi.nvmlDeviceGetPowerUsage):
        with pytest.raises(nvml.NVMLError):
            call(0)
    processes = smi.nvmlDeviceGetComputeRunningProcesses(0)
    assert [(p.pid, p.usedGpuMemory) for p in processes] == [(4242, 1500 * 1048576), (999, None)]
    smi.outputs["gpu"] = ""
    smi._cache = None
    with pytest.raises(nvml.NVMLError):
        smi.nvmlDeviceGetCount()


def test_loader_prefers_real_pynvml_then_smi_then_none(monkeypatch) -> None:
    fake = type(sys)("pynvml")
    monkeypatch.setitem(sys.modules, "pynvml", fake)
    assert nvml._load() == (fake, "nvidia-ml-py", "")

    monkeypatch.setitem(sys.modules, "pynvml", None)  # import fails
    monkeypatch.setattr(nvml, "find_nvidia_smi", lambda: "C:/Windows/System32/nvidia-smi.exe")
    module, backend, error = nvml._load()
    assert isinstance(module, nvml._SmiNvml) and backend == "nvidia-smi" and error == ""

    monkeypatch.setattr(nvml, "find_nvidia_smi", lambda: None)
    module, backend, error = nvml._load()
    assert module is None and backend == "none" and "pip install nvidia-ml-py" in error


def test_smi_failure_is_reported_as_nvml_error(monkeypatch) -> None:
    shim = nvml._SmiNvml("nvidia-smi")
    monkeypatch.setattr(nvml.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 9, "stdout": "", "stderr": "driver not loaded"})())
    with pytest.raises(nvml.NVMLError, match="driver not loaded"):
        shim.nvmlInit()


def test_monitor_and_scheduler_see_the_gpu_through_the_shim(smi, monkeypatch) -> None:
    from backend.services import monitor as monitor_module
    from backend.services.resource_manager import resources

    monkeypatch.setattr(settings, "disable_nvml", False)
    monkeypatch.setattr(monitor_module, "pynvml", smi)
    gpu_monitor = monitor_module.Monitor()
    assert gpu_monitor.probe_gpu()["available"] is True and gpu_monitor.probe_gpu()["total_mb"] == pytest.approx(12282, abs=1)
    snapshot = gpu_monitor._gpu_snapshot()
    assert snapshot["util"] == 37 and snapshot["temp_c"] == 55 and snapshot["power_w"] == 41.5 and snapshot["vram_used_mb"] == 2048

    monkeypatch.setattr(nvml, "pynvml", smi)  # resource manager imports it lazily from this module
    resources._refresh_gpu()
    assert resources._gpu_available is True and resources._gpu_total_mb == pytest.approx(12282, abs=1)
    assert resources._gpu_process_used(4242) == pytest.approx(1500 / 1024, abs=0.01)
    monkeypatch.setattr(settings, "disable_nvml", True)
    resources._refresh_gpu()
    assert resources._gpu_available is False


# ============================================================ start-up self-check
GOOD = {"fastapi": "", "torch": "2.8.0", "torchaudio": "2.8.0", "faster-whisper": "1.2.1"}


def versions(**overrides):
    table = {name: "1.0" for name in GOOD} | overrides
    return lambda name: table.get(name)


def test_requirements_are_parsed_from_the_real_file() -> None:
    wanted = read_requirements()
    assert wanted["torch"] == "2.8.0" and wanted["fastapi"] == "" and "nvidia-ml-py" in wanted and "huggingface-hub" in wanted
    assert not any(name.startswith("-") for name in wanted)
    assert read_requirements(Path("/nonexistent/requirements.txt")) == {}


def test_all_installed_means_no_warnings() -> None:
    assert check_environment(requirements=GOOD, version_of=versions(), gpu_present=True, platform="linux") == []


def test_missing_packages_are_listed_with_the_exact_fix() -> None:
    (problem,) = check_environment(requirements=GOOD, version_of=versions(**{"faster-whisper": None}), python=r"C:\MyVS\.venv\Scripts\python.exe")
    assert problem["code"] == "MISSING_PACKAGES" and problem["packages"] == ["faster-whisper"]
    assert r'"C:\MyVS\.venv\Scripts\python.exe" -m pip install -r requirements.txt' in problem["message"]


@pytest.mark.parametrize(
    ("torch", "platform", "gpu", "warns"),
    [
        ("2.8.0", "win32", True, True),  # PyPI wheel on Windows = CPU only
        ("2.8.0+cpu", "win32", True, True),
        ("2.8.0+cpu", "linux", True, True),
        ("2.8.0+cu128", "win32", True, False),
        ("2.8.0", "linux", True, False),  # untagged Linux wheel is the CUDA build
        ("2.8.0", "win32", False, False),  # no NVIDIA GPU -> nothing to fix
    ],
)
def test_cpu_only_torch_is_detected(torch, platform, gpu, warns) -> None:
    problems = check_environment(requirements=GOOD, version_of=versions(torch=torch), gpu_present=gpu, platform=platform)
    assert bool(problems) is warns
    if warns:
        assert problems[0]["code"] == "TORCH_WITHOUT_CUDA" and "torch==2.8.0 torchaudio==2.8.0" in problems[0]["message"]
        assert "download.pytorch.org/whl/cu128" in problems[0]["message"]


def test_diagnostics_endpoint_reports_python_warnings_and_backend(client) -> None:
    body = client.get("/api/system/diagnostics").json()
    assert body["python"] == sys.executable and isinstance(body["warnings"], list)
    assert "huggingface-hub" in body["packages"] and "backend" in body["gpu"]
