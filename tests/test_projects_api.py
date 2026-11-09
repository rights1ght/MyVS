from backend.db.models import TaskRecord
from backend.db.session import session_scope


def _create(client, name="Проект"):
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def test_project_crud(client) -> None:
    project = _create(client, "Книга")
    assert any(p["id"] == project["id"] for p in client.get("/api/projects").json())
    updated = client.patch(f"/api/projects/{project['id']}", json={"name": "Книга 2", "color": "#fff"}).json()
    assert updated["name"] == "Книга 2" and updated["color"] == "#fff"
    assert client.delete(f"/api/projects/{project['id']}").json() == {"deleted": True}
    assert client.delete(f"/api/projects/{project['id']}").status_code == 404
    assert client.patch("/api/projects/missing", json={"name": "x"}).status_code == 404


def test_blank_project_name_is_rejected(client) -> None:
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422
    project = _create(client)
    assert client.patch(f"/api/projects/{project['id']}", json={"name": " "}).status_code == 422
    client.delete(f"/api/projects/{project['id']}")


def test_deleting_project_keeps_task_history(client) -> None:
    project = _create(client)
    with session_scope() as session:
        task = TaskRecord(type="tts", status="completed", project_id=project["id"])
        session.add(task)
        session.flush()
        task_id = task.id
    client.delete(f"/api/projects/{project['id']}")
    assert client.get(f"/api/tasks/{task_id}").json()["project_id"] is None


def test_last_project_cannot_be_deleted(client) -> None:
    projects = client.get("/api/projects").json()
    for item in projects[1:]:
        assert client.delete(f"/api/projects/{item['id']}").status_code == 200
    survivor = client.get("/api/projects").json()
    assert len(survivor) == 1
    response = client.delete(f"/api/projects/{survivor[0]['id']}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROJECT_PROTECTED"
