from __future__ import annotations

from fastapi import APIRouter
from sqlmodel import desc, select

from backend.api.errors import AppError
from backend.api.schemas import MonitorSnapshot
from backend.db.models import ResourceAlert
from backend.db.session import session_scope
from backend.services.monitor import monitor

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/snapshot", response_model=MonitorSnapshot)
def snapshot() -> MonitorSnapshot:
    return MonitorSnapshot(**monitor.snapshot())


@router.get("/history", response_model=list[MonitorSnapshot])
def history(seconds: int = 300, after: int | None = None) -> list[MonitorSnapshot]:
    return [MonitorSnapshot(**item) for item in monitor.get_history(seconds, after)]


@router.get("/alerts")
def alerts(limit: int = 50) -> list[dict[str, object]]:
    limit = max(1, min(limit, 200))
    with session_scope() as session:
        rows = session.exec(select(ResourceAlert).order_by(desc(ResourceAlert.ts)).limit(limit)).all()
    return [
        {
            "id": row.id,
            "ts": row.ts.isoformat(),
            "severity": row.severity,
            "metric": row.metric,
            "value": row.value,
            "threshold": row.threshold,
            "model_id": row.model_id,
            "task_id": row.task_id,
            "message": row.message,
            "acknowledged": row.acknowledged,
        }
        for row in rows
    ]


@router.post("/alerts/{alert_id}/ack")
def acknowledge(alert_id: str) -> dict[str, bool]:
    with session_scope() as session:
        row = session.get(ResourceAlert, alert_id)
        if not row:
            raise AppError("ALERT_NOT_FOUND", "Предупреждение не найдено.", 404)
        row.acknowledged = True
        session.add(row)
    return {"ok": True}
