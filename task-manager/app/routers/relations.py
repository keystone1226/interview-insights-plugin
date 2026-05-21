"""Task relation (parent-child linkage) routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_user_id, get_workspace_id
from app.models import (
    Task,
    TaskHistory,
    TaskRelation,
    TaskRelationCreate,
    TaskRelationInfo,
    User,
)

router = APIRouter(prefix="/api/relations", tags=["relations"])


def _would_create_cycle(session: Session, parent_id: int, child_id: int) -> bool:
    if parent_id == child_id:
        return True
    visited = set()
    queue = [parent_id]
    while queue:
        current = queue.pop()
        if current == child_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        parent_edges = session.exec(
            select(TaskRelation.parent_id).where(TaskRelation.child_id == current)
        ).all()
        queue.extend(parent_edges)
    return False


def _task_relation_info(session: Session, task: Task, relation_id: int) -> dict:
    assignee_name = None
    if task.assignee_id:
        user = session.get(User, task.assignee_id)
        if user:
            assignee_name = user.nickname
    return TaskRelationInfo(
        relation_id=relation_id,
        task_id=task.id,
        title=task.title,
        status=task.status,
        priority=task.priority,
        assignee_name=assignee_name,
    )


@router.get("/task/{task_id}")
def get_task_relations(task_id: int, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    child_rels = session.exec(
        select(TaskRelation).where(TaskRelation.parent_id == task_id)
    ).all()
    parent_rels = session.exec(
        select(TaskRelation).where(TaskRelation.child_id == task_id)
    ).all()

    children = []
    for rel in child_rels:
        child_task = session.get(Task, rel.child_id)
        if child_task:
            children.append(_task_relation_info(session, child_task, rel.id))

    parents = []
    for rel in parent_rels:
        parent_task = session.get(Task, rel.parent_id)
        if parent_task:
            parents.append(_task_relation_info(session, parent_task, rel.id))

    return {"parents": parents, "children": children}


@router.post("", status_code=201)
def create_relation(
    data: TaskRelationCreate,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    parent = session.get(Task, data.parent_id)
    child = session.get(Task, data.child_id)
    if not parent or not child:
        raise HTTPException(status_code=404, detail="Task not found")

    existing = session.exec(
        select(TaskRelation).where(
            TaskRelation.parent_id == data.parent_id,
            TaskRelation.child_id == data.child_id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Relation already exists")

    if _would_create_cycle(session, data.parent_id, data.child_id):
        raise HTTPException(status_code=400, detail="순환 관계가 발생합니다. 이 연결은 생성할 수 없습니다.")

    rel = TaskRelation(parent_id=data.parent_id, child_id=data.child_id)
    session.add(rel)

    session.add(TaskHistory(
        task_id=parent.id,
        task_title=parent.title,
        field_name="child_added",
        old_value=None,
        new_value=child.title,
        changed_by_id=user_id,
        workspace_id=parent.workspace_id,
    ))

    session.commit()
    session.refresh(rel)
    return {"id": rel.id, "parent_id": rel.parent_id, "child_id": rel.child_id}


@router.delete("/{relation_id}", status_code=204)
def delete_relation(
    relation_id: int,
    session: Session = Depends(get_session),
    user_id: int | None = Depends(get_user_id),
):
    rel = session.get(TaskRelation, relation_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Relation not found")

    parent = session.get(Task, rel.parent_id)
    child = session.get(Task, rel.child_id)
    if parent and child:
        session.add(TaskHistory(
            task_id=parent.id,
            task_title=parent.title,
            field_name="child_removed",
            old_value=child.title,
            new_value=None,
            changed_by_id=user_id,
            workspace_id=parent.workspace_id,
        ))

    session.delete(rel)
    session.commit()


@router.get("/graph")
def get_relation_graph(
    session: Session = Depends(get_session),
    workspace_id: int | None = Depends(get_workspace_id),
):
    task_query = select(Task).where(Task.archived == False)
    if workspace_id:
        task_query = task_query.where(Task.workspace_id == workspace_id)
    else:
        task_query = task_query.where(Task.workspace_id.is_(None))
    all_tasks = session.exec(task_query).all()

    task_ids = {t.id for t in all_tasks}

    nodes = []
    for t in all_tasks:
        assignee_name = None
        if t.assignee_id:
            user = session.get(User, t.assignee_id)
            if user:
                assignee_name = user.nickname
        nodes.append({
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "assignee": assignee_name,
        })

    all_rels = session.exec(select(TaskRelation)).all()
    edges = [
        {"id": r.id, "parent_id": r.parent_id, "child_id": r.child_id}
        for r in all_rels
        if r.parent_id in task_ids and r.child_id in task_ids
    ]

    return {"nodes": nodes, "edges": edges}
