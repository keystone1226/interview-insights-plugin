#!/usr/bin/env python3
"""Demo data seed script.

디자인 시스템 + 사용자 리서치 팀의 2주 스프린트 시나리오.
기존 DB를 초기화하고 데모 데이터를 생성합니다.

사용법:
    cd task-manager
    python seed_demo.py
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 모듈 임포트를 위해 path 추가
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlmodel import Session, create_engine, SQLModel, select

from app.config import DATABASE_URL
from app.models import (
    BoardColumn,
    Comment,
    Notification,
    ReportTemplate,
    Task,
    TaskHistory,
    User,
)

engine = create_engine(DATABASE_URL)


def clear_all(session: Session):
    """기존 데이터 전부 삭제."""
    for model in [Comment, TaskHistory, Task, ReportTemplate, BoardColumn, User]:
        # Notification은 User FK cascade로 처리
        try:
            items = session.exec(select(model)).all()
            for item in items:
                session.delete(item)
        except Exception:
            pass
    session.commit()


def seed(session: Session):
    now = datetime.utcnow()
    day = timedelta(days=1)
    hour = timedelta(hours=1)

    # ── 팀원 ────────────────────────────
    users_data = [
        ("지민", "jimin@samsung.com"),
        ("수현", "suhyun@samsung.com"),
        ("태호", "taeho@samsung.com"),
        ("유나", "yuna@samsung.com"),
    ]
    users = {}
    for nickname, email in users_data:
        u = User(nickname=nickname, email=email, created_at=now - 14 * day)
        session.add(u)
        session.flush()
        users[nickname] = u
    print(f"  Users: {len(users)}명 생성")

    # ── 칸반 컬럼 ──────────────────────
    columns_data = [
        ("BACKLOG", 0, "#94a3b8"),
        ("TODO", 1, "#6366f1"),
        ("IN_PROGRESS", 2, "#f59e0b"),
        ("REVIEW", 3, "#06b6d4"),
        ("DONE", 4, "#22c55e"),
    ]
    cols = {}
    for name, order, color in columns_data:
        c = BoardColumn(name=name, sort_order=order, color=color)
        session.add(c)
        cols[name] = c
    session.flush()
    print(f"  Columns: {len(cols)}개 생성")

    # ── 태스크 ──────────────────────────
    tasks_data = [
        # (title, desc, status, priority, assignee, tags, due_offset_days, figma, confluence)
        (
            "디자인 토큰 정의 (Color Palette)",
            "브랜드 컬러, 시맨틱 컬러, 다크모드 컬러를 포함한 전체 컬러 토큰 체계 정립",
            "DONE", "HIGH", "지민",
            '["Design System", "Token"]',
            -2, None, None,
        ),
        (
            "Typography Scale 설계",
            "Heading, Body, Caption 등 타이포그래피 스케일 및 line-height, letter-spacing 정의",
            "DONE", "HIGH", "지민",
            '["Design System", "Typography"]',
            -1, None, None,
        ),
        (
            "Button 컴포넌트 디자인",
            "Primary, Secondary, Ghost, Danger 버튼 variants. 각 사이즈(sm/md/lg) 및 상태(default/hover/active/disabled) 포함",
            "IN_PROGRESS", "HIGH", "수현",
            '["Design System", "Component"]',
            3, "https://figma.com/file/demo-button-component", None,
        ),
        (
            "Input Field 컴포넌트 디자인",
            "Text, Password, Search, Textarea variants. Validation 상태(error/success/warning) 포함",
            "IN_PROGRESS", "MEDIUM", "수현",
            '["Design System", "Component"]',
            5, "https://figma.com/file/demo-input-component", None,
        ),
        (
            "Spacing & Grid System 정의",
            "4px 기반 스페이싱 체계, 12 column grid, breakpoint 정의 (mobile/tablet/desktop)",
            "REVIEW", "MEDIUM", "지민",
            '["Design System", "Layout"]',
            1, None, None,
        ),
        (
            "Icon Set 선정 및 커스텀 아이콘 제작",
            "Lucide 기반 아이콘 셋 + 서비스 특화 커스텀 아이콘 20종 제작",
            "TODO", "MEDIUM", "태호",
            '["Design System", "Icon"]',
            7, "https://figma.com/file/demo-icon-set", None,
        ),
        (
            "사용자 인터뷰 스크립트 작성",
            "신규 서비스 사용성 평가를 위한 인터뷰 가이드. 태스크 시나리오 5개, 사전/사후 질문 포함",
            "DONE", "HIGH", "유나",
            '["User Research", "Interview"]',
            -3, None, "https://confluence.samsung.com/demo-interview-script",
        ),
        (
            "사용자 인터뷰 진행 (1차 5명)",
            "내부 직원 대상 1차 사용성 테스트. 화면 녹화 및 think-aloud 방식",
            "IN_PROGRESS", "HIGH", "유나",
            '["User Research", "Interview"]',
            2, None, None,
        ),
        (
            "인터뷰 분석 및 어피니티 다이어그램",
            "1차 인터뷰 결과 정리, 어피니티 다이어그램으로 핵심 인사이트 도출",
            "BACKLOG", "MEDIUM", "유나",
            '["User Research", "Analysis"]',
            10, None, None,
        ),
        (
            "경쟁사 디자인 시스템 벤치마킹",
            "Material Design, Ant Design, Carbon Design 등 주요 디자인 시스템 비교 분석",
            "DONE", "LOW", "태호",
            '["Research", "Benchmark"]',
            -5, None, "https://confluence.samsung.com/demo-benchmark",
        ),
        (
            "Modal / Dialog 컴포넌트 디자인",
            "Alert, Confirm, Custom 모달. 애니메이션 및 접근성(키보드 트랩, aria) 가이드 포함",
            "TODO", "MEDIUM", "수현",
            '["Design System", "Component"]',
            8, None, None,
        ),
        (
            "Dark Mode 테마 적용",
            "기존 컬러 토큰 기반으로 다크모드 매핑. 명암비 WCAG AA 기준 충족 확인",
            "BACKLOG", "HIGH", "지민",
            '["Design System", "Theme"]',
            12, None, None,
        ),
        (
            "페르소나 정의 업데이트",
            "기존 페르소나 3종을 인터뷰 결과 반영하여 업데이트. 신규 페르소나 1종 추가",
            "TODO", "MEDIUM", "유나",
            '["User Research", "Persona"]',
            9, None, "https://confluence.samsung.com/demo-persona",
        ),
        (
            "Storybook 환경 구축",
            "디자인 시스템 컴포넌트 문서화를 위한 Storybook 초기 세팅 및 CI 연동",
            "IN_PROGRESS", "MEDIUM", "태호",
            '["Design System", "Dev"]',
            4, None, None,
        ),
        (
            "접근성 가이드라인 문서 작성",
            "WCAG 2.1 AA 기준 체크리스트 및 컴포넌트별 접근성 구현 가이드",
            "TODO", "LOW", "태호",
            '["Design System", "Accessibility"]',
            14, None, None,
        ),
    ]

    task_objs = []
    for i, (title, desc, status, priority, assignee, tags, due_offset, figma, confl) in enumerate(tasks_data):
        t = Task(
            title=title,
            description=desc,
            status=status,
            priority=priority,
            assignee_id=users[assignee].id,
            tags=tags,
            due_date=(now + due_offset * day).date(),
            figma_url=figma,
            confluence_url=confl,
            sort_order=i,
            created_at=now - 10 * day + i * hour,
            updated_at=now - 2 * day + i * hour,
        )
        session.add(t)
        session.flush()
        task_objs.append(t)
    print(f"  Tasks: {len(task_objs)}개 생성")

    # ── 댓글 ──────────────────────────────
    comments_data = [
        (0, "수현", "컬러 토큰 Figma에 올려두었습니다. 다크모드 대비비 확인 부탁드려요!"),
        (0, "태호", "확인했습니다. Neutral 계열 300~500 구간 명암비가 좀 아슬아슬하네요."),
        (2, "지민", "Ghost 버튼 hover 상태에서 배경색 추가하면 어떨까요?"),
        (2, "수현", "@지민 좋은 의견이에요! 반영하겠습니다."),
        (4, "태호", "Grid 시스템 breakpoint 값 확인했습니다. tablet이 768px 맞나요?"),
        (4, "지민", "@태호 네, 768px~1024px 구간입니다."),
        (7, "유나", "3명 완료, 2명 내일 진행 예정입니다. 현재까지 네비게이션 관련 이슈가 가장 많이 나옵니다."),
        (7, "지민", "네비게이션 이슈 구체적으로 공유 부탁드려요!"),
        (9, "유나", "벤치마킹 문서 정리 잘 됐네요! 우리 시스템에 적용할 포인트 표시해주세요."),
        (13, "수현", "Storybook에 Button 컴포넌트 먼저 등록해주시면 바로 연동 테스트 해볼게요."),
        (13, "태호", "@수현 내일 오전에 PR 올리겠습니다!"),
    ]

    for task_idx, author, content in comments_data:
        c = Comment(
            content=content,
            task_id=task_objs[task_idx].id,
            author_id=users[author].id,
            created_at=now - 3 * day + task_idx * hour,
        )
        session.add(c)
    print(f"  Comments: {len(comments_data)}개 생성")

    # ── 태스크 변동 히스토리 (주간보고서용) ──────
    history_data = [
        # (task_idx, field, old, new, days_ago)
        (0, "created", None, "디자인 토큰 정의 (Color Palette)", 10),
        (0, "status", "TODO", "IN_PROGRESS", 8),
        (0, "status", "IN_PROGRESS", "REVIEW", 5),
        (0, "status", "REVIEW", "DONE", 3),
        (1, "created", None, "Typography Scale 설계", 9),
        (1, "status", "TODO", "IN_PROGRESS", 7),
        (1, "status", "IN_PROGRESS", "DONE", 2),
        (2, "created", None, "Button 컴포넌트 디자인", 8),
        (2, "status", "TODO", "IN_PROGRESS", 4),
        (2, "assignee_id", None, "수현", 8),
        (3, "created", None, "Input Field 컴포넌트 디자인", 7),
        (3, "status", "TODO", "IN_PROGRESS", 3),
        (4, "created", None, "Spacing & Grid System 정의", 9),
        (4, "status", "TODO", "IN_PROGRESS", 6),
        (4, "status", "IN_PROGRESS", "REVIEW", 2),
        (5, "created", None, "Icon Set 선정 및 커스텀 아이콘 제작", 6),
        (6, "created", None, "사용자 인터뷰 스크립트 작성", 12),
        (6, "status", "TODO", "IN_PROGRESS", 10),
        (6, "status", "IN_PROGRESS", "DONE", 5),
        (7, "created", None, "사용자 인터뷰 진행 (1차 5명)", 7),
        (7, "status", "TODO", "IN_PROGRESS", 4),
        (8, "created", None, "인터뷰 분석 및 어피니티 다이어그램", 5),
        (9, "created", None, "경쟁사 디자인 시스템 벤치마킹", 14),
        (9, "status", "TODO", "IN_PROGRESS", 12),
        (9, "status", "IN_PROGRESS", "DONE", 6),
        (10, "created", None, "Modal / Dialog 컴포넌트 디자인", 5),
        (11, "created", None, "Dark Mode 테마 적용", 4),
        (11, "priority", "MEDIUM", "HIGH", 3),
        (12, "created", None, "페르소나 정의 업데이트", 4),
        (13, "created", None, "Storybook 환경 구축", 6),
        (13, "status", "TODO", "IN_PROGRESS", 3),
        (14, "created", None, "접근성 가이드라인 문서 작성", 3),
    ]

    for task_idx, field, old, new, days_ago in history_data:
        h = TaskHistory(
            task_id=task_objs[task_idx].id,
            task_title=task_objs[task_idx].title,
            field_name=field,
            old_value=old,
            new_value=new,
            created_at=now - days_ago * day,
        )
        session.add(h)
    print(f"  History: {len(history_data)}개 생성")

    # ── 주간보고서 템플릿 + 시스템 프롬프트 ─────
    template = ReportTemplate(
        name="default",
        content="""## UX디자인팀 주간업무보고

### 보고기간: 2026.03.20 ~ 2026.03.26

---

### 1. 디자인 시스템 구축
| 항목 | 담당 | 상태 | 비고 |
|------|------|------|------|
| 컬러 토큰 정의 | 지민 | 완료 | 다크모드 포함 |
| 타이포그래피 스케일 | 지민 | 완료 | - |
| Button 컴포넌트 | 수현 | 진행중 | Ghost variant 추가 예정 |

### 2. 사용자 리서치
- 사용성 테스트 1차 (5명 중 3명 완료)
- 네비게이션 관련 이슈 다수 발견 → 2차 인터뷰 반영 예정

### 3. 다음 주 계획
- Input / Modal 컴포넌트 디자인 착수
- 인터뷰 분석 및 어피니티 다이어그램 작성
- Storybook 연동 테스트

### 4. 이슈 & 리스크
- 다크모드 명암비 일부 미달 (Neutral 300~500) → 조정 필요
""",
        system_prompt=(
            "당신은 삼성 UX디자인팀의 주간보고서를 작성하는 어시스턴트입니다. "
            "다음 규칙을 따르세요:\n"
            "1. 한국어 경어체로 작성\n"
            "2. 예시 보고서의 마크다운 표, 섹션 구조를 정확히 유지\n"
            "3. 각 태스크의 상태 변화를 기반으로 진행률을 판단\n"
            "4. '다음 주 계획'은 현재 TODO/BACKLOG 상태인 태스크에서 도출\n"
            "5. '이슈 & 리스크'는 댓글이나 우선순위 변경에서 추론\n"
            "6. 불필요한 반복 없이 간결하게 작성"
        ),
        created_at=now - 7 * day,
        updated_at=now,
    )
    session.add(template)
    print("  Template: 1개 생성 (시스템 프롬프트 포함)")

    session.commit()
    print("\nDone! 데모 데이터 시드 완료.")


def main():
    print("=" * 50)
    print("Demo Data Seed")
    print("=" * 50)

    # 테이블이 없으면 생성 (alembic 없이도 동작하도록)
    print("\nDB 테이블 확인/생성 중...")
    SQLModel.metadata.create_all(engine)

    # DB 초기화 (테이블 구조 유지, 데이터만 삭제)
    with Session(engine) as session:
        print("기존 데이터 삭제 중...")
        clear_all(session)
        print("데모 데이터 생성 중...")
        seed(session)

    print("\n서버를 시작하세요: python -m app")


if __name__ == "__main__":
    main()
