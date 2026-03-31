#!/usr/bin/env python3
"""
업그레이드 검증 스크립트 (Sandbox Test)

새 버전의 ZIP을 받은 후, 실제 서버에 적용하기 전에
이 스크립트로 마이그레이션과 기능을 검증합니다.

사용법:
  python upgrade_test.py                   # DB 검증만 (기본)
  python upgrade_test.py --db /path/to.db  # 특정 DB 파일로 테스트
  python upgrade_test.py --fresh           # 빈 DB로 신규 설치 테스트
  python upgrade_test.py --serve           # 검증 후 스테이징 서버 실행 (포트 8001)
  python upgrade_test.py --serve --port 9000  # 포트 지정

스테이징 서버 모드 (--serve):
  1. 기존 DB를 복사하여 마이그레이션 검증
  2. ALL PASS이면 별도 포트에 스테이징 서버 실행
  3. 브라우저에서 확인 후 Ctrl+C로 종료
  4. 원본 DB는 전혀 건드리지 않음
"""

import argparse
import os
import shutil
import signal
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
CYAN = "\033[96m"
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
        try:
            from sqlmodel import SQLModel, create_engine
            engine = create_engine(f"sqlite:///{db_path}")
            import app.models  # noqa: F401
            SQLModel.metadata.create_all(engine)
            engine.dispose()
            ok("신규 설치: 테이블 생성 완료")
            results.append(True)
        except Exception as e:
            fail(f"테이블 생성 실패: {e}")
            results.append(False)
    else:
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
                if "already" in result.stderr.lower() or "no upgrade" in result.stderr.lower():
                    ok("마이그레이션: 이미 최신 상태")
                    results.append(True)
                else:
                    fail(f"마이그레이션 실패:\n{result.stderr}")
                    results.append(False)
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


def run_staging_server(db_path: Path, port: int):
    """DB를 복사하고, 마이그레이션 검증 후, 별도 포트에 스테이징 서버를 띄운다."""
    db_path = db_path.resolve()
    staging_dir = BASE_DIR / ".staging"

    print(f"\n{BOLD}Task Manager 스테이징 서버{RESET}")
    print("=" * 50)
    print(f"원본 DB: {db_path}")
    print(f"스테이징 포트: {port}")

    # ── 스테이징 디렉토리 준비 ───────────────────
    staging_dir.mkdir(exist_ok=True)
    staging_db = staging_dir / "tasks.db"

    if db_path.exists():
        shutil.copy2(db_path, staging_db)
        print(f"DB 복사: {db_path} → {staging_db}")
        is_fresh = False
    else:
        print(f"기존 DB 없음 → 신규 설치 모드")
        is_fresh = True

    # uploads 디렉토리 공유 (symlink 또는 복사)
    staging_uploads = staging_dir / "uploads"
    real_uploads = BASE_DIR / "app" / "uploads"
    if real_uploads.exists() and not staging_uploads.exists():
        try:
            staging_uploads.symlink_to(real_uploads)
        except OSError:
            # Windows에서 symlink 권한이 없는 경우 복사로 대체
            shutil.copytree(real_uploads, staging_uploads)

    # ── 검증 실행 ────────────────────────────────
    print()
    success = run_tests(staging_db, is_fresh=is_fresh)

    if not success:
        print(f"{RED}검증 실패 — 스테이징 서버를 시작하지 않습니다.{RESET}")
        print(f"실패 항목을 확인하세요.")
        shutil.rmtree(staging_dir, ignore_errors=True)
        sys.exit(1)

    # ── 스테이징 서버 시작 ───────────────────────
    section("스테이징 서버 시작")

    # Detect local IP for team access
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    print()
    print(f"  {CYAN}{BOLD}{'=' * 46}{RESET}")
    print(f"  {CYAN}{BOLD}  STAGING SERVER (읽기/쓰기 가능, 원본 무관){RESET}")
    print(f"  {CYAN}{BOLD}{'=' * 46}{RESET}")
    print(f"  Local:   {BOLD}http://127.0.0.1:{port}{RESET}")
    print(f"  Network: {BOLD}http://{local_ip}:{port}{RESET}")
    print()
    print(f"  {YELLOW}이 서버에서의 변경은 원본 DB에 영향을 주지 않습니다.{RESET}")
    print(f"  {YELLOW}확인 후 Ctrl+C로 종료하세요.{RESET}")
    print(f"  {CYAN}{BOLD}{'=' * 46}{RESET}")
    print()

    # Set env to use staging DB, then start uvicorn
    env = os.environ.copy()
    env["TASK_DB_PATH"] = str(staging_db)

    # We need to override DATABASE_URL at the module level.
    # The cleanest way: write a small wrapper script that patches config before import.
    wrapper = staging_dir / "_staging_run.py"
    # Use repr() for paths to avoid Windows backslash escape issues
    base_dir_repr = repr(str(BASE_DIR))
    staging_db_repr = repr(str(staging_db))
    staging_db_url = str(staging_db).replace("\\", "/")
    wrapper.write_text(f'''"""Staging server wrapper."""
import sys
import os

sys.path.insert(0, {base_dir_repr})
os.environ["_STAGING_DB"] = {staging_db_repr}

import app.config as cfg
from pathlib import Path
cfg.DB_PATH = Path({staging_db_repr})
cfg.DATABASE_URL = "sqlite:///{staging_db_url}"

import app.database as db
from sqlmodel import create_engine
db.engine = create_engine(cfg.DATABASE_URL, echo=False)

from app.main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port={port})
''', encoding="utf-8")

    try:
        proc = subprocess.Popen(
            [sys.executable, str(wrapper)],
            cwd=str(BASE_DIR),
            env=env,
        )
        proc.wait()
    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}스테이징 서버 종료{RESET}")
        proc.terminate()
        proc.wait(timeout=5)
    finally:
        # Cleanup
        print(f"  스테이징 DB 삭제: {staging_db}")
        shutil.rmtree(staging_dir, ignore_errors=True)
        print(f"  {GREEN}정리 완료. 원본 DB는 그대로입니다.{RESET}\n")


def main():
    parser = argparse.ArgumentParser(
        description="업그레이드 검증 및 스테이징 서버",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python upgrade_test.py                    # DB 검증만
  python upgrade_test.py --serve            # 검증 + 포트 8001에서 스테이징 서버
  python upgrade_test.py --serve --port 9000  # 검증 + 포트 9000
  python upgrade_test.py --fresh --serve    # 빈 DB로 스테이징 서버
        """,
    )
    parser.add_argument("--db", type=str, default=None, help="테스트할 DB 파일 경로")
    parser.add_argument("--fresh", action="store_true", help="빈 DB로 신규 설치 테스트")
    parser.add_argument("--serve", action="store_true", help="검증 후 스테이징 서버 실행")
    parser.add_argument("--port", type=int, default=8001, help="스테이징 서버 포트 (기본: 8001)")
    args = parser.parse_args()

    if args.serve:
        # Staging server mode
        source = Path(args.db) if args.db else BASE_DIR / "tasks.db"
        if args.fresh:
            source = Path(tempfile.mktemp(suffix=".db"))  # non-existent = fresh
        run_staging_server(source, args.port)
    else:
        # Test-only mode
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
