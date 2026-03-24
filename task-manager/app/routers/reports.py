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


# ── LLM Health Check ────────────────────────────


@router.get("/llm-status")
async def llm_status():
    """Check whether the LLM API key is configured and reachable."""
    import httpx

    from app.config import LLM_CLIENT_KEY, LLM_ENDPOINT, LLM_MODEL_ID, LLM_PASS_KEY

    if not is_llm_configured():
        return {
            "configured": False,
            "reachable": False,
            "error": "LLM API 키가 설정되지 않았거나 유효하지 않습니다. .env 파일에서 TASK_LLM_CLIENT_KEY, TASK_LLM_PASS_KEY, TASK_LLM_MODEL_ID를 확인하세요.",
            "debug": {
                "endpoint": LLM_ENDPOINT,
                "client_key_set": bool(LLM_CLIENT_KEY),
                "pass_key_set": bool(LLM_PASS_KEY),
                "model_id_set": bool(LLM_MODEL_ID),
            },
        }

    headers = {
        "x-fabrix-client": LLM_CLIENT_KEY,
        "x-openapi-token": LLM_PASS_KEY,
        "x-llm-model-id": LLM_MODEL_ID,
        "Content-Type": "application/json",
    }
    payload = {
        "model": "/mnt/models",
        "messages": [{"role": "user", "content": "Hello, respond with OK."}],
        "max_tokens": 16,
    }

    # Probe: GET on base endpoint, /v1/models, and POST on root
    probes = [
        ("GET", LLM_ENDPOINT, None),
        ("GET", f"{LLM_ENDPOINT}/v1/models", None),
        ("GET", f"{LLM_ENDPOINT}/models", None),
        ("POST", LLM_ENDPOINT, payload),
        ("GET", LLM_ENDPOINT.rsplit("/", 1)[0], None),  # parent path
    ]

    results = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for method, url, body in probes:
                try:
                    if method == "GET":
                        resp = await client.get(url, headers=headers)
                    else:
                        resp = await client.post(url, headers=headers, json=body)
                    results.append({
                        "method": method,
                        "url": url,
                        "status_code": resp.status_code,
                        "response_body": resp.text[:500],
                    })
                except Exception as e:
                    results.append({
                        "method": method,
                        "url": url,
                        "error": f"{type(e).__name__}: {e}",
                    })
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)}

    return {
        "configured": True,
        "endpoint": LLM_ENDPOINT,
        "model_id": LLM_MODEL_ID,
        "results": results,
    }


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
    except (RuntimeError, UnicodeEncodeError) as e:
        detail = str(e)
        if isinstance(e, UnicodeEncodeError):
            detail = "API 키에 유효하지 않은 문자가 포함되어 있습니다. .env 파일에서 실제 API 키를 입력하세요."
        raise HTTPException(status_code=502, detail=detail)

    return {"report": report_text, "period": period_label, "changes_count": len(task_changes)}
