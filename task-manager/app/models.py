"""Database models."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NotificationType(str, Enum):
    MENTION = "mention"
    STATUS_CHANGE = "status_change"
    ASSIGNMENT = "assignment"


# ── User ──────────────────────────────────────────────


class UserBase(SQLModel):
    nickname: str = Field(index=True, unique=True, max_length=50)
    email: Optional[str] = Field(default=None, max_length=200)


class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    tasks: list["Task"] = Relationship(back_populates="assignee_user")
    comments: list["Comment"] = Relationship(back_populates="author")
    notifications: list["Notification"] = Relationship(back_populates="user")
    workspace_members: list["WorkspaceMember"] = Relationship(back_populates="user")


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    id: int
    created_at: datetime


# ── Workspace ─────────────────────────────────────────


class Workspace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, index=True)
    description: Optional[str] = Field(default=None, max_length=500)
    owner_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    members: list["WorkspaceMember"] = Relationship(back_populates="workspace")


class WorkspaceMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    joined_at: datetime = Field(default_factory=datetime.utcnow)

    workspace: Optional[Workspace] = Relationship(back_populates="members")
    user: Optional[User] = Relationship(back_populates="workspace_members")


class WorkspaceCreate(SQLModel):
    name: str
    description: Optional[str] = None


class WorkspaceRead(SQLModel):
    id: int
    name: str
    description: Optional[str]
    owner_id: int
    created_at: datetime


# ── BoardColumn ───────────────────────────────────────


class BoardColumnBase(SQLModel):
    name: str = Field(max_length=50)
    sort_order: int = Field(default=0)
    color: Optional[str] = Field(default=None, max_length=20)


class BoardColumn(BoardColumnBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: Optional[int] = Field(default=None, foreign_key="workspace.id", index=True)


class BoardColumnCreate(BoardColumnBase):
    pass


class BoardColumnRead(BoardColumnBase):
    id: int
    workspace_id: Optional[int] = None


class BoardColumnUpdate(SQLModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    color: Optional[str] = None


# ── Task ──────────────────────────────────────────────


class TaskBase(SQLModel):
    title: str = Field(max_length=200)
    description: Optional[str] = Field(default=None)
    status: str = Field(default="TODO", max_length=50)
    priority: Priority = Field(default=Priority.MEDIUM)
    assignee_id: Optional[int] = Field(default=None, foreign_key="user.id")
    figma_url: Optional[str] = Field(default=None, max_length=500)
    confluence_url: Optional[str] = Field(default=None, max_length=500)
    image_path: Optional[str] = Field(default=None, max_length=300)
    due_date: Optional[date] = Field(default=None)
    tags: Optional[str] = Field(default=None)  # JSON array string
    sort_order: int = Field(default=0)


class Task(TaskBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: Optional[int] = Field(default=None, foreign_key="workspace.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    assignee_user: Optional[User] = Relationship(back_populates="tasks")
    comments: list["Comment"] = Relationship(
        back_populates="task", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class TaskCreate(SQLModel):
    title: str
    description: Optional[str] = None
    status: str = "TODO"
    priority: Priority = Priority.MEDIUM
    assignee_id: Optional[int] = None
    figma_url: Optional[str] = None
    confluence_url: Optional[str] = None
    due_date: Optional[date] = None
    tags: Optional[str] = None
    sort_order: int = 0


class TaskRead(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
    assignee_user: Optional[UserRead] = None


class TaskUpdate(SQLModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[Priority] = None
    assignee_id: Optional[int] = None
    figma_url: Optional[str] = None
    confluence_url: Optional[str] = None
    due_date: Optional[date] = None
    tags: Optional[str] = None
    sort_order: Optional[int] = None


class TaskStatusUpdate(SQLModel):
    status: str
    sort_order: int = 0


# ── Comment ───────────────────────────────────────────


class CommentBase(SQLModel):
    content: str
    task_id: int = Field(foreign_key="task.id")
    author_id: int = Field(foreign_key="user.id")


class Comment(CommentBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    task: Optional[Task] = Relationship(back_populates="comments")
    author: Optional[User] = Relationship(back_populates="comments")


class CommentCreate(SQLModel):
    content: str
    author_id: int


class CommentRead(CommentBase):
    id: int
    created_at: datetime
    author: Optional[UserRead] = None


# ── Notification ──────────────────────────────────────


class Notification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    task_id: int = Field(foreign_key="task.id")
    type: NotificationType
    message: str
    is_read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    user: Optional[User] = Relationship(back_populates="notifications")


class NotificationRead(SQLModel):
    id: int
    user_id: int
    task_id: int
    type: NotificationType
    message: str
    is_read: bool
    created_at: datetime


# ── TaskHistory ──────────────────────────────────


class TaskHistory(SQLModel, table=True):
    """Records every meaningful change to a task for weekly report generation."""

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(index=True)
    task_title: str = Field(max_length=200)
    field_name: str = Field(max_length=50)  # e.g. "status", "assignee_id", "title"
    old_value: Optional[str] = Field(default=None)
    new_value: Optional[str] = Field(default=None)
    changed_by_id: Optional[int] = Field(default=None)
    workspace_id: Optional[int] = Field(default=None, foreign_key="workspace.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TaskHistoryRead(SQLModel):
    id: int
    task_id: int
    task_title: str
    field_name: str
    old_value: Optional[str]
    new_value: Optional[str]
    changed_by_id: Optional[int]
    workspace_id: Optional[int] = None
    created_at: datetime


# ── ReportTemplate ───────────────────────────────


DEFAULT_SYSTEM_PROMPT = (
    "당신은 UX디자인팀의 주간보고서를 작성하는 어시스턴트입니다.\n\n"
    "규칙:\n"
    "1. 마크다운 문법(#, *, **, ```, | 등)을 절대 사용하지 마세요. 일반 텍스트로만 작성하세요.\n"
    "2. 예시 보고서는 형식과 구조만 참고하세요. 예시의 내용(텍스트)을 그대로 복사하거나 포함하지 마세요.\n"
    "3. 오직 태스크 변동사항의 description과 상태 변화만을 근거로 새로운 내용을 작성하세요.\n"
    "4. 한국어 경어체로 작성하세요.\n"
    "5. 각 태스크의 description을 활용하여 구체적으로 무엇을 완료/진행했는지 서술하세요.\n"
    "6. DONE으로 변경된 항목은 description 기반으로 완료 내용을 요약하세요.\n"
    "7. TODO/BACKLOG 항목은 '다음 주 계획'에 반영하세요."
)


class ReportTemplate(SQLModel, table=True):
    """Stores a user-provided example weekly report for LLM style reference."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(default="default", max_length=100)
    content: str  # The example report text
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT)
    workspace_id: Optional[int] = Field(default=None, foreign_key="workspace.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReportTemplateCreate(SQLModel):
    name: str = "default"
    content: str
    system_prompt: Optional[str] = None


class ReportTemplateRead(SQLModel):
    id: int
    name: str
    content: str
    system_prompt: str
    created_at: datetime
    updated_at: datetime
