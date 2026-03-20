"""Notification routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import get_session
from app.models import Notification, NotificationRead

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/users/{user_id}/notifications", response_model=list[NotificationRead])
def list_notifications(
    user_id: int,
    unread_only: bool = False,
    session: Session = Depends(get_session),
):
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.is_read == False)  # noqa: E712
    query = query.order_by(Notification.created_at.desc())
    return session.exec(query).all()


@router.get("/users/{user_id}/notifications/count")
def notification_count(user_id: int, session: Session = Depends(get_session)):
    count = session.exec(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.is_read == False)  # noqa: E712
    ).one()
    return {"unread_count": count}


@router.patch("/notifications/{notification_id}/read")
def mark_read(notification_id: int, session: Session = Depends(get_session)):
    notification = session.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    session.add(notification)
    session.commit()
    return {"ok": True}


@router.post("/users/{user_id}/notifications/read-all")
def mark_all_read(user_id: int, session: Session = Depends(get_session)):
    notifications = session.exec(
        select(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.is_read == False)  # noqa: E712
    ).all()
    for n in notifications:
        n.is_read = True
        session.add(n)
    session.commit()
    return {"ok": True, "count": len(notifications)}
