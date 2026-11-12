from pathlib import Path

import pytest

from backend.config import settings
from backend.services.model_registry import registry
from tests.conftest import set_installed

TINY = "faster-whisper-tiny"


def _tiny_variant():
    return registry.get_variant(TINY, "cpu-int8")


def _cache_root(repo: str) -> Path:
    return settings.hf_cache / f"models--{repo.replace('/', '--')}"


@pytest.fixture()
def empty_hf_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "hf_cache", tmp_path / "hf")
    set_installed(TINY, "cpu-int8", "not_installed")
    yield
    set_installed(TINY, "cpu-int8", "not_installed")


def test_catalog_integrity() -> None:
    ids = {m.id for m in registry.all()}
    from backend.services.voices import BUILTIN
    assert {model_id for _n, model_id, *_ in BUILTIN} <= ids, "builtin voices reference unknown models"
    for model in registry.all():
        assert model.enabled, f"{model.id} disabled (unknown adapter?)"
        assert registry.variants(model.id), f"{model.id} has no variants"
        for variant in registry.variants(model.id):
            assert variant.source.get("type") in ("hf", "hf_files", "url_files", "package", "local")
            if variant.source.get("type") in ("hf", "hf_files"):
                assert variant.source.get("repo") and variant.source.get("revision"), f"{variant.id}: unpinned"


def test_resolve_variant_prefers_installed_over_first_catalog_entry(empty_hf_cache) -> None:
    set_installed(TINY, "cpu-int8")
    assert registry.get_variant(TINY).id.endswith(":int8"), "first catalog entry is the GPU build"
    assert registry.resolve_variant(TINY).id.endswith(":cpu-int8")
    assert registry.resolve_variant(TINY, "int8").id.endswith(":int8")
    assert registry.resolve_variant(TINY, "nope") is None


def test_hf_cache_empty_snapshot_is_not_an_install(empty_hf_cache) -> None:
    (_cache_root("Systran/faster-whisper-tiny") / "snapshots" / "abc123").mkdir(parents=True)
    registry.sync()
    assert _tiny_variant().install_state == "not_installed"


def test_hf_cache_incomplete_download_is_not_an_install(empty_hf_cache) -> None:
    root = _cache_root("Systran/faster-whisper-tiny")
    revision = _tiny_variant().source["revision"]
    snapshot = root / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    (root / "blobs").mkdir()
    (root / "blobs" / "deadbeef.incomplete").write_bytes(b"partial")
    registry.sync()
    assert _tiny_variant().install_state == "not_installed"


def test_hf_cache_complete_snapshot_is_reused(empty_hf_cache) -> None:
    root = _cache_root("Systran/faster-whisper-tiny")
    revision = _tiny_variant().source["revision"]
    snapshot = root / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"weights")
    (snapshot / "config.json").write_text("{}")
    registry.sync()
    variant = _tiny_variant()
    assert variant.install_state == "installed" and variant.install_path == str(snapshot)


def test_hf_cache_prefers_pinned_revision(empty_hf_cache) -> None:
    root = _cache_root("Systran/faster-whisper-tiny")
    pinned = _tiny_variant().source["revision"]
    for name in ("zzz-newer-sorts-last", pinned):
        (root / "snapshots" / name).mkdir(parents=True)
        (root / "snapshots" / name / "model.bin").write_bytes(b"w")
    registry.sync()
    assert Path(_tiny_variant().install_path).name == pinned


def test_hf_files_cache_requires_every_included_file(empty_hf_cache, monkeypatch) -> None:
    set_installed("piper", "en-voices", "not_installed")
    variant = registry.get_variant("piper", "en-voices")
    root = _cache_root(variant.source["repo"])
    snapshot = root / "snapshots" / variant.source["revision"]
    files = variant.source["include"]
    for name in files[:-1]:  # one file missing
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    registry.sync()
    assert registry.get_variant("piper", "en-voices").install_state == "not_installed"
    last = snapshot / files[-1]
    last.parent.mkdir(parents=True, exist_ok=True)
    last.write_bytes(b"x")
    registry.sync()
    assert registry.get_variant("piper", "en-voices").install_state == "installed"
    set_installed("piper", "en-voices", "not_installed")


def test_custom_model_validation(client) -> None:
    base = {"name": "x", "adapter": "piper", "path": "/tmp"}
    for bad_id in ("", "   ", "../evil", "a/b", "a\\b", "x" * 100, ".hidden"):
        response = client.post("/api/models/custom", json={**base, "id": bad_id})
        assert response.status_code == 400, bad_id
        assert response.json()["error"]["code"] == "CUSTOM_MODEL_INVALID"
    assert client.post("/api/models/custom", json={**base, "id": "custom-bad-adapter", "adapter": "nope"}).status_code == 400
    assert client.post("/api/models/custom", json={**base, "id": "piper"}).status_code == 400  # duplicate of catalog id


def test_custom_model_lifecycle(client) -> None:
    created = client.post("/api/models/custom", json={"id": "custom-life", "name": "Life", "adapter": "piper", "path": "/tmp"})
    assert created.status_code == 200 and created.json()["is_custom"] is True
    assert any(m["id"] == "custom-life" for m in client.get("/api/models").json())

    assert client.delete("/api/models/custom/custom-life").json() == {"removed": True}
    assert registry.get("custom-life") is None and registry.variants("custom-life") == []
    assert all(m["id"] != "custom-life" for m in client.get("/api/models").json())
    assert client.delete("/api/models/custom/custom-life").status_code == 404
    assert client.delete("/api/models/custom/piper").status_code == 404  # catalog models are not removable


def test_custom_model_in_use_by_voice_cannot_be_removed(client) -> None:
    client.post("/api/models/custom", json={"id": "custom-used", "name": "U", "adapter": "qwen3_tts_design", "path": "/tmp",
                                             "capabilities": ["voice_design"], "category": "clone"})
    voice = client.post("/api/voices/design", json={"name": "v", "description": "d", "model_id": "custom-used"}).json()["voice"]
    response = client.delete("/api/models/custom/custom-used")
    assert response.status_code == 409 and response.json()["error"]["code"] == "CUSTOM_MODEL_IN_USE"
    client.delete(f"/api/voices/{voice['id']}")
    assert client.delete("/api/models/custom/custom-used").status_code == 200


def test_user_models_file_lives_under_data_dir() -> None:
    assert settings.data_dir in settings.user_models_yaml.parents
    assert settings.data_dir in settings.hf_cache.parents


def test_model_list_filters(client) -> None:
    assert {m["category"] for m in client.get("/api/models", params={"category": "stt"}).json()} == {"stt"}
    assert all("ru" in m["languages"] for m in client.get("/api/models", params={"language": "ru"}).json())
    assert client.get("/api/models", params={"q": "whisper"}).json()
    assert client.get("/api/models", params={"installed": True, "category": "stt"}).json() == []
    assert client.get("/api/models/missing").status_code == 404
    measurements = client.get(f"/api/models/{TINY}/measurements").json()  # other tests may have loaded the model
    assert isinstance(measurements, list) and all(m["model_id"] == TINY for m in measurements)
