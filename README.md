# interview-insights-plugin

사내망에서 바로 실행하는 경량 칸반 **Task Manager**가 담긴 저장소입니다. 외부 서비스/빌드 도구 없이 Python 한 줄로 서버를 띄우고, 네트워크 URL만 공유하면 팀 전체가 사용할 수 있습니다.

---

## 구성

```
.
├── task-manager/          # 메인 애플리케이션 (FastAPI + SQLite + Vanilla JS)
│   ├── app/               # 서버 코드 (routers, models, static 프론트)
│   ├── alembic/           # DB 마이그레이션
│   ├── README.md          # 상세 사용 가이드
│   └── requirements.txt
└── CLAUDE.md              # AI 어시스턴트용 프로젝트 가이드
```

자세한 기능/옵션 설명은 [`task-manager/README.md`](task-manager/README.md)를 참고하세요.

---

## 빠른 시작

```bash
cd task-manager
pip install -r requirements.txt   # 또는 uv sync
python -m app                     # 서버 실행 (기본 포트 8000)
```

실행 후 출력되는 **Network URL**을 팀원과 공유하면 바로 사용할 수 있습니다.

```
==================================================
  Task Manager
==================================================
  Local:   http://127.0.0.1:8000
  Network: http://192.168.1.100:8000

  Share the Network URL with your team!
==================================================
```

---

## 주요 기능

- **워크스페이스 단위 칸반 보드** — TODO / IN_PROGRESS / REVIEW / DONE 기본 컬럼, 드래그앤드롭 이동
- **태스크 관리** — 담당자/우선순위/마감일/태그/Figma·Confluence 링크/커버 이미지
- **댓글 & 멘션 알림** — `@닉네임` 자동완성, 헤더 종 아이콘 알림 패널
- **태스크 아카이브** — 완료된 태스크를 아카이브 컬럼으로 드래그, 키워드/담당자/기간별 검색
- **AI 주간 보고서** — LLM(FabriX)으로 기간 내 변동사항 요약, 시스템 프롬프트/예시 템플릿 저장 가능
- **AI 일감 분해** — 목표/과업을 입력하면 LLM이 작은 단위의 일감으로 자동 분해, 선택적으로 생성 가능
- **다크 테마 UI** — 2단 레이아웃 모달, 인라인 수정
- **워크스페이스 백업/복원** — Markdown(`.md`) 또는 SQLite DB 파일 직접 백업/복원
- **워크스페이스 비밀번호 보호** — PBKDF2-SHA256(120k iter) 해시, 세션 캐시, 자물쇠 배지 UI
- **관리자 CLI** — 비밀번호 리셋, 워크스페이스 목록, 사용 통계

---

## 관리자 CLI

```bash
# 전체 워크스페이스 목록 + password_hash 조회
python -m app list-workspaces

# 사용 통계 (DAU, 퍼널, 이탈, 참여도)
python -m app stats

# 특정 워크스페이스 비밀번호 해제
python -m app reset-password 3 --clear

# 대화형 입력으로 새 비밀번호 설정 (권장 — 셸 히스토리에 남지 않음)
python -m app reset-password 3
```

---

## 기술 스택

- Python 3.10+ / FastAPI / SQLModel / Alembic
- 순수 HTML/CSS/JS 프론트엔드 (빌드 과정·CDN 불필요)
- SQLite (설정 없이 파일 한 개로 동작)
- 선택: FabriX LLM (주간보고서·일감 분해), SMTP (이메일 알림)

---

## 개발자 가이드

AI 어시스턴트(Claude Code 등)가 이 저장소에서 작업할 때 참고할 수 있는 컨벤션·워크플로는 [`CLAUDE.md`](CLAUDE.md)에 정리되어 있습니다.
