"""Task CRUD routes."""

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import UPLOAD_DIR
from app.database import get_session
from app.deps import get_user_id, get_workspace_id
from app.models import (
    Notification,
    NotificationType,
    Task,
    TaskCreate,
    TaskHistory,
    TaskRead,
    TaskStatusUpdate,
    TaskUpdate,
    User,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _record_history(
    session: Session,
    task: Task,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    changed_by_id: int | None = None,
):
    """Record a task change for weekly report generation."""
    history = TaskHistory(
        task_id=task.id,
        task_title=task.title,
        field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        changed_by_id=changed_by_id,
        workspace_id=task.workspace_id,
    )
    session.add(history)


def _notify_assignment(session: Session, task: Task, changed_by: str | None = None):
    """Create notification when a task is assigned."""
    if not task.assignee_id:
        return
    msg = f'"{task.title}" 태스크가 당신에게 배정되었습니다.'
    notification = Notification(
        user_id=task.assignee_id,
        task_id=task.id,
        type=NotificationType.ASSIGNMENT,
        message=msg,
    )
    session.add(notification)


def _notify_status_change(session: Session, task: Task, old_status: str, new_status: str):
    """Create notification when task status changes."""
    if not task.assignee_id:
        return
    msg = f'"{task.title}" 상태 변경: {old_status} → {new_status}'
    notification = Notification(
        user_id=task.assignee_id,
        task_id=task.id,
        type=NotificationType.STATUS_CHANGE,
        message=msg,
    )
    session.add(notification)


@router.get("", response_model=list[TaskRead])
def list_tasks(
    status: str | None = None,
    assignee_id: int | None = None,
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    query = select(Task).where(Task.archived == False)
    if workspace_id:
        query = query.where(Task.workspace_id == workspace_id)
    else:
        query = query.where(Task.workspace_id.is_(None))
    if status:
        query = query.where(Task.status == status)
    if assignee_id:
        query = query.where(Task.assignee_id == assignee_id)
    query = query.order_by(Task.sort_order, Task.created_at.desc())
    return session.exec(query).all()


@router.post("", response_model=TaskRead, status_code=201)
def create_task(
    data: TaskCreate,
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
    user_id: int | None = Depends(get_user_id),
):
    task = Task.model_validate(data)
    task.workspace_id = workspace_id
    task.created_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    _record_history(session, task, "created", None, task.status, changed_by_id=user_id)
    if task.assignee_id:
        _notify_assignment(session, task)
    session.commit()
    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    data: TaskUpdate,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Capture old values for history tracking
    tracked_fields = {"title", "description", "status", "priority", "assignee_id", "due_date", "tags"}
    old_values = {f: getattr(task, f) for f in tracked_fields}
    old_status = task.status
    old_assignee = task.assignee_id
    update_data = data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(task, key, value)
    task.updated_at = datetime.utcnow()

    # Notifications
    if "assignee_id" in update_data and update_data["assignee_id"] != old_assignee:
        _notify_assignment(session, task)
    if "status" in update_data and update_data["status"] != old_status:
        _notify_status_change(session, task, old_status, update_data["status"])

    # Record history for changed fields
    for field in tracked_fields:
        if field in update_data and str(old_values[field]) != str(update_data[field]):
            _record_history(
                session, task, field, old_values[field], update_data[field],
                changed_by_id=user_id,
            )

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.patch("/{task_id}/status", response_model=TaskRead)
def update_task_status(
    task_id: int,
    data: TaskStatusUpdate,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    old_status = task.status
    task.status = data.status
    task.sort_order = data.sort_order
    task.updated_at = datetime.utcnow()

    if old_status != data.status:
        _notify_status_change(session, task, old_status, data.status)
        _record_history(session, task, "status", old_status, data.status, changed_by_id=user_id)

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Record deletion history before deleting
    _record_history(session, task, "deleted", task.status, None, changed_by_id=user_id)
    # Clean up image file if exists
    if task.image_path:
        img_file = UPLOAD_DIR / Path(task.image_path).name
        if img_file.exists():
            img_file.unlink()
    session.delete(task)
    session.commit()


@router.post("/{task_id}/image", response_model=TaskRead)
async def upload_task_image(
    task_id: int,
    file: UploadFile,
    session: Session = Depends(get_session),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Validate file type
    allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    ext = Path(file.filename or "file.png").suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"File type {ext} not allowed")

    # Save file with unique name
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = UPLOAD_DIR / filename
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(filepath, "wb") as f:
        content = await file.read()
        await f.write(content)

    # Delete old image if exists
    if task.image_path:
        old_file = UPLOAD_DIR / Path(task.image_path).name
        if old_file.exists():
            old_file.unlink()

    task.image_path = f"/uploads/{filename}"
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


# ── Archive ────────────────────────────────────────


@router.post("/{task_id}/archive", response_model=TaskRead)
def archive_task(
    task_id: int,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.archived:
        return task
    task.archived = True
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.post("/{task_id}/unarchive", response_model=TaskRead)
def unarchive_task(
    task_id: int,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.archived:
        return task
    task.archived = False
    task.updated_at = datetime.utcnow()
    _record_history(session, task, "unarchived", "true", "false", changed_by_id=user_id)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.get("/archived/search", response_model=list[TaskRead])
def search_archived_tasks(
    keyword: str | None = None,
    assignee_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    query = select(Task).where(Task.archived == True)
    if workspace_id:
        query = query.where(Task.workspace_id == workspace_id)
    else:
        query = query.where(Task.workspace_id.is_(None))
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            (Task.title.ilike(pattern)) | (Task.description.ilike(pattern))
        )
    if assignee_id:
        query = query.where(Task.assignee_id == assignee_id)
    if date_from:
        query = query.where(Task.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        to_dt = datetime.fromisoformat(date_to) + timedelta(days=1)
        query = query.where(Task.created_at < to_dt)
    query = query.order_by(Task.updated_at.desc())
    return session.exec(query).all()


@router.get("/archived/count")
def archived_task_count(
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    query = select(Task).where(Task.archived == True)
    if workspace_id:
        query = query.where(Task.workspace_id == workspace_id)
    else:
        query = query.where(Task.workspace_id.is_(None))
    count = len(session.exec(query).all())
    return {"count": count}


# ── AI Task Generation ────────────────────────────


DEFAULT_TASK_GEN_PROMPT = (
    "당신은 프로젝트 매니저 어시스턴트입니다. 사용자가 입력한 목표/과업을 팀원들이 바로 착수할 수 있는 작은 단위의 일감으로 분해해주세요.\n\n"
    "규칙:\n"
    "1. 반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트나 마크다운을 포함하지 마세요.\n"
    "2. 각 일감은 독립적으로 수행 가능한 단위여야 합니다.\n"
    "3. 제목은 구체적이고 행동 중심(동사로 시작)으로 작성하세요.\n"
    "4. 설명은 1-2문장으로 무엇을 해야 하는지, 왜 필요한지 간결하게 적으세요.\n"
    "5. 우선순위는 HIGH, MEDIUM, LOW 중 하나를 선택하세요.\n"
    "6. 일감 수는 목표 규모에 맞게 5~15개 사이로 생성하세요.\n\n"
    '응답 형식:\n'
    '[{"title": "일감 제목", "description": "일감 설명", "priority": "MEDIUM"}, ...]'
)


class TaskGenerateRequest(BaseModel):
    goal: str
    system_prompt: str | None = None
    reject_items: list[dict] | None = None


@router.post("/generate")
async def generate_tasks(data: TaskGenerateRequest):
    from app.services.llm import chat_completion, is_llm_configured

    if not is_llm_configured():
        raise HTTPException(
            status_code=503,
            detail="LLM API가 설정되지 않았습니다. 환경변수 TASK_LLM_* 을 설정하세요.",
        )

    system_prompt = data.system_prompt or DEFAULT_TASK_GEN_PROMPT

    user_content = f"## 목표\n{data.goal}"
    if data.reject_items:
        reject_text = json.dumps(data.reject_items, ensure_ascii=False)
        user_content += (
            f"\n\n## 제외할 항목 (이 일감들은 적절하지 않으므로 대체 일감을 생성하세요)\n{reject_text}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        raw = await chat_completion(messages, temperature=0.7, max_tokens=4096)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Extract JSON array from response
    try:
        start = raw.index("[")
        end = raw.rindex("]") + 1
        items = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(
            status_code=502,
            detail=f"LLM 응답을 파싱할 수 없습니다. 시스템 프롬프트에서 JSON 형식을 요구하세요.\n\n응답:\n{raw[:500]}",
        )

    valid = []
    for item in items:
        if isinstance(item, dict) and "title" in item:
            valid.append({
                "title": str(item["title"]),
                "description": str(item.get("description", "")),
                "priority": str(item.get("priority", "MEDIUM")).upper(),
            })

    return {"items": valid}
