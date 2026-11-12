import io
from pathlib import Path

import pytest

from sqlmodel import select

from backend.config import settings
from backend.db.models import Voice, VoiceCache
from backend.db.session import session_scope
from backend.services import voices as voices_service


def _voice_dirs() -> set[str]:
    folder = settings.data_dir / "voices"
    return {p.name for p in folder.iterdir()} if folder.exists() else set()


def _upload(path: Path) -> dict:
    return {"file": (path.name, path.read_bytes(), "audio/wav")}


def test_analyze_ok(client, wav_file) -> None:
    body = client.post("/api/voices/analyze", files=_upload(wav_file)).json()
    assert body["ok"] is True and body["duration_sec"] == pytest.approx(6.0, abs=0.1)


def test_analyze_garbage_is_400(client) -> None:
    response = client.post("/api/voices/analyze", files={"file": ("x.wav", b"not audio" * 100, "audio/wav")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AUDIO_DECODE_FAILED"


def test_analyze_oversize_is_413_not_500(client, monkeypatch) -> None:
    import backend.api.routes.voices as routes

    def too_big(*_a, **_k):
        raise ValueError("Файл больше 100 MB.")

    monkeypatch.setattr(routes, "save_upload", too_big)
    response = client.post("/api/voices/analyze", files={"file": ("a.wav", b"x" * 10, "audio/wav")})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_clone_requires_consent_and_capable_model(client, wav_file) -> None:
    base = {"name": "Я", "model_id": "chatterbox-multilingual", "language": "ru"}
    refused = client.post("/api/voices/clone", data={**base, "consent": "false"}, files=_upload(wav_file))
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "VOICE_REJECTED"
    incompatible = client.post("/api/voices/clone", data={**base, "model_id": "piper", "consent": "true"}, files=_upload(wav_file))
    assert incompatible.status_code == 400 and incompatible.json()["error"]["code"] == "VOICE_INCOMPATIBLE"


def test_clone_lifecycle_and_cleanup(client, wav_file) -> None:
    before = _voice_dirs()
    created = client.post(
        "/api/voices/clone",
        data={"name": "  Тест  ", "model_id": "chatterbox-multilingual", "consent": "true", "reference_text": "привет"},
        files=_upload(wav_file),
    )
    assert created.status_code == 201, created.text
    voice = created.json()["voice"]
    assert voice["name"] == "Тест" and voice["kind"] == "cloned" and voice["has_reference"] is True
    assert client.get(f"/api/voices/{voice['id']}/reference").status_code == 200
    assert client.patch(f"/api/voices/{voice['id']}", json={"name": "Новое"}).json()["name"] == "Новое"

    # a cache row referencing the voice must not make deletion fail with an FK error
    with session_scope() as session:
        session.add(VoiceCache(voice_id=voice["id"], model_id="chatterbox-multilingual"))
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 200
    assert client.get(f"/api/voices/{voice['id']}").status_code == 404
    assert _voice_dirs() == before


def test_clone_rejects_short_reference_without_leaving_files(client, tmp_path) -> None:
    from tests.conftest import make_wav

    before = _voice_dirs()
    short = make_wav(tmp_path / "short.wav", seconds=2)
    response = client.post(
        "/api/voices/clone",
        data={"name": "x", "model_id": "chatterbox-multilingual", "consent": "true"},
        files=_upload(short),
    )
    assert response.status_code == 422
    assert _voice_dirs() == before


def test_clone_oversize_upload_leaves_no_orphan_folder(client, wav_file, monkeypatch) -> None:
    before = _voice_dirs()

    def explode(upload, target, max_mb=100):
        target.write_bytes(b"partial")
        raise ValueError("Файл больше 100 MB.")

    monkeypatch.setattr(voices_service, "save_upload", explode)
    response = client.post(
        "/api/voices/clone",
        data={"name": "x", "model_id": "chatterbox-multilingual", "consent": "true"},
        files=_upload(wav_file),
    )
    assert response.status_code in (413, 422)
    assert _voice_dirs() == before


def test_design_voice_validation(client) -> None:
    ok = client.post("/api/voices/design", json={"name": "Диктор", "description": "низкий голос", "model_id": "voxcpm2"})
    assert ok.status_code == 201 and ok.json()["voice"]["kind"] == "designed"
    assert client.post("/api/voices/design", json={"name": "x", "description": "  ", "model_id": "voxcpm2"}).status_code == 422
    assert client.post("/api/voices/design", json={"name": "x", "description": "d", "model_id": "piper"}).status_code == 400
    client.delete(f"/api/voices/{ok.json()['voice']['id']}")


def test_builtin_voices_are_protected(client) -> None:
    builtin = client.get("/api/voices", params={"kind": "builtin"}).json()[0]
    assert client.delete(f"/api/voices/{builtin['id']}").json()["error"]["code"] == "VOICE_PROTECTED"
    response = client.patch(f"/api/voices/{builtin['id']}", json={"name": "Hacked"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "VOICE_PROTECTED"
    assert client.get(f"/api/voices/{builtin['id']}").json()["name"] == builtin["name"]


def test_blank_voice_name_is_rejected(client) -> None:
    created = client.post("/api/voices/design", json={"name": "N", "description": "d", "model_id": "voxcpm2"}).json()["voice"]
    assert client.patch(f"/api/voices/{created['id']}", json={"name": "   "}).status_code == 422
    client.delete(f"/api/voices/{created['id']}")


def test_voice_filters_and_404(client) -> None:
    piper = client.get("/api/voices", params={"model_id": "piper"}).json()
    assert piper and all(v["model_id"] == "piper" for v in piper)
    assert all(v["language"] == "en" for v in client.get("/api/voices", params={"language": "en"}).json())
    assert client.get("/api/voices/missing").status_code == 404
    assert client.get("/api/voices/missing/reference").status_code == 404


def test_seed_builtin_voices_is_idempotent() -> None:
    def count() -> int:
        with session_scope() as session:
            return len(session.exec(select(Voice).where(Voice.kind == "builtin")).all())

    first = count()
    voices_service.seed_builtin_voices()
    assert count() == first == len(voices_service.BUILTIN)
