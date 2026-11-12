import pytest

from backend.services.resource_manager import resources


@pytest.fixture(autouse=True)
def _restore_settings(client):
    yield
    client.put("/api/settings", json={
        "resource_mode": "parallel", "conflict_policy": "ask", "reserve_vram_gb": 0.8,
        "reserve_ram_gb": 3.0, "idle_unload_seconds": 600,
    })


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("reserve_vram_gb", "abc"),
        ("reserve_vram_gb", -1),
        ("reserve_ram_gb", None),
        ("resource_mode", "bogus"),
        ("conflict_policy", "maybe"),
        ("idle_unload_seconds", "soon"),
        ("idle_unload_seconds", -10),
    ],
)
def test_invalid_settings_are_rejected_and_not_persisted(client, key, value) -> None:
    before = client.get("/api/settings").json()["values"][key]
    response = client.put("/api/settings", json={key: value})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "SETTINGS_INVALID"
    assert client.get("/api/settings").json()["values"][key] == before


def test_valid_settings_roundtrip_and_apply_to_runtime(client) -> None:
    response = client.put("/api/settings", json={"reserve_vram_gb": 1.5, "idle_unload_seconds": "120", "unknown_key": 1})
    assert response.status_code == 200
    values = response.json()["values"]
    assert values["reserve_vram_gb"] == 1.5
    assert "unknown_key" not in values
    assert resources.status()["reserve_vram_gb"] == 1.5
    assert resources.status()["idle_unload_seconds"] == 120


def test_resource_mode_endpoint_is_persistent(client) -> None:
    assert client.put("/api/resources/mode", json={"mode": "economy"}).status_code == 200
    # The idle watcher calls refresh_settings() every 15 s; the mode must survive that.
    resources.refresh_settings()
    assert resources.mode == "economy"
    assert client.get("/api/settings").json()["values"]["resource_mode"] == "economy"
    assert client.put("/api/resources/mode", json={"mode": "nope"}).status_code == 400


def test_refresh_settings_survives_corrupt_rows(client) -> None:
    """Legacy/corrupt rows must not kill the idle watcher loop."""
    from backend.db.models import AppSetting
    from backend.db.session import session_scope

    with session_scope() as session:
        session.merge(AppSetting(key="reserve_vram_gb", value={"value": "abc"}))
    session_ok = False
    try:
        resources.refresh_settings()
        session_ok = True
    finally:
        with session_scope() as session:
            session.merge(AppSetting(key="reserve_vram_gb", value={"value": 0.8}))
    assert session_ok
    assert isinstance(resources.status()["reserve_vram_gb"], float)


def test_profiles_crud_and_default_exclusivity(client) -> None:
    first = client.post("/api/settings/profiles", json={"name": "a", "model_id": "piper", "is_default": True}).json()
    second = client.post("/api/settings/profiles", json={"name": "b", "model_id": "piper", "is_default": True}).json()
    profiles = {p["id"]: p for p in client.get("/api/settings").json()["profiles"]}
    assert profiles[first["id"]]["is_default"] is False
    assert profiles[second["id"]]["is_default"] is True

    patched = client.patch(f"/api/settings/profiles/{first['id']}", json={"is_default": True}).json()
    assert patched["is_default"] is True
    profiles = {p["id"]: p for p in client.get("/api/settings").json()["profiles"]}
    assert profiles[second["id"]]["is_default"] is False

    assert client.delete(f"/api/settings/profiles/{first['id']}").json() == {"deleted": True}
    assert client.delete(f"/api/settings/profiles/{first['id']}").status_code == 404
    assert client.patch("/api/settings/profiles/missing", json={"name": "x"}).status_code == 404
    client.delete(f"/api/settings/profiles/{second['id']}")


def test_global_default_profiles_are_exclusive(client) -> None:
    a = client.post("/api/settings/profiles", json={"name": "ga", "is_default": True}).json()
    b = client.post("/api/settings/profiles", json={"name": "gb", "is_default": True}).json()
    profiles = {p["id"]: p for p in client.get("/api/settings").json()["profiles"]}
    assert [p["is_default"] for p in (profiles[a["id"]], profiles[b["id"]])] == [False, True]
    for item in (a, b):
        client.delete(f"/api/settings/profiles/{item['id']}")
