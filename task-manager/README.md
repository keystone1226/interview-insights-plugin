# Task Manager

경량 칸반 태스크 매니저. 외부 의존 없이 사내망에서 바로 실행하고, URL을 공유하면 팀 전체가 사용할 수 있습니다.

---

## 빠른 시작

```bash
cd task-manager
uv sync                        # 의존성 설치
uv run python -m app           # 서버 실행 (기본 포트 8000)
```

서버가 시작되면 아래와 같이 출력됩니다:

```
==================================================
  Task Manager
==================================================
  Local:   http://127.0.0.1:8000
  Network: http://192.168.1.100:8000

  Share the Network URL with your team!
==================================================
```

**Network URL**을 팀원에게 공유하세요. 브라우저에서 접속하면 바로 사용 가능합니다.

### 포트 변경

```bash
uv run python -m app --port 9000
```

---

## 사용 흐름

### 1. 닉네임 입력
처음 접속하면 닉네임을 입력합니다. 이메일은 선택사항(알림용)입니다.

### 2. 워크스페이스 선택
닉네임 입력 후 워크스페이스 선택 화면이 나옵니다.
- **기존 워크스페이스 선택**: 목록에서 클릭하면 참여(join) 후 진입
- **새 워크스페이스 생성**: 하단 입력창에 이름을 쓰고 Create 클릭

워크스페이스는 팀/프로젝트 단위로 분리된 칸반 보드입니다. 각 워크스페이스는 독립적인 태스크, 컬럼, 히스토리, 리포트 템플릿을 가집니다.

### 3. 칸반 보드 사용

#### 태스크 생성
- 각 컬럼 하단의 **+ Add Task** 버튼 클릭
- 제목(필수), 설명, 우선순위, 담당자, 마감일, 태그 입력
- Figma/Confluence URL을 입력하면 카드에 아이콘이 표시됨
- 이미지 첨부 가능 (드래그 앤 드롭 또는 클릭 업로드)

#### 태스크 이동
- 카드를 **드래그 앤 드롭**으로 다른 컬럼으로 이동
- 모든 상태 변경은 자동으로 히스토리에 기록됨

#### 태스크 편집/삭제
- 카드 클릭 → 수정 모달
- 하단 **Delete** 버튼으로 삭제

#### 컬럼 구조
기본 컬럼: **TODO** → **IN_PROGRESS** → **REVIEW** → **DONE**

### 4. 댓글 & 멘션
태스크 편집 화면 하단에서 댓글을 작성할 수 있습니다.
- `@닉네임`으로 팀원을 멘션하면 자동완성이 뜨고, 대상에게 알림이 전송됩니다.

### 5. 알림
- 헤더의 종 아이콘을 클릭하면 알림 패널이 열림
- 멘션, 담당자 변경, 상태 변경 시 알림 생성
- 알림 클릭 시 해당 태스크로 이동

---

## 주간보고서 (Weekly Report)

LLM을 활용해 태스크 변동사항 기반의 주간보고서를 자동 생성합니다.

### 설정

#### 1. LLM API 키 (환경변수)
```bash
export TASK_LLM_CLIENT_KEY=your-client-key
export TASK_LLM_PASS_KEY=your-pass-key
export TASK_LLM_MODEL_ID=your-model-id      # 선택 (기본: sds-ai-llama-3.1-70b-instruct)
export TASK_LLM_ENDPOINT=https://...         # 선택 (기본: FabriX prod)
```

#### 2. 시스템 프롬프트
Weekly Report 모달에서 **Agent Instructions (System Prompt)** 토글을 열면 편집 가능합니다.
기본값은 UX디자인팀 주간보고서 작성 규칙(마크다운 미사용, 경어체, description 활용 등)이 설정되어 있습니다.

#### 3. 예시 템플릿
기존에 사용하던 주간보고서를 **Example Report Template** 란에 붙여넣고 **Save Template**을 클릭하세요. LLM이 이 형식과 톤을 모방하여 보고서를 작성합니다.

### 보고서 생성
1. 헤더의 **Weekly Report** 버튼 클릭
2. 기간 선택 (7일/14일/30일)
3. **Generate Report** 클릭
4. 생성된 보고서를 **Copy to Clipboard**로 복사

### 히스토리 관리
- **Task Changes** 섹션에서 기간 내 변동사항 미리보기
- **Clear History** 버튼으로 히스토리 초기화 (태스크 자체는 유지)

---

## 워크스페이스 관리

### 워크스페이스 전환
헤더의 **Switch Workspace** 버튼 클릭 → 워크스페이스 목록에서 선택

### 워크스페이스 삭제
1. Switch Workspace 모달에서 삭제할 워크스페이스의 **Delete** 버튼 클릭
2. 확인 모달에서 워크스페이스 이름을 정확히 입력
3. **Delete** 클릭

삭제 시 해당 워크스페이스의 모든 데이터(태스크, 히스토리, 템플릿, 컬럼)가 영구 삭제됩니다.

### 백업 (Markdown 다운로드)
1. Switch Workspace 모달에서 **Backup** 버튼 클릭
2. `.md` 파일이 다운로드됨

백업 파일에 포함되는 내용:
- 멤버 목록
- 현재 태스크 목록 (상태별 분류, 설명/링크/태그 포함)
- 일별 체인지로그 (전체 기간 — DB에 저장된 모든 히스토리)
- 리포트 템플릿 (시스템 프롬프트 + 예시 보고서)

백업 파일은 `.md`이므로 누구나 텍스트 에디터나 브라우저로 조회 가능합니다.

### 복원 (Markdown 업로드)
1. 헤더의 **Restore Backup** 버튼 클릭
2. 백업 `.md` 파일 선택
3. 동일 이름 워크스페이스가 있으면 덮어쓰기 경고 → 확인
4. 복원 완료 후 자동으로 해당 워크스페이스로 전환

새 서버에서 기존 데이터를 이어서 사용할 때 유용합니다.

---

## 버전 업그레이드

사내에서 ZIP으로 다운로드하여 배포하는 경우:

### 1. 샌드박스 테스트
```bash
python upgrade_test.py          # 27개 검증 항목 자동 실행
```

### 2. 스테이징 서버
```bash
python upgrade_test.py --serve --port 8001   # 별도 포트에서 미리 확인
```

### 3. 데이터 마이그레이션 (구버전 → 워크스페이스 버전)
```bash
python migrate_data.py --dry-run                    # 미리보기
python migrate_data.py --workspace-name "팀이름"     # 실행
```

---

## 이메일 알림 (선택)

```bash
export TASK_SMTP_HOST=mail.company.internal
export TASK_SMTP_PORT=25
export TASK_SMTP_FROM=taskmanager@company.com
export TASK_SMTP_USER=        # 인증 불필요 시 비워두기
export TASK_SMTP_PASSWORD=
```

---

## 데이터베이스

- SQLite 파일: `tasks.db` (자동 생성)
- 마이그레이션: Alembic 사용, 서버 시작 시 자동 적용
- 백업: 마이그레이션 전 자동 백업 (`tasks.db.bak.{timestamp}`)
- 수동 롤백: `uv run alembic downgrade -1`

---

## 기술 스택

- Python 3.10+ / FastAPI / SQLModel / Alembic
- 순수 HTML/CSS/JS 프론트엔드 (빌드 불필요, CDN 불필요)
- SQLite (설정 없이 바로 사용)
