"""Weekly report generation routes."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_workspace_id
from app.models import (
    ReportTemplate,
    ReportTemplateCreate,
    ReportTemplateRead,
    Task,
    TaskHistory,
    TaskHistoryRead,
)
from sqlmodel import delete
from app.services.llm import generate_weekly_report, is_llm_configured

router = APIRouter(prefix="/api/reports", tags=["reports"])


# ── LLM Health Check ────────────────────────────────


@router.get("/llm-status")
async def llm_status():
    """Check whether the LLM API key is configured and reachable."""
    from app.config import LLM_CLIENT_KEY, LLM_ENDPOINT, LLM_MODEL_ID, LLM_PASS_KEY

    if not is_llm_configured():
        return {
            "configured": False,
            "reachable": False,
            "error": "LLM API 키가 설정되지 않았거나 유효하지 않습니다.",
        }

    # 설정값만 확인 (실제 API 호출 없음 — rate limit 보호)
    return {
        "configured": True,
        "reachable": True,
        "endpoint": LLM_ENDPOINT,
        "model_id": LLM_MODEL_ID,
    }


# ── Report Template CRUD ─────────────────────────


@router.get("/templates", response_model=list[ReportTemplateRead])
def list_templates(
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    query = select(ReportTemplate).order_by(ReportTemplate.updated_at.desc())
    if workspace_id:
        query = query.where(ReportTemplate.workspace_id == workspace_id)
    else:
        query = query.where(ReportTemplate.workspace_id.is_(None))
    return session.exec(query).all()


@router.post("/templates", response_model=ReportTemplateRead, status_code=201)
def create_template(
    data: ReportTemplateCreate,
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    # Upsert by name within workspace
    query = select(ReportTemplate).where(ReportTemplate.name == data.name)
    if workspace_id:
        query = query.where(ReportTemplate.workspace_id == workspace_id)
    else:
        query = query.where(ReportTemplate.workspace_id.is_(None))
    existing = session.exec(query).first()

    if existing:
        existing.content = data.content
        if data.system_prompt is not None:
            existing.system_prompt = data.system_prompt
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    template = ReportTemplate.model_validate(data)
    template.workspace_id = workspace_id
    template.created_at = datetime.utcnow()
    template.updated_at = datetime.utcnow()
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int, session: Session = Depends(get_session)):
    template = session.get(ReportTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    session.delete(template)
    session.commit()


# ── Task History ─────────────────────────────────


@router.get("/history", response_model=list[TaskHistoryRead])
def list_history(
    days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    since = datetime.utcnow() - timedelta(days=days)
    query = (
        select(TaskHistory)
        .where(TaskHistory.created_at >= since)
        .order_by(TaskHistory.created_at.desc())
    )
    if workspace_id:
        query = query.where(TaskHistory.workspace_id == workspace_id)
    else:
        query = query.where(TaskHistory.workspace_id.is_(None))
    return session.exec(query).all()


# ── Clear History ────────────────────────────────


@router.delete("/history", status_code=204)
def clear_history(
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    """Delete task change history records for a workspace."""
    if workspace_id:
        histories = session.exec(
            select(TaskHistory).where(TaskHistory.workspace_id == workspace_id)
        ).all()
        for h in histories:
            session.delete(h)
    else:
        session.exec(delete(TaskHistory).where(TaskHistory.workspace_id.is_(None)))
    session.commit()


# ── Generate Report ──────────────────────────────


@router.post("/generate")
async def generate_report(
    template_id: Optional[int] = None,
    days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    if not is_llm_configured():
        raise HTTPException(
            status_code=503,
            detail="LLM API가 설정되지 않았습니다. 환경변수 TASK_LLM_CLIENT_KEY, TASK_LLM_PASS_KEY를 설정하세요.",
        )

    # Get template
    if template_id:
        template = session.get(ReportTemplate, template_id)
    else:
        query = select(ReportTemplate).order_by(ReportTemplate.updated_at.desc())
        if workspace_id:
            query = query.where(ReportTemplate.workspace_id == workspace_id)
        else:
            query = query.where(ReportTemplate.workspace_id.is_(None))
        template = session.exec(query).first()

    if not template:
        raise HTTPException(
            status_code=400,
            detail="예시 주간보고서 템플릿이 없습니다. 먼저 템플릿을 등록해주세요.",
        )

    # Get task changes
    since = datetime.utcnow() - timedelta(days=days)
    history_query = (
        select(TaskHistory)
        .where(TaskHistory.created_at >= since)
        .order_by(TaskHistory.created_at)
    )
    if workspace_id:
        history_query = history_query.where(TaskHistory.workspace_id == workspace_id)
    else:
        history_query = history_query.where(TaskHistory.workspace_id.is_(None))
    histories = session.exec(history_query).all()

    if not histories:
        raise HTTPException(
            status_code=400,
            detail=f"최근 {days}일간 태스크 변동사항이 없습니다.",
        )

    # Build changes summary — include task description for richer reports
    task_ids = list({h.task_id for h in histories})
    task_map = {}
    for tid in task_ids:
        t = session.get(Task, tid)
        if t:
            task_map[tid] = t

    task_changes = [
        {
            "task": h.task_title,
            "description": (task_map[h.task_id].description or "") if h.task_id in task_map else "",
            "field": h.field_name,
            "from": h.old_value,
            "to": h.new_value,
            "date": h.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for h in histories
    ]

    end_date = datetime.utcnow()
    start_date = since
    period_label = f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"

    try:
        report_text = await generate_weekly_report(
            task_changes=task_changes,
            example_report=template.content,
            period_label=period_label,
            system_prompt=template.system_prompt,
        )
    except Exception as e:
        detail = str(e)
        if isinstance(e, UnicodeEncodeError):
            detail = "API 키에 유효하지 않은 문자가 포함되어 있습니다. .env 파일에서 실제 API 키를 입력하세요."
        raise HTTPException(status_code=502, detail=detail)

    return {"report": report_text, "period": period_label, "changes_count": len(task_changes)}
