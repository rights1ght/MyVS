from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, field_validator
from sqlmodel import select

from backend.api.errors import AppError
from backend.db.models import Project, TaskRecord
from backend.db.session import session_scope

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectPayload(BaseModel):
    name: str
    description: str = ""
    color: str = "#f5b942"

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


@router.get("")
def list_projects() -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.exec(select(Project).order_by(Project.created_at)).all()
    return [row.model_dump() | {"created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()} for row in rows]


@router.post("", status_code=201)
def create_project(payload: ProjectPayload) -> dict[str, Any]:
    with session_scope() as session:
        project = Project(**payload.model_dump())
        session.add(project)
        session.flush()
        session.refresh(project)
        return project.model_dump() | {"created_at": project.created_at.isoformat(), "updated_at": project.updated_at.isoformat()}


@router.patch("/{project_id}")
def update_project(project_id: str, payload: ProjectPayload) -> dict[str, Any]:
    with session_scope() as session:
        project = session.get(Project, project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Проект не найден.", 404)
        project.name = payload.name
        project.description = payload.description
        project.color = payload.color
        project.updated_at = datetime.now(timezone.utc)
        session.add(project)
        return project.model_dump() | {"created_at": project.created_at.isoformat(), "updated_at": project.updated_at.isoformat()}


@router.delete("/{project_id}")
def delete_project(project_id: str) -> dict[str, bool]:
    with session_scope() as session:
        project = session.get(Project, project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Проект не найден.", 404)
        if len(session.exec(select(Project.id)).all()) <= 1:
            raise AppError("PROJECT_PROTECTED", "Нельзя удалить последний проект.", 400)
        # Keep task history; move it out of the project before deleting.
        for task in session.exec(select(TaskRecord).where(TaskRecord.project_id == project_id)).all():
            task.project_id = None
            session.add(task)
        session.delete(project)
    return {"deleted": True}
