"""Board column management routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_workspace_id
from app.models import BoardColumn, BoardColumnCreate, BoardColumnRead, BoardColumnUpdate, Task

router = APIRouter(prefix="/api/columns", tags=["columns"])


@router.get("", response_model=list[BoardColumnRead])
def list_columns(
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    query = select(BoardColumn).order_by(BoardColumn.sort_order)
    if workspace_id:
        query = query.where(BoardColumn.workspace_id == workspace_id)
    else:
        query = query.where(BoardColumn.workspace_id.is_(None))
    return session.exec(query).all()


@router.post("", response_model=BoardColumnRead, status_code=201)
def create_column(
    data: BoardColumnCreate,
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    column = BoardColumn.model_validate(data)
    column.workspace_id = workspace_id
    session.add(column)
    session.commit()
    session.refresh(column)
    return column


@router.patch("/{column_id}", response_model=BoardColumnRead)
def update_column(
    column_id: int, data: BoardColumnUpdate, session: Session = Depends(get_session)
):
    column = session.get(BoardColumn, column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(column, key, value)
    session.add(column)
    session.commit()
    session.refresh(column)
    return column


@router.delete("/{column_id}", status_code=204)
def delete_column(
    column_id: int,
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    column = session.get(BoardColumn, column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")
    # Move tasks in this column to the first available column
    other_query = select(BoardColumn).where(BoardColumn.id != column_id).order_by(BoardColumn.sort_order)
    if workspace_id:
        other_query = other_query.where(BoardColumn.workspace_id == workspace_id)
    other = session.exec(other_query).first()
    if other:
        task_query = select(Task).where(Task.status == column.name)
        if workspace_id:
            task_query = task_query.where(Task.workspace_id == workspace_id)
        tasks = session.exec(task_query).all()
        for task in tasks:
            task.status = other.name
            session.add(task)
    session.delete(column)
    session.commit()
