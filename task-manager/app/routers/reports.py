"""Weekly report generation routes."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    ReportTemplate,
    ReportTemplateCreate,
    ReportTemplateRead,
    TaskHistory,
    TaskHistoryRead,
)
from app.services.llm import generate_weekly_report, is_llm_configured

router = APIRouter(prefix="/api/reports", tags=["reports"])


# ── Report Template CRUD ─────────────────────────


@router.get("/templates", response_model=list[ReportTemplateRead])
def list_templates(session: Session = Depends(get_session)):
    return session.exec(select(ReportTemplate).order_by(ReportTemplate.updated_at.desc())).all()


@router.post("/templates", response_model=ReportTemplateRead, status_code=201)
def create_template(data: ReportTemplateCreate, session: Session = Depends(get_session)):
    # Upsert by name
    existing = session.exec(
        select(ReportTemplate).where(ReportTemplate.name == data.name)
    ).first()
    if existing:
        existing.content = data.content
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    template = ReportTemplate.model_validate(data)
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
):
    since = datetime.utcnow() - timedelta(days=days)
    return session.exec(
        select(TaskHistory)
        .where(TaskHistory.created_at >= since)
        .order_by(TaskHistory.created_at.desc())
    ).all()


# ── Generate Report ──────────────────────────────


@router.post("/generate")
async def generate_report(
    template_id: Optional[int] = None,
    days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_session),
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
        template = session.exec(
            select(ReportTemplate).order_by(ReportTemplate.updated_at.desc())
        ).first()

    if not template:
        raise HTTPException(
            status_code=400,
            detail="예시 주간보고서 템플릿이 없습니다. 먼저 템플릿을 등록해주세요.",
        )

    # Get task changes
    since = datetime.utcnow() - timedelta(days=days)
    histories = session.exec(
        select(TaskHistory)
        .where(TaskHistory.created_at >= since)
        .order_by(TaskHistory.created_at)
    ).all()

    if not histories:
        raise HTTPException(
            status_code=400,
            detail=f"최근 {days}일간 태스크 변동사항이 없습니다.",
        )

    # Build changes summary
    task_changes = [
        {
            "task": h.task_title,
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
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {"report": report_text, "period": period_label, "changes_count": len(task_changes)}
