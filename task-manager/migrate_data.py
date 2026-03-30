#!/usr/bin/env python3
"""
데이터 마이그레이션 스크립트

이전 버전(워크스페이스 없음)의 DB를 새 버전으로 마이그레이션합니다.

동작:
  1. DB 백업 생성
  2. Alembic 마이그레이션 실행 (workspace 테이블 + workspace_id 컬럼 추가)
  3. 기존 데이터(workspace_id=NULL)를 기본 워크스페이스로 이동
  4. 기존 사용자 전원을 해당 워크스페이스 멤버로 등록

사용법:
  python migrate_data.py                              # 기본 (tasks.db)
  python migrate_data.py --db /path/to/tasks.db       # 특정 DB
  python migrate_data.py --workspace-name "디자인팀"   # 워크스페이스 이름 지정
  python migrate_data.py --dry-run                     # 실제 변경 없이 미리보기
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def log(msg):
    print(f"  {msg}")


def ok(msg):
    print(f"  {GREEN}OK{RESET} {msg}")


def fail(msg):
    print(f"  {RED}FAIL{RESET} {msg}")


def warn(msg):
    print(f"  {YELLOW}!{RESET} {msg}")


def section(title):
    print(f"\n{BOLD}{'─' * 50}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─' * 50}{RESET}")


def get_db_stats(conn: sqlite3.Connection) -> dict:
    """기존 데이터 현황 조회."""
    stats = {}
    tables_to_check = {
        "user": "사용자",
        "boardcolumn": "컬럼",
        "task": "태스크",
        "taskhistory": "변동 히스토리",
        "reporttemplate": "리포트 템플릿",
        "comment": "댓글",
        "notification": "알림",
    }
    existing_tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table, label in tables_to_check.items():
        if table in existing_tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            stats[table] = {"label": label, "count": count}
    return stats


def check_needs_migration(conn: sqlite3.Connection) -> dict:
    """어떤 마이그레이션이 필요한지 확인."""
    result = {
        "needs_schema": False,
        "needs_data": False,
        "has_workspace_table": False,
        "has_workspace_id_columns": False,
        "null_data_counts": {},
    }

    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    # 1. workspace 테이블 존재 여부
    result["has_workspace_table"] = "workspace" in tables

    if not result["has_workspace_table"]:
        result["needs_schema"] = True

    # 2. workspace_id 컬럼 존재 여부
    ws_tables = ["boardcolumn", "task", "taskhistory", "reporttemplate"]
    cols_found = 0
    for table in ws_tables:
        if table not in tables:
            continue
        cols = [
            r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        if "workspace_id" in cols:
            cols_found += 1
            # NULL 데이터 수
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL"
            ).fetchone()[0]
            if null_count > 0:
                result["null_data_counts"][table] = null_count
                result["needs_data"] = True
        else:
            result["needs_schema"] = True

    result["has_workspace_id_columns"] = cols_found == len(ws_tables)

    return result


def run_schema_migration(db_path: Path) -> bool:
    """Alembic 마이그레이션으로 스키마 업그레이드."""
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
        return True
    # Already at heads?
    if "already" in result.stderr.lower():
        return True
    print(f"    stderr: {result.stderr[:300]}")
    return False


def migrate_data(
    db_path: Path,
    workspace_name: str,
    dry_run: bool = False,
) -> bool:
    """기존 NULL 데이터를 워크스페이스에 할당."""
    db_path = db_path.resolve()
    conn = sqlite3.connect(str(db_path))

    # ── 1. 현황 파악 ────────────────────────────
    section("1. 현재 데이터 현황")
    stats = get_db_stats(conn)
    for table, info in stats.items():
        log(f"{info['label']} ({table}): {info['count']}건")

    if all(info["count"] == 0 for info in stats.values()):
        ok("데이터가 없습니다. 마이그레이션 불필요.")
        conn.close()
        return True

    # ── 2. 마이그레이션 필요 여부 ────────────────
    section("2. 마이그레이션 진단")
    check = check_needs_migration(conn)

    if check["has_workspace_table"]:
        ok("workspace 테이블 존재")
    else:
        warn("workspace 테이블 없음 → 스키마 마이그레이션 필요")

    if check["has_workspace_id_columns"]:
        ok("workspace_id 컬럼 존재")
    else:
        warn("workspace_id 컬럼 없음 → 스키마 마이그레이션 필요")

    if check["null_data_counts"]:
        for table, count in check["null_data_counts"].items():
            warn(f"{table}: workspace_id=NULL 데이터 {count}건 → 이동 필요")
    elif not check["needs_schema"]:
        ok("모든 데이터에 workspace_id가 할당됨. 마이그레이션 불필요.")
        conn.close()
        return True

    if not check["needs_schema"] and not check["needs_data"]:
        ok("마이그레이션 불필요.")
        conn.close()
        return True

    conn.close()

    # ── 3. DB 백업 ──────────────────────────────
    section("3. 데이터베이스 백업")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_suffix(f".db.pre_workspace.{timestamp}")

    if dry_run:
        log(f"[DRY RUN] 백업 생성 예정: {backup_path}")
    else:
        shutil.copy2(db_path, backup_path)
        ok(f"백업 생성: {backup_path}")

    # ── 4. 스키마 마이그레이션 ──────────────────
    if check["needs_schema"]:
        section("4. 스키마 마이그레이션 (Alembic)")
        if dry_run:
            log("[DRY RUN] alembic upgrade heads 실행 예정")
        else:
            if run_schema_migration(db_path):
                ok("스키마 마이그레이션 완료")
            else:
                fail("스키마 마이그레이션 실패")
                warn(f"백업에서 복원하세요: cp {backup_path} {db_path}")
                return False
    else:
        section("4. 스키마 마이그레이션 (불필요 — 스킵)")

    # ── 5. 데이터 마이그레이션 ──────────────────
    section("5. 데이터 마이그레이션")

    conn = sqlite3.connect(str(db_path))

    # 기본 워크스페이스 생성
    # owner는 첫 번째 사용자 (없으면 0)
    first_user = conn.execute(
        "SELECT id, nickname FROM user ORDER BY id LIMIT 1"
    ).fetchone()
    owner_id = first_user[0] if first_user else 0
    owner_name = first_user[1] if first_user else "(없음)"

    log(f"워크스페이스 이름: {workspace_name}")
    log(f"소유자: {owner_name} (id={owner_id})")

    if dry_run:
        log(f"[DRY RUN] 워크스페이스 '{workspace_name}' 생성 예정")
    else:
        # 이미 같은 이름의 워크스페이스가 있는지 확인
        existing_ws = conn.execute(
            "SELECT id FROM workspace WHERE name = ?", (workspace_name,)
        ).fetchone()

        if existing_ws:
            ws_id = existing_ws[0]
            ok(f"기존 워크스페이스 재사용: id={ws_id}")
        else:
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO workspace (name, description, owner_id, created_at) VALUES (?, ?, ?, ?)",
                (workspace_name, "이전 버전 데이터에서 마이그레이션됨", owner_id, now),
            )
            ws_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            ok(f"워크스페이스 생성: id={ws_id}")

            # 기본 컬럼 생성 (workspace용) — NULL 컬럼이 이동되므로 별도 생성 불필요
            # (기존 boardcolumn이 이동됨)

    # 모든 사용자를 워크스페이스 멤버로 등록
    users = conn.execute("SELECT id, nickname FROM user ORDER BY id").fetchall()
    if dry_run:
        log(f"[DRY RUN] 사용자 {len(users)}명 멤버 등록 예정")
    else:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        for uid, uname in users:
            existing_member = conn.execute(
                "SELECT id FROM workspacemember WHERE workspace_id = ? AND user_id = ?",
                (ws_id, uid),
            ).fetchone()
            if not existing_member:
                conn.execute(
                    "INSERT INTO workspacemember (workspace_id, user_id, joined_at) VALUES (?, ?, ?)",
                    (ws_id, uid, now),
                )
        ok(f"사용자 {len(users)}명 멤버 등록 완료")

    # NULL 데이터를 워크스페이스에 할당
    tables_to_migrate = ["boardcolumn", "task", "taskhistory", "reporttemplate"]
    for table in tables_to_migrate:
        if dry_run:
            # dry-run에서는 스키마 마이그레이션을 안 했으므로 workspace_id 컬럼이 없을 수 있음
            # 전체 행 수를 이동 대상으로 표시
            if check["needs_schema"]:
                total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                log(f"[DRY RUN] {table}: {total}건 → 워크스페이스에 할당 예정")
            else:
                null_count = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL"
                ).fetchone()[0]
                if null_count == 0:
                    log(f"{table}: 이동할 데이터 없음")
                else:
                    log(f"[DRY RUN] {table}: {null_count}건 → workspace_id 할당 예정")
        else:
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL"
            ).fetchone()[0]
            if null_count == 0:
                log(f"{table}: 이동할 데이터 없음")
                continue
            conn.execute(
                f"UPDATE {table} SET workspace_id = ? WHERE workspace_id IS NULL",
                (ws_id,),
            )
            ok(f"{table}: {null_count}건 → workspace_id={ws_id}")

    if not dry_run:
        conn.commit()
    conn.close()

    # ── 6. 검증 ─────────────────────────────────
    if not dry_run:
        section("6. 마이그레이션 검증")
        conn = sqlite3.connect(str(db_path))

        # NULL 데이터가 남아있는지 확인
        all_clear = True
        for table in tables_to_migrate:
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL"
            ).fetchone()[0]
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if null_count == 0:
                ok(f"{table}: 전체 {total}건 — workspace_id 할당 완료")
            else:
                fail(f"{table}: {null_count}건이 아직 NULL")
                all_clear = False

        # 워크스페이스 멤버 확인
        member_count = conn.execute(
            "SELECT COUNT(*) FROM workspacemember WHERE workspace_id = ?",
            (ws_id,),
        ).fetchone()[0]
        ok(f"워크스페이스 멤버: {member_count}명")

        conn.close()

        if all_clear:
            section("결과")
            print(f"\n  {GREEN}{BOLD}마이그레이션 완료!{RESET}")
            print(f"  워크스페이스 '{workspace_name}' (id={ws_id})에 모든 데이터가 이동되었습니다.")
            print(f"  백업: {backup_path}")
            print(f"\n  서버를 재시작하면 기존 데이터가 워크스페이스 안에서 보입니다.\n")
        else:
            warn("일부 데이터가 마이그레이션되지 않았습니다.")
            warn(f"문제 발생 시 백업에서 복원: cp {backup_path} {db_path}")

        return all_clear

    else:
        section("결과 (DRY RUN)")
        print(f"\n  {CYAN}실제 변경은 없습니다. --dry-run 없이 다시 실행하세요.{RESET}\n")
        return True


def main():
    parser = argparse.ArgumentParser(
        description="이전 버전 DB → 워크스페이스 데이터 마이그레이션",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python migrate_data.py                              # 기본 실행
  python migrate_data.py --dry-run                    # 미리보기 (변경 없음)
  python migrate_data.py --workspace-name "디자인팀"   # 이름 지정
  python migrate_data.py --db /old/tasks.db           # 다른 DB 파일
        """,
    )
    parser.add_argument("--db", type=str, default=None, help="마이그레이션할 DB 파일 경로")
    parser.add_argument("--workspace-name", type=str, default="Default Workspace",
                        help="기존 데이터를 넣을 워크스페이스 이름 (기본: Default Workspace)")
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 변경 없이 마이그레이션 계획만 출력")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else BASE_DIR / "tasks.db"

    print(f"\n{BOLD}Task Manager 데이터 마이그레이션{RESET}")
    print("=" * 50)
    print(f"DB: {db_path}")
    if args.dry_run:
        print(f"{CYAN}[DRY RUN 모드 — 실제 변경 없음]{RESET}")

    if not db_path.exists():
        print(f"\n{RED}DB 파일을 찾을 수 없습니다: {db_path}{RESET}")
        sys.exit(1)

    success = migrate_data(db_path, args.workspace_name, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
