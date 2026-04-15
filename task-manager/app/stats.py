"""Self-hosted usage analytics.

All queries read directly from the app's own SQLite DB — no external
services, no network calls. Meant for running via
``python -m app stats`` to answer:

- How many people registered, joined a workspace, created a task?
- Where in the funnel is churn happening?
- Which workspaces are actually active vs. abandoned?
- How is daily activity trending?

Limitations:
  TaskHistory.changed_by_id is only populated going forward (after the
  X-User-Id header plumbing landed). Older history rows have NULL
  ``changed_by_id``, so user-level action attribution is backfill-
  accurate only for data created after that change.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session, func, select

from app.models import (
    Comment,
    Task,
    TaskHistory,
    User,
    Workspace,
    WorkspaceMember,
)


# ── Data shapes ─────────────────────────────────────


@dataclass
class FunnelStep:
    label: str
    count: int
    pct_of_first: float


@dataclass
class WorkspaceRow:
    id: int
    name: str
    task_count: int
    member_count: int
    last_activity: datetime | None


@dataclass
class Stats:
    generated_at: datetime
    db_path: str

    # Users
    users_total: int
    users_joined_ws: int
    users_with_action: int  # has any comment or authored history row
    users_active_7d: int
    users_active_30d: int

    # Workspaces
    ws_total: int
    ws_with_multiple_members: int
    ws_with_5_tasks: int
    ws_active_7d: int
    ws_active_30d: int
    ws_top: list[WorkspaceRow]

    # Tasks
    tasks_total: int
    tasks_moved_once: int
    tasks_done: int
    tasks_never_moved: int
    tasks_last_7d: int
    tasks_last_30d: int

    # Churn signals
    churn_no_workspace: int
    churn_no_action: int
    churn_single_task_users: int

    # Engagement (where attribution exists)
    commenters: int
    comments_total: int
    comments_last_7d: int

    # Timeline
    daily_task_creations: list[tuple[str, int]] = field(default_factory=list)

    # Per-user distribution
    tasks_per_user_buckets: dict[str, int] = field(default_factory=dict)

    # Metadata
    attribution_coverage_pct: float = 0.0
    attributed_history_rows: int = 0
    total_history_rows: int = 0


# ── Queries ─────────────────────────────────────────


def compute_stats(session: Session, db_path: str) -> Stats:
    now = datetime.utcnow()
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    # ── Users ────────────────────────────────────────
    users_total = session.exec(select(func.count()).select_from(User)).one()

    users_joined_ws = session.exec(
        select(func.count(func.distinct(WorkspaceMember.user_id)))
    ).one()

    # "Took any action" = has authored a comment OR was credited as
    # the actor on a TaskHistory row.
    commented_user_ids = set(
        session.exec(select(Comment.author_id).distinct()).all()
    )
    history_actor_ids = set(
        session.exec(
            select(TaskHistory.changed_by_id)
            .where(TaskHistory.changed_by_id.is_not(None))
            .distinct()
        ).all()
    )
    users_with_action = len(commented_user_ids | history_actor_ids)

    # Activity windows — same definition but filtered by date.
    def _active_user_ids(since: datetime) -> set[int]:
        c = set(
            session.exec(
                select(Comment.author_id)
                .where(Comment.created_at >= since)
                .distinct()
            ).all()
        )
        h = set(
            session.exec(
                select(TaskHistory.changed_by_id)
                .where(TaskHistory.changed_by_id.is_not(None))
                .where(TaskHistory.created_at >= since)
                .distinct()
            ).all()
        )
        return {u for u in (c | h) if u is not None}

    users_active_7d = len(_active_user_ids(cutoff_7d))
    users_active_30d = len(_active_user_ids(cutoff_30d))

    # ── Workspaces ───────────────────────────────────
    ws_total = session.exec(select(func.count()).select_from(Workspace)).one()

    # Count workspaces whose member count > 1.
    ws_member_counts = dict(
        session.exec(
            select(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
            .group_by(WorkspaceMember.workspace_id)
        ).all()
    )
    ws_with_multiple_members = sum(1 for c in ws_member_counts.values() if c > 1)

    ws_task_counts = dict(
        session.exec(
            select(Task.workspace_id, func.count(Task.id))
            .where(Task.workspace_id.is_not(None))
            .group_by(Task.workspace_id)
        ).all()
    )
    ws_with_5_tasks = sum(1 for c in ws_task_counts.values() if c >= 5)

    # Workspace last-activity = max(task.updated_at, history.created_at, comment.created_at)
    ws_last_activity: dict[int, datetime] = {}
    for ws_id, updated in session.exec(
        select(Task.workspace_id, func.max(Task.updated_at))
        .where(Task.workspace_id.is_not(None))
        .group_by(Task.workspace_id)
    ).all():
        if updated:
            ws_last_activity[ws_id] = updated
    for ws_id, ts in session.exec(
        select(TaskHistory.workspace_id, func.max(TaskHistory.created_at))
        .where(TaskHistory.workspace_id.is_not(None))
        .group_by(TaskHistory.workspace_id)
    ).all():
        if ts and (ws_id not in ws_last_activity or ts > ws_last_activity[ws_id]):
            ws_last_activity[ws_id] = ts

    ws_active_7d = sum(1 for t in ws_last_activity.values() if t >= cutoff_7d)
    ws_active_30d = sum(1 for t in ws_last_activity.values() if t >= cutoff_30d)

    # Top workspaces by task count (limit 5).
    workspaces = session.exec(select(Workspace)).all()
    top_rows: list[WorkspaceRow] = []
    for ws in workspaces:
        top_rows.append(
            WorkspaceRow(
                id=ws.id,
                name=ws.name,
                task_count=ws_task_counts.get(ws.id, 0),
                member_count=ws_member_counts.get(ws.id, 0),
                last_activity=ws_last_activity.get(ws.id),
            )
        )
    top_rows.sort(key=lambda r: r.task_count, reverse=True)
    ws_top = top_rows[:5]

    # ── Tasks ────────────────────────────────────────
    tasks_total = session.exec(select(func.count()).select_from(Task)).one()
    tasks_done = session.exec(
        select(func.count()).select_from(Task).where(Task.status == "DONE")
    ).one()
    tasks_last_7d = session.exec(
        select(func.count()).select_from(Task).where(Task.created_at >= cutoff_7d)
    ).one()
    tasks_last_30d = session.exec(
        select(func.count()).select_from(Task).where(Task.created_at >= cutoff_30d)
    ).one()

    # "Moved at least once" = has at least one status-change history row.
    moved_task_ids = set(
        session.exec(
            select(TaskHistory.task_id)
            .where(TaskHistory.field_name == "status")
            .distinct()
        ).all()
    )
    tasks_moved_once = len(moved_task_ids)
    tasks_never_moved = tasks_total - tasks_moved_once

    # ── Churn signals ────────────────────────────────
    user_ids_in_ws = set(
        session.exec(select(WorkspaceMember.user_id).distinct()).all()
    )
    all_user_ids = set(session.exec(select(User.id)).all())
    churn_no_workspace = len(all_user_ids - user_ids_in_ws)

    users_with_any_action = commented_user_ids | history_actor_ids
    churn_no_action = len(all_user_ids - users_with_any_action)

    # Users whose assigned task count == 1 AND who never commented.
    assignee_task_counts = dict(
        session.exec(
            select(Task.assignee_id, func.count(Task.id))
            .where(Task.assignee_id.is_not(None))
            .group_by(Task.assignee_id)
        ).all()
    )
    single_assignee_users = {
        uid for uid, cnt in assignee_task_counts.items() if cnt == 1
    }
    churn_single_task_users = len(single_assignee_users - commented_user_ids)

    # ── Engagement ───────────────────────────────────
    commenters = len(commented_user_ids)
    comments_total = session.exec(select(func.count()).select_from(Comment)).one()
    comments_last_7d = session.exec(
        select(func.count())
        .select_from(Comment)
        .where(Comment.created_at >= cutoff_7d)
    ).one()

    # ── Attribution coverage ─────────────────────────
    total_history_rows = session.exec(
        select(func.count()).select_from(TaskHistory)
    ).one()
    attributed_history_rows = session.exec(
        select(func.count())
        .select_from(TaskHistory)
        .where(TaskHistory.changed_by_id.is_not(None))
    ).one()
    coverage_pct = (
        100.0 * attributed_history_rows / total_history_rows
        if total_history_rows
        else 0.0
    )

    # ── Daily timeline (last 14 days) ────────────────
    start_day = (now - timedelta(days=13)).date()
    day_counts: dict[str, int] = {
        (start_day + timedelta(days=i)).isoformat(): 0 for i in range(14)
    }
    for row in session.exec(
        select(Task.created_at).where(Task.created_at >= datetime.combine(start_day, datetime.min.time()))
    ).all():
        key = row.date().isoformat()
        if key in day_counts:
            day_counts[key] += 1
    daily_task_creations = sorted(day_counts.items())

    # ── Per-user task distribution (assignee-based) ──
    buckets = Counter()
    for uid, cnt in assignee_task_counts.items():
        if cnt == 1:
            buckets["1"] += 1
        elif cnt <= 4:
            buckets["2-4"] += 1
        elif cnt <= 9:
            buckets["5-9"] += 1
        else:
            buckets["10+"] += 1
    tasks_per_user_buckets = {
        "1": buckets["1"],
        "2-4": buckets["2-4"],
        "5-9": buckets["5-9"],
        "10+": buckets["10+"],
    }

    return Stats(
        generated_at=now,
        db_path=db_path,
        users_total=users_total,
        users_joined_ws=users_joined_ws,
        users_with_action=users_with_action,
        users_active_7d=users_active_7d,
        users_active_30d=users_active_30d,
        ws_total=ws_total,
        ws_with_multiple_members=ws_with_multiple_members,
        ws_with_5_tasks=ws_with_5_tasks,
        ws_active_7d=ws_active_7d,
        ws_active_30d=ws_active_30d,
        ws_top=ws_top,
        tasks_total=tasks_total,
        tasks_moved_once=tasks_moved_once,
        tasks_done=tasks_done,
        tasks_never_moved=tasks_never_moved,
        tasks_last_7d=tasks_last_7d,
        tasks_last_30d=tasks_last_30d,
        churn_no_workspace=churn_no_workspace,
        churn_no_action=churn_no_action,
        churn_single_task_users=churn_single_task_users,
        commenters=commenters,
        comments_total=comments_total,
        comments_last_7d=comments_last_7d,
        daily_task_creations=daily_task_creations,
        tasks_per_user_buckets=tasks_per_user_buckets,
        attribution_coverage_pct=coverage_pct,
        attributed_history_rows=attributed_history_rows,
        total_history_rows=total_history_rows,
    )


# ── Formatter ───────────────────────────────────────


def _pct(n: int, total: int) -> str:
    if total <= 0:
        return "  -"
    return f"{100 * n / total:4.0f}%"


def _relative_time(ts: datetime | None, now: datetime) -> str:
    if ts is None:
        return "never"
    delta = now - ts
    sec = delta.total_seconds()
    if sec < 60:
        return "just now"
    if sec < 3600:
        return f"{int(sec / 60)}m ago"
    if sec < 86400:
        return f"{int(sec / 3600)}h ago"
    days = int(sec / 86400)
    return f"{days}d ago"


def _sparkline(value: int, max_value: int, width: int = 10) -> str:
    if max_value <= 0:
        return " " * width
    filled = round(width * value / max_value)
    return "█" * filled + "·" * (width - filled)


def format_stats(s: Stats) -> str:
    lines: list[str] = []
    w = 70
    bar = "=" * w
    dash = "-" * w

    lines.append(bar)
    lines.append("  Task Manager — Usage Stats")
    lines.append(f"  Generated: {s.generated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"  DB: {s.db_path}")
    lines.append(bar)

    # Users funnel
    lines.append("")
    lines.append("USERS (funnel)")
    lines.append(dash)
    lines.append(f"  1. Registered                   {s.users_total:>5}")
    lines.append(
        f"  2. Joined a workspace            {s.users_joined_ws:>5}"
        f"   ({_pct(s.users_joined_ws, s.users_total)} of [1])"
    )
    lines.append(
        f"  3. Took any action*              {s.users_with_action:>5}"
        f"   ({_pct(s.users_with_action, s.users_total)} of [1])"
    )
    lines.append(
        f"  4. Active last 7 days*           {s.users_active_7d:>5}"
        f"   ({_pct(s.users_active_7d, s.users_total)} of [1])"
    )
    lines.append(
        f"  5. Active last 30 days*          {s.users_active_30d:>5}"
        f"   ({_pct(s.users_active_30d, s.users_total)} of [1])"
    )
    if s.total_history_rows > 0:
        lines.append(
            f"  * attribution coverage: "
            f"{s.attribution_coverage_pct:.0f}% "
            f"({s.attributed_history_rows}/{s.total_history_rows} history rows)"
        )
    else:
        lines.append("  * no history rows recorded yet")

    # Workspaces
    lines.append("")
    lines.append("WORKSPACES")
    lines.append(dash)
    lines.append(f"  Total                            {s.ws_total:>5}")
    lines.append(
        f"  Multi-member (members > 1)       {s.ws_with_multiple_members:>5}"
        f"   ({_pct(s.ws_with_multiple_members, s.ws_total)})"
    )
    lines.append(
        f"  With >= 5 tasks                  {s.ws_with_5_tasks:>5}"
        f"   ({_pct(s.ws_with_5_tasks, s.ws_total)})"
    )
    lines.append(
        f"  Active last 7 days               {s.ws_active_7d:>5}"
        f"   ({_pct(s.ws_active_7d, s.ws_total)})"
    )
    lines.append(
        f"  Active last 30 days              {s.ws_active_30d:>5}"
        f"   ({_pct(s.ws_active_30d, s.ws_total)})"
    )

    if s.ws_top:
        lines.append("")
        lines.append("  Top 5 by task count:")
        for row in s.ws_top:
            name = row.name[:24]
            lines.append(
                f"    #{row.id:<3} {name:<24} "
                f"{row.task_count:>3} tasks, "
                f"{row.member_count:>2} members, "
                f"{_relative_time(row.last_activity, s.generated_at)}"
            )

    # Tasks
    lines.append("")
    lines.append("TASKS")
    lines.append(dash)
    lines.append(f"  Total                            {s.tasks_total:>5}")
    lines.append(
        f"  Moved at least once              {s.tasks_moved_once:>5}"
        f"   ({_pct(s.tasks_moved_once, s.tasks_total)})"
    )
    lines.append(
        f"  Completed (DONE)                 {s.tasks_done:>5}"
        f"   ({_pct(s.tasks_done, s.tasks_total)})"
    )
    lines.append(
        f"  Never moved from initial state   {s.tasks_never_moved:>5}"
        f"   ({_pct(s.tasks_never_moved, s.tasks_total)})"
    )
    lines.append(f"  Created last 7 days              {s.tasks_last_7d:>5}")
    lines.append(f"  Created last 30 days             {s.tasks_last_30d:>5}")

    # Distribution
    if any(s.tasks_per_user_buckets.values()):
        lines.append("")
        lines.append("  Tasks per user (by assignee_id, users with >= 1):")
        for bucket in ("1", "2-4", "5-9", "10+"):
            count = s.tasks_per_user_buckets.get(bucket, 0)
            lines.append(f"    {bucket:<5}  {count:>3} users")

    # Churn signals
    lines.append("")
    lines.append("CHURN SIGNALS")
    lines.append(dash)
    lines.append(
        f"  Registered but no workspace      {s.churn_no_workspace:>5}"
        f"   ({_pct(s.churn_no_workspace, s.users_total)})"
    )
    lines.append(
        f"  Registered but no action*        {s.churn_no_action:>5}"
        f"   ({_pct(s.churn_no_action, s.users_total)})"
    )
    lines.append(
        f"  Assigned 1 task, never commented {s.churn_single_task_users:>5}"
    )

    # Engagement
    lines.append("")
    lines.append("ENGAGEMENT")
    lines.append(dash)
    lines.append(f"  Users who commented              {s.commenters:>5}")
    lines.append(f"  Comments total                   {s.comments_total:>5}")
    lines.append(f"  Comments last 7 days             {s.comments_last_7d:>5}")

    # Daily timeline
    if s.daily_task_creations:
        lines.append("")
        lines.append("DAILY TASK CREATION (last 14 days)")
        lines.append(dash)
        max_v = max(v for _, v in s.daily_task_creations) or 1
        for day, count in s.daily_task_creations:
            spark = _sparkline(count, max_v)
            lines.append(f"  {day}  {spark}  {count}")

    lines.append("")
    lines.append(bar)
    if s.attribution_coverage_pct < 80 and s.total_history_rows > 0:
        lines.append(
            "  NOTE: Action attribution is partial — rows with NULL "
            "changed_by_id are from"
        )
        lines.append(
            "  before the X-User-Id header was plumbed. Future data "
            "will be fully attributed."
        )
        lines.append(bar)

    return "\n".join(lines)
