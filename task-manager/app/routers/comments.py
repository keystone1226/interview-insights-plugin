"""Comment routes with @mention support."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_user_id
from app.models import (
    Comment,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    Notification,
    NotificationType,
    Task,
    TaskHistory,
    User,
)

router = APIRouter(prefix="/api/tasks/{task_id}/comments", tags=["comments"])

MENTION_PATTERN = re.compile(r"@(\S+)")


def _create_mention_notifications(
    session: Session, comment: Comment, task: Task
):
    """Parse @mentions from comment content and create notifications."""
    mentions = MENTION_PATTERN.findall(comment.content)
    if not mentions:
        return

    for nickname in set(mentions):
        user = session.exec(
            select(User).where(User.nickname == nickname)
        ).first()
        if not user or user.id == comment.author_id:
            continue
        author = session.get(User, comment.author_id)
        author_name = author.nickname if author else "누군가"
        msg = f'{author_name}님이 "{task.title}"에서 당신을 멘션했습니다.'
        notification = Notification(
            user_id=user.id,
            task_id=task.id,
            type=NotificationType.MENTION,
            message=msg,
        )
        session.add(notification)


@router.get("", response_model=list[CommentRead])
def list_comments(task_id: int, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    comments = session.exec(
        select(Comment)
        .where(Comment.task_id == task_id)
        .order_by(Comment.created_at)
    ).all()
    return comments


@router.post("", response_model=CommentRead, status_code=201)
def create_comment(
    task_id: int, data: CommentCreate, session: Session = Depends(get_session)
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    author = session.get(User, data.author_id)
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    comment = Comment(
        content=data.content,
        task_id=task_id,
        author_id=data.author_id,
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)

    # Record comment as a task-history change so it appears in the weekly
    # report and the daily changelog (comments are change management).
    history_label = f"{author.nickname}: {data.content}"
    session.add(
        TaskHistory(
            task_id=task.id,
            task_title=task.title,
            field_name="comment",
            old_value=None,
            new_value=history_label,
            changed_by_id=data.author_id,
            workspace_id=task.workspace_id,
        )
    )

    _create_mention_notifications(session, comment, task)
    session.commit()
    session.refresh(comment)

    return comment


@router.patch("/{comment_id}", response_model=CommentRead)
def update_comment(
    task_id: int,
    comment_id: int,
    data: CommentUpdate,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    comment = session.get(Comment, comment_id)
    if not comment or comment.task_id != task_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.author_id != user_id:
        raise HTTPException(status_code=403, detail="Only the author can edit this comment")
    comment.content = data.content
    comment.updated_at = datetime.utcnow()
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@router.delete("/{comment_id}", status_code=204)
def delete_comment(
    task_id: int,
    comment_id: int,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    comment = session.get(Comment, comment_id)
    if not comment or comment.task_id != task_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.author_id != user_id:
        raise HTTPException(status_code=403, detail="Only the author can delete this comment")
    session.delete(comment)
    session.commit()
