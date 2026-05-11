"""Workspace management routes."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    BoardColumn,
    Comment,
    ReportTemplate,
    Task,
    TaskHistory,
    User,
    Workspace,
    WorkspaceCreate,
    WorkspaceMember,
    WorkspacePasswordSet,
    WorkspacePasswordVerify,
    WorkspaceRead,
)


# ── Password helpers ────────────────────────────────

_PBKDF2_ITERATIONS = 120_000


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def _verify_password(password: str, stored: str | None) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, hex_hash = stored.split("$", 1)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return secrets.compare_digest(digest.hex(), hex_hash)


def _to_read(workspace: Workspace) -> WorkspaceRead:
    return WorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        owner_id=workspace.owner_id,
        created_at=workspace.created_at,
        has_password=bool(workspace.password_hash),
    )

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceRead])
def list_workspaces(
    user_id: int | None = None,
    session: Session = Depends(get_session),
):
    """List workspaces. If user_id is given, only return workspaces the user belongs to."""
    if user_id:
        query = (
            select(Workspace)
            .join(WorkspaceMember)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.name)
        )
    else:
        query = select(Workspace).order_by(Workspace.name)
    return [_to_read(w) for w in session.exec(query).all()]


_ONBOARDING_TASKS = [
    {
        "title": "일감 생성하기",
        "description": (
            "이 화면이 바로 칸반 보드입니다. 각 컬럼은 일감의 상태를 나타냅니다.\n\n"
            "• TODO — 아직 시작하지 않은 일\n"
            "• IN PROGRESS — 지금 진행 중인 일\n"
            "• REVIEW — 동료의 검토를 기다리는 일\n"
            "• DONE — 완료된 일\n"
            "• ARCHIVE — 더 이상 보드에 두지 않을 보관된 일\n\n"
            "+ Add Task 버튼으로 새 일감을 만들 수 있고, 댓글에서 @닉네임으로 멘션하면 "
            "상단의 🔔 알림으로 전달돼요. 개인 일정 관리부터 팀 협업까지 모두 가능합니다.\n\n"
            "👉 다음 안내를 따라 직접 일감을 한 번 만들어보세요."
        ),
    },
    {
        "title": "일감 아카이브 해보기",
        "description": (
            "끝난 일감은 ARCHIVE로 옮겨 보드를 깔끔하게 유지하세요.\n\n"
            "방법은 두 가지입니다.\n"
            "1) 카드를 우측 ARCHIVE 영역으로 드래그\n"
            "2) 일감을 열고 'Archive' 버튼 클릭\n\n"
            "보관된 일감은 ARCHIVE 카드의 'Browse Archived'에서 언제든 다시 볼 수 있어요."
        ),
    },
    {
        "title": "AI에게 주간보고 요청하기",
        "description": (
            "상단 'Weekly Report' 버튼을 누르면 LLM이 일주일 동안의 일감 변동, 댓글, "
            "상태 변화를 종합해 자동으로 주간보고서를 작성해 줍니다.\n\n"
            "• System Prompt — 보고서의 톤과 규칙을 정의 (예: '경어체로 작성하라')\n"
            "• Example Report Template — Few-shot 예시. 실제 우리 팀의 주간보고 형식을 "
            "한 번 붙여넣으면 LLM이 그 형식을 따라 새 내용을 작성합니다.\n\n"
            "두 입력만 잘 채워두면 매주 한 번의 클릭으로 보고서가 완성돼요."
        ),
    },
    {
        "title": "Task Generator 사용하기 (퀴즈)",
        "description": (
            "Task Generator는 큰 목표를 LLM으로 잘게 나눠 여러 개의 일감으로 만들어주는 "
            "이스터에그 기능입니다. 어디에 숨어있을까요? 🤔\n\n"
            "👉 다음 안내에서 3지선다 퀴즈로 직접 찾아보세요."
        ),
    },
]


def _seed_onboarding_tasks(session: Session, workspace_id: int) -> None:
    """Seed the four onboarding tasks into a workspace's TODO column."""
    now = datetime.utcnow()
    for idx, item in enumerate(_ONBOARDING_TASKS):
        task = Task(
            title=item["title"],
            description=item["description"],
            status="TODO",
            priority="MEDIUM",
            tags=json.dumps(["onboarding"], ensure_ascii=False),
            sort_order=idx,
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )
        session.add(task)


@router.post("", response_model=WorkspaceRead, status_code=201)
def create_workspace(
    data: WorkspaceCreate,
    owner_id: int | None = None,
    session: Session = Depends(get_session),
):
    workspace = Workspace(
        name=data.name,
        description=data.description,
        owner_id=owner_id or 0,
        created_at=datetime.utcnow(),
    )
    session.add(workspace)
    session.commit()
    session.refresh(workspace)

    # Add owner as member
    if owner_id:
        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner_id,
        )
        session.add(member)

    # Create default columns for this workspace
    defaults = [
        BoardColumn(name="TODO", sort_order=0, color="#6B7280", workspace_id=workspace.id),
        BoardColumn(name="IN_PROGRESS", sort_order=1, color="#3B82F6", workspace_id=workspace.id),
        BoardColumn(name="REVIEW", sort_order=2, color="#F59E0B", workspace_id=workspace.id),
        BoardColumn(name="DONE", sort_order=3, color="#10B981", workspace_id=workspace.id),
    ]
    for col in defaults:
        session.add(col)

    # Seed onboarding tasks for first-time users only.
    # A user is considered "first-time" if they have not yet completed onboarding
    # AND this is their very first workspace membership.
    if owner_id:
        owner = session.get(User, owner_id)
        if owner and owner.onboarded_at is None:
            other_memberships = session.exec(
                select(WorkspaceMember)
                .where(WorkspaceMember.user_id == owner_id)
                .where(WorkspaceMember.workspace_id != workspace.id)
            ).first()
            if not other_memberships:
                _seed_onboarding_tasks(session, workspace.id)

    session.commit()
    session.refresh(workspace)
    return _to_read(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(workspace_id: int, session: Session = Depends(get_session)):
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return _to_read(workspace)


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: int,
    confirm_name: str | None = None,
    session: Session = Depends(get_session),
):
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if confirm_name != workspace.name:
        raise HTTPException(
            status_code=400,
            detail="워크스페이스 이름이 일치하지 않습니다. 삭제를 확인하려면 정확한 이름을 입력하세요.",
        )

    # Cascade delete all workspace data
    # 1. Comments on workspace tasks
    ws_tasks = session.exec(select(Task).where(Task.workspace_id == workspace_id)).all()
    for t in ws_tasks:
        comments = session.exec(select(Comment).where(Comment.task_id == t.id)).all()
        for c in comments:
            session.delete(c)

    # 2. Tasks
    for t in ws_tasks:
        session.delete(t)

    # 3. Task history
    histories = session.exec(
        select(TaskHistory).where(TaskHistory.workspace_id == workspace_id)
    ).all()
    for h in histories:
        session.delete(h)

    # 4. Report templates
    templates = session.exec(
        select(ReportTemplate).where(ReportTemplate.workspace_id == workspace_id)
    ).all()
    for tmpl in templates:
        session.delete(tmpl)

    # 5. Board columns
    cols = session.exec(
        select(BoardColumn).where(BoardColumn.workspace_id == workspace_id)
    ).all()
    for col in cols:
        session.delete(col)

    # 6. Members
    members = session.exec(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    ).all()
    for m in members:
        session.delete(m)

    # 7. Workspace itself
    session.delete(workspace)
    session.commit()


@router.post("/{workspace_id}/join")
def join_workspace(
    workspace_id: int,
    user_id: int,
    password: str | None = None,
    session: Session = Depends(get_session),
):
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if workspace.password_hash:
        if not password or not _verify_password(password, workspace.password_hash):
            raise HTTPException(
                status_code=401,
                detail="워크스페이스 비밀번호가 일치하지 않습니다.",
            )

    existing = session.exec(
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .where(WorkspaceMember.user_id == user_id)
    ).first()
    if existing:
        return {"ok": True, "message": "Already a member"}

    member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id)
    session.add(member)
    session.commit()
    return {"ok": True, "message": "Joined workspace"}


# ── Workspace Password Management ───────────────────


@router.post("/{workspace_id}/verify-password")
def verify_workspace_password(
    workspace_id: int,
    data: WorkspacePasswordVerify,
    session: Session = Depends(get_session),
):
    """Verify a workspace password. Used to unlock a protected workspace."""
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not workspace.password_hash:
        return {"ok": True, "has_password": False}

    if not _verify_password(data.password, workspace.password_hash):
        raise HTTPException(
            status_code=401,
            detail="비밀번호가 일치하지 않습니다.",
        )
    return {"ok": True, "has_password": True}


@router.put("/{workspace_id}/password")
def set_workspace_password(
    workspace_id: int,
    data: WorkspacePasswordSet,
    session: Session = Depends(get_session),
):
    """Set, change, or clear a workspace password.

    - If a password is already set, ``current_password`` must match.
    - Pass an empty/None ``new_password`` to clear the password.
    """
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if workspace.password_hash:
        if not data.current_password or not _verify_password(
            data.current_password, workspace.password_hash
        ):
            raise HTTPException(
                status_code=401,
                detail="현재 비밀번호가 올바르지 않습니다.",
            )

    new_pw = (data.new_password or "").strip()
    if new_pw:
        if len(new_pw) < 4:
            raise HTTPException(
                status_code=400,
                detail="비밀번호는 최소 4자 이상이어야 합니다.",
            )
        workspace.password_hash = _hash_password(new_pw)
        message = "워크스페이스 비밀번호가 설정되었습니다."
    else:
        workspace.password_hash = None
        message = "워크스페이스 비밀번호가 해제되었습니다."

    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    return {
        "ok": True,
        "message": message,
        "has_password": bool(workspace.password_hash),
    }


# ── Backup: Markdown Export ─────────────────────────


@router.get("/{workspace_id}/backup")
def export_workspace_backup(
    workspace_id: int,
    session: Session = Depends(get_session),
):
    """Export workspace data as a Markdown file.

    The backup includes:
    - Workspace metadata
    - All tasks grouped by status (daily snapshot)
    - Daily changelog from TaskHistory (unlimited — all history stored in DB)
    - Report templates
    - Members list

    Data retention: TaskHistory records are never auto-deleted, so the changelog
    covers the entire lifetime of the workspace. The only limit is explicit user
    deletion via "Clear History". Typically this means weeks to months of change
    records depending on team activity.
    """
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    now = datetime.utcnow()
    lines = []

    # Header
    lines.append(f"# {workspace.name} - Workspace Backup")
    lines.append(f"")
    lines.append(f"Exported: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    if workspace.description:
        lines.append(f"Description: {workspace.description}")
    lines.append(f"")

    # Members
    members = session.exec(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    ).all()
    lines.append(f"## Members")
    lines.append(f"")
    for m in members:
        user = session.get(User, m.user_id)
        if user:
            email_part = f" ({user.email})" if user.email else ""
            lines.append(f"- {user.nickname}{email_part}")
    lines.append(f"")

    # Columns
    ws_columns = session.exec(
        select(BoardColumn)
        .where(BoardColumn.workspace_id == workspace_id)
        .order_by(BoardColumn.sort_order)
    ).all()

    # Tasks grouped by status (daily snapshot)
    lines.append(f"## Tasks (Current Snapshot)")
    lines.append(f"")
    ws_tasks = session.exec(
        select(Task)
        .where(Task.workspace_id == workspace_id)
        .order_by(Task.sort_order)
    ).all()

    for col in ws_columns:
        col_tasks = [t for t in ws_tasks if t.status == col.name]
        lines.append(f"### {col.name} ({len(col_tasks)})")
        lines.append(f"")
        if not col_tasks:
            lines.append(f"(none)")
            lines.append(f"")
            continue
        for t in col_tasks:
            assignee = ""
            if t.assignee_id:
                u = session.get(User, t.assignee_id)
                if u:
                    assignee = f" @{u.nickname}"
            priority = f" [{t.priority}]"
            due = f" (due: {t.due_date})" if t.due_date else ""
            tags_str = ""
            if t.tags:
                try:
                    tag_list = json.loads(t.tags)
                    tags_str = " " + " ".join(f"#{tg}" for tg in tag_list)
                except Exception:
                    pass
            lines.append(f"- **{t.title}**{priority}{assignee}{due}{tags_str}")
            if t.description:
                for desc_line in t.description.split("\n"):
                    lines.append(f"  {desc_line}")
            if t.figma_url:
                lines.append(f"  Figma: {t.figma_url}")
            if t.confluence_url:
                lines.append(f"  Confluence: {t.confluence_url}")
            lines.append(f"  Created: {t.created_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"")

    # Changelog grouped by date
    lines.append(f"## Changelog (Daily)")
    lines.append(f"")
    histories = session.exec(
        select(TaskHistory)
        .where(TaskHistory.workspace_id == workspace_id)
        .order_by(TaskHistory.created_at.desc())
    ).all()

    if not histories:
        lines.append("(no change history)")
        lines.append("")
    else:
        lines.append(f"Total: {len(histories)} changes recorded")
        lines.append(f"")

        # Group by date
        by_date: dict[str, list] = {}
        for h in histories:
            date_key = h.created_at.strftime("%Y-%m-%d")
            by_date.setdefault(date_key, []).append(h)

        for date_key in sorted(by_date.keys(), reverse=True):
            day_items = by_date[date_key]
            lines.append(f"### {date_key} ({len(day_items)} changes)")
            lines.append(f"")
            for h in day_items:
                time_str = h.created_at.strftime("%H:%M")
                if h.field_name == "created":
                    lines.append(f"- [{time_str}] **{h.task_title}** created -> {h.new_value}")
                elif h.field_name == "deleted":
                    lines.append(f"- [{time_str}] **{h.task_title}** deleted")
                elif h.field_name == "comment":
                    lines.append(
                        f"- [{time_str}] **{h.task_title}** comment: {h.new_value or ''}"
                    )
                else:
                    lines.append(
                        f"- [{time_str}] **{h.task_title}** {h.field_name}: "
                        f"{h.old_value or '(empty)'} -> {h.new_value or '(empty)'}"
                    )
            lines.append(f"")

    # Report templates
    templates = session.exec(
        select(ReportTemplate).where(ReportTemplate.workspace_id == workspace_id)
    ).all()
    if templates:
        lines.append(f"## Report Templates")
        lines.append(f"")
        for tmpl in templates:
            lines.append(f"### Template: {tmpl.name}")
            lines.append(f"")
            lines.append(f"**System Prompt:**")
            lines.append(f"```")
            lines.append(tmpl.system_prompt or "(default)")
            lines.append(f"```")
            lines.append(f"")
            lines.append(f"**Example Report:**")
            lines.append(f"```")
            lines.append(tmpl.content)
            lines.append(f"```")
            lines.append(f"")

    # Metadata footer (for restore parsing)
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"<!-- BACKUP_META")
    meta = {
        "version": 1,
        "workspace_name": workspace.name,
        "workspace_description": workspace.description,
        "exported_at": now.isoformat(),
        "columns": [{"name": c.name, "sort_order": c.sort_order, "color": c.color} for c in ws_columns],
        "tasks": [],
        "history": [],
        "templates": [],
        "members": [],
    }
    for t in ws_tasks:
        meta["tasks"].append({
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "due_date": str(t.due_date) if t.due_date else None,
            "tags": t.tags,
            "figma_url": t.figma_url,
            "confluence_url": t.confluence_url,
            "sort_order": t.sort_order,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
            "assignee_nickname": (
                session.get(User, t.assignee_id).nickname if t.assignee_id and session.get(User, t.assignee_id) else None
            ),
        })
    for h in histories:
        meta["history"].append({
            "task_title": h.task_title,
            "field_name": h.field_name,
            "old_value": h.old_value,
            "new_value": h.new_value,
            "created_at": h.created_at.isoformat(),
        })
    for tmpl in templates:
        meta["templates"].append({
            "name": tmpl.name,
            "content": tmpl.content,
            "system_prompt": tmpl.system_prompt,
        })
    for m in members:
        user = session.get(User, m.user_id)
        if user:
            meta["members"].append({"nickname": user.nickname, "email": user.email})

    lines.append(json.dumps(meta, ensure_ascii=False, indent=2))
    lines.append(f"BACKUP_META -->")
    lines.append(f"")

    content = "\n".join(lines)
    filename = f"{workspace.name.replace(' ', '_')}_backup_{now.strftime('%Y%m%d')}.md"

    return PlainTextResponse(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Backup: Restore from Markdown ───────────────────


@router.post("/restore")
async def restore_workspace_backup(
    owner_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Restore a workspace from a backup Markdown file.

    Parses the BACKUP_META JSON block embedded in the .md file to recreate
    the workspace, columns, tasks, history, and templates.
    """
    raw = await file.read()
    text = raw.decode("utf-8")

    # Extract JSON from <!-- BACKUP_META ... BACKUP_META -->
    start_marker = "<!-- BACKUP_META"
    end_marker = "BACKUP_META -->"
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        raise HTTPException(
            status_code=400,
            detail="유효한 백업 파일이 아닙니다. BACKUP_META 블록을 찾을 수 없습니다.",
        )

    json_str = text[start_idx + len(start_marker):end_idx].strip()
    try:
        meta = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"백업 메타데이터 파싱 실패: {e}")

    ws_name = meta.get("workspace_name", "Restored Workspace")
    ws_desc = meta.get("workspace_description")

    # Check if workspace with same name already exists
    existing = session.exec(
        select(Workspace).where(Workspace.name == ws_name)
    ).first()

    if existing:
        # Delete existing workspace data for overwrite
        ws_id = existing.id

        # Delete comments on tasks
        old_tasks = session.exec(select(Task).where(Task.workspace_id == ws_id)).all()
        for t in old_tasks:
            for c in session.exec(select(Comment).where(Comment.task_id == t.id)).all():
                session.delete(c)
            session.delete(t)

        for h in session.exec(select(TaskHistory).where(TaskHistory.workspace_id == ws_id)).all():
            session.delete(h)
        for tmpl in session.exec(select(ReportTemplate).where(ReportTemplate.workspace_id == ws_id)).all():
            session.delete(tmpl)
        for col in session.exec(select(BoardColumn).where(BoardColumn.workspace_id == ws_id)).all():
            session.delete(col)
        for m in session.exec(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id)).all():
            session.delete(m)

        existing.description = ws_desc
        session.add(existing)
        session.commit()
        workspace = existing
    else:
        workspace = Workspace(
            name=ws_name,
            description=ws_desc,
            owner_id=owner_id,
            created_at=datetime.utcnow(),
        )
        session.add(workspace)
        session.commit()
        session.refresh(workspace)

    ws_id = workspace.id

    # Add owner as member
    member = WorkspaceMember(workspace_id=ws_id, user_id=owner_id)
    session.add(member)

    # Restore members (create users if needed, add as members)
    for m_data in meta.get("members", []):
        nickname = m_data.get("nickname")
        if not nickname:
            continue
        user = session.exec(select(User).where(User.nickname == nickname)).first()
        if not user:
            user = User(nickname=nickname, email=m_data.get("email"))
            session.add(user)
            session.commit()
            session.refresh(user)
        # Add as member if not already
        if user.id != owner_id:
            existing_member = session.exec(
                select(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == ws_id)
                .where(WorkspaceMember.user_id == user.id)
            ).first()
            if not existing_member:
                session.add(WorkspaceMember(workspace_id=ws_id, user_id=user.id))

    # Restore columns
    for col_data in meta.get("columns", []):
        session.add(BoardColumn(
            name=col_data["name"],
            sort_order=col_data.get("sort_order", 0),
            color=col_data.get("color"),
            workspace_id=ws_id,
        ))

    session.commit()

    # Restore tasks
    for t_data in meta.get("tasks", []):
        assignee_id = None
        if t_data.get("assignee_nickname"):
            assignee = session.exec(
                select(User).where(User.nickname == t_data["assignee_nickname"])
            ).first()
            if assignee:
                assignee_id = assignee.id

        from datetime import date as date_type
        due_date = None
        if t_data.get("due_date") and t_data["due_date"] != "None":
            try:
                due_date = date_type.fromisoformat(t_data["due_date"])
            except ValueError:
                pass

        task = Task(
            title=t_data["title"],
            description=t_data.get("description"),
            status=t_data.get("status", "TODO"),
            priority=t_data.get("priority", "MEDIUM"),
            assignee_id=assignee_id,
            due_date=due_date,
            tags=t_data.get("tags"),
            figma_url=t_data.get("figma_url"),
            confluence_url=t_data.get("confluence_url"),
            sort_order=t_data.get("sort_order", 0),
            workspace_id=ws_id,
            created_at=datetime.fromisoformat(t_data["created_at"]) if t_data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(t_data["updated_at"]) if t_data.get("updated_at") else datetime.utcnow(),
        )
        session.add(task)

    # Restore history
    for h_data in meta.get("history", []):
        session.add(TaskHistory(
            task_id=0,
            task_title=h_data["task_title"],
            field_name=h_data["field_name"],
            old_value=h_data.get("old_value"),
            new_value=h_data.get("new_value"),
            workspace_id=ws_id,
            created_at=datetime.fromisoformat(h_data["created_at"]) if h_data.get("created_at") else datetime.utcnow(),
        ))

    # Restore templates
    for tmpl_data in meta.get("templates", []):
        session.add(ReportTemplate(
            name=tmpl_data.get("name", "default"),
            content=tmpl_data["content"],
            system_prompt=tmpl_data.get("system_prompt", ""),
            workspace_id=ws_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))

    session.commit()
    session.refresh(workspace)

    return {
        "ok": True,
        "workspace_id": ws_id,
        "workspace_name": ws_name,
        "message": f"워크스페이스 '{ws_name}' 복원 완료",
    }
