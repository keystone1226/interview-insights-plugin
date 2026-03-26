"""Workspace management routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    BoardColumn,
    Workspace,
    WorkspaceCreate,
    WorkspaceMember,
    WorkspaceRead,
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
    return session.exec(query).all()


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

    session.commit()
    session.refresh(workspace)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(workspace_id: int, session: Session = Depends(get_session)):
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: int, session: Session = Depends(get_session)):
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # Delete members
    members = session.exec(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    ).all()
    for m in members:
        session.delete(m)
    session.delete(workspace)
    session.commit()


@router.post("/{workspace_id}/join")
def join_workspace(
    workspace_id: int,
    user_id: int,
    session: Session = Depends(get_session),
):
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

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
