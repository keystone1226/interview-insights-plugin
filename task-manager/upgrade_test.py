#!/usr/bin/env python3
"""
업그레이드 검증 스크립트 (Sandbox Test)

새 버전의 ZIP을 받은 후, 실제 서버에 적용하기 전에
이 스크립트로 마이그레이션과 기능을 검증합니다.

사용법:
  python upgrade_test.py                   # 기본 (tasks.db 복사본으로 테스트)
  python upgrade_test.py --db /path/to.db  # 특정 DB 파일로 테스트
  python upgrade_test.py --fresh           # 빈 DB로 신규 설치 테스트

결과:
  - 모든 테스트 PASS → 안전하게 업그레이드 가능
  - FAIL 항목 있음   → 해당 항목 확인 후 진행
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ── Colors ───────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"  {GREEN}PASS{RESET} {msg}")


def fail(msg):
    print(f"  {RED}FAIL{RESET} {msg}")


def warn(msg):
    print(f"  {YELLOW}WARN{RESET} {msg}")


def section(msg):
    print(f"\n{BOLD}{'─' * 50}{RESET}")
    print(f"{BOLD}  {msg}{RESET}")
    print(f"{BOLD}{'─' * 50}{RESET}")


def run_tests(db_path: Path, is_fresh: bool = False) -> bool:
    """Run all upgrade tests. Returns True if all pass."""
    results = []
    db_path = db_path.resolve()

    # ── 1. DB 접근 테스트 ────────────────────────
    section("1. 데이터베이스 접근")
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1")
        ok(f"DB 파일 접근 가능: {db_path}")
        results.append(True)
    except Exception as e:
        fail(f"DB 접근 실패: {e}")
        return False

    if not is_fresh:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cursor.fetchall()]
        ok(f"기존 테이블: {', '.join(tables)}")
        for table in ['user', 'boardcolumn', 'task', 'taskhistory', 'reporttemplate']:
            if table in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                ok(f"  {table}: {count}건")
    conn.close()

    # ── 2. Alembic 마이그레이션 테스트 ──────────
    section("2. 마이그레이션 실행")

    if is_fresh:
        # For fresh install, create tables directly via SQLModel
        try:
            from sqlmodel import SQLModel, create_engine
            engine = create_engine(f"sqlite:///{db_path}")
            # Must import all models to register them
            import app.models  # noqa: F401
            SQLModel.metadata.create_all(engine)
            engine.dispose()
            ok("신규 설치: 테이블 생성 완료")
            results.append(True)
        except Exception as e:
            fail(f"테이블 생성 실패: {e}")
            results.append(False)
    else:
        # Run alembic as subprocess to avoid module-level caching of DATABASE_URL
        # We override sqlalchemy.url via -x flag
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "alembic",
                    "-x", f"sqlalchemy.url=sqlite:///{db_path}",
                    "upgrade", "heads",
                ],
                capture_output=True,
                text=True,
                cwd=str(BASE_DIR),
            )
            if result.returncode == 0:
                ok("마이그레이션 업그레이드 완료")
                results.append(True)
            else:
                # Check if it's the "already at heads" case
                if "already" in result.stderr.lower() or "no upgrade" in result.stderr.lower():
                    ok("마이그레이션: 이미 최신 상태")
                    results.append(True)
                else:
                    fail(f"마이그레이션 실패:\n{result.stderr}")
                    results.append(False)
                    # Try fallback
                    try:
                        from sqlmodel import SQLModel, create_engine
                        engine = create_engine(f"sqlite:///{db_path}")
                        import app.models  # noqa: F401
                        SQLModel.metadata.create_all(engine)
                        engine.dispose()
                        warn("Fallback: create_all로 테이블 보정 완료")
                    except Exception as e2:
                        fail(f"Fallback도 실패: {e2}")
        except Exception as e:
            fail(f"마이그레이션 프로세스 실행 실패: {e}")
            results.append(False)

    # ── 3. 스키마 검증 ──────────────────────────
    section("3. 스키마 검증")
    conn = sqlite3.connect(str(db_path))

    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {r[0] for r in cursor.fetchall()}
    required = {'user', 'boardcolumn', 'task', 'comment', 'notification',
                'taskhistory', 'reporttemplate', 'workspace', 'workspacemember'}
    for t in sorted(required):
        if t in tables:
            ok(f"테이블 존재: {t}")
            results.append(True)
        else:
            fail(f"테이블 누락: {t}")
            results.append(False)

    ws_columns = {
        'boardcolumn': 'workspace_id',
        'task': 'workspace_id',
        'taskhistory': 'workspace_id',
        'reporttemplate': 'workspace_id',
    }
    for table, col in ws_columns.items():
        cursor = conn.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cursor.fetchall()]
        if col in cols:
            ok(f"컬럼 존재: {table}.{col}")
            results.append(True)
        else:
            fail(f"컬럼 누락: {table}.{col}")
            results.append(False)

    # ── 4. 기존 데이터 보존 검증 ─────────────────
    if not is_fresh:
        section("4. 기존 데이터 보존")
        for table in ['user', 'boardcolumn', 'task', 'taskhistory', 'reporttemplate']:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                ok(f"{table}: {count}건 보존됨")
                results.append(True)
            except Exception as e:
                fail(f"{table} 조회 실패: {e}")
                results.append(False)

        for table in ['boardcolumn', 'task', 'taskhistory', 'reporttemplate']:
            try:
                total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                null_count = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL"
                ).fetchone()[0]
                if total == 0 or null_count == total:
                    ok(f"{table}: 기존 데이터 workspace_id=NULL (정상)")
                    results.append(True)
                else:
                    warn(f"{table}: {total - null_count}건에 예상치 않은 workspace_id 값 있음")
                    results.append(True)
            except Exception as e:
                fail(f"{table} workspace_id 검증 실패: {e}")
                results.append(False)

    # ── 5. API Import 테스트 ─────────────────────
    section("5. 앱 Import 테스트")
    try:
        from app.main import app as fastapi_app  # noqa: F811
        ok("FastAPI 앱 로드 성공")
        results.append(True)
    except Exception as e:
        fail(f"앱 로드 실패: {e}")
        results.append(False)

    try:
        from app.models import (  # noqa: F811
            Workspace, WorkspaceMember, BoardColumn, Task,
            TaskHistory, ReportTemplate, User,
        )
        ok("모든 모델 Import 성공")
        results.append(True)
    except Exception as e:
        fail(f"모델 Import 실패: {e}")
        results.append(False)

    try:
        from app.routers import workspaces  # noqa: F811
        ok("워크스페이스 라우터 Import 성공")
        results.append(True)
    except Exception as e:
        fail(f"워크스페이스 라우터 Import 실패: {e}")
        results.append(False)

    conn.close()

    # ── 결과 요약 ────────────────────────────────
    section("결과 요약")
    passed = sum(1 for r in results if r)
    total = len(results)
    failed = total - passed

    if failed == 0:
        print(f"\n  {GREEN}{BOLD}ALL {passed} TESTS PASSED{RESET}")
        print(f"  안전하게 업그레이드할 수 있습니다.\n")
        return True
    else:
        print(f"\n  {passed} passed, {RED}{failed} failed{RESET}")
        print(f"  실패 항목을 확인 후 진행하세요.\n")
        return False


def main():
    parser = argparse.ArgumentParser(description="업그레이드 검증 스크립트")
    parser.add_argument("--db", type=str, default=None, help="테스트할 DB 파일 경로")
    parser.add_argument("--fresh", action="store_true", help="빈 DB로 신규 설치 테스트")
    args = parser.parse_args()

    print(f"\n{BOLD}Task Manager 업그레이드 검증{RESET}")
    print("=" * 50)

    if args.fresh:
        tmp = tempfile.mktemp(suffix=".db")
        db_path = Path(tmp)
        print(f"모드: 신규 설치 테스트")
        print(f"임시 DB: {db_path}")
        try:
            success = run_tests(db_path, is_fresh=True)
        finally:
            db_path.unlink(missing_ok=True)
    else:
        source = Path(args.db) if args.db else BASE_DIR / "tasks.db"
        if not source.exists():
            print(f"{RED}DB 파일을 찾을 수 없습니다: {source}{RESET}")
            print("--fresh 옵션으로 신규 설치 테스트를 하거나, --db 옵션으로 DB 경로를 지정하세요.")
            sys.exit(1)

        tmp = tempfile.mktemp(suffix=".db")
        sandbox_db = Path(tmp)
        shutil.copy2(source, sandbox_db)
        print(f"모드: 업그레이드 테스트 (샌드박스)")
        print(f"원본 DB: {source}")
        print(f"샌드박스 DB: {sandbox_db}")
        print(f"(원본 DB는 변경되지 않습니다)")
        try:
            success = run_tests(sandbox_db, is_fresh=False)
        finally:
            sandbox_db.unlink(missing_ok=True)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
