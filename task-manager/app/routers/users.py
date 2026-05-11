"""User (nickname) management routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, UserCreate, UserRead

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(session: Session = Depends(get_session)):
    return session.exec(select(User).order_by(User.nickname)).all()


@router.post("", response_model=UserRead, status_code=201)
def create_user(data: UserCreate, session: Session = Depends(get_session)):
    existing = session.exec(
        select(User).where(User.nickname == data.nickname)
    ).first()
    if existing:
        return existing  # idempotent: return existing user
    user = User.model_validate(data)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/{user_id}/complete-onboarding", response_model=UserRead)
def complete_onboarding(user_id: int, session: Session = Depends(get_session)):
    """Mark a user as having completed the onboarding flow.

    Idempotent: calling twice keeps the original timestamp.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.onboarded_at is None:
        user.onboarded_at = datetime.utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
    return user
