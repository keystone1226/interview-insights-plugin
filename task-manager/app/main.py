"""FastAPI application entry point."""

import argparse
import getpass
import shutil
import socket
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.config import DB_PATH, DEFAULT_HOST, DEFAULT_PORT, UPLOAD_DIR
from app.database import engine, init_default_columns, run_migrations
from app.routers import columns, comments, notifications, relations, reports, tasks, users, workspaces

# Resolve directories using Path for cross-platform compatibility
STATIC_DIR = Path(__file__).resolve().parent / "static"
README_PATH = Path(__file__).resolve().parent.parent / "README.md"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle handler."""
    try:
        run_migrations()
    except Exception as e:
        print(f"  Migration error (non-fatal): {e}")
    try:
        with Session(engine) as session:
            init_default_columns(session)
    except Exception as e:
        print(f"  Column init error (non-fatal): {e}")
    yield


app = FastAPI(title="Task Manager", version="0.1.0", lifespan=lifespan)

# Mount routers
app.include_router(users.router)
app.include_router(workspaces.router)
app.include_router(tasks.router)
app.include_router(comments.router)
app.include_router(notifications.router)
app.include_router(columns.router)
app.include_router(reports.router)
app.include_router(relations.router)

# Mount static files
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.api_route("/", methods=["GET", "HEAD"])
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/style.css")
async def serve_css():
    resp = FileResponse(STATIC_DIR / "style.css", media_type="text/css")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/app.js")
async def serve_js():
    resp = FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/api/help")
async def serve_help():
    """Serve README.md content for the in-app help modal."""
    if README_PATH.exists():
        return PlainTextResponse(README_PATH.read_text(encoding="utf-8"))
    return PlainTextResponse("도움말 파일을 찾을 수 없습니다.", status_code=404)


# ── DB File Backup / Restore ────────────────────


@app.get("/api/backup/db")
async def download_db():
    """Download the raw SQLite DB file."""
    if not DB_PATH.exists():
        return Response(status_code=404)
    filename = f"tasks_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    return FileResponse(
        DB_PATH,
        media_type="application/octet-stream",
        filename=filename,
    )


@app.post("/api/backup/db")
async def upload_db(file: UploadFile = File(...)):
    """Upload a SQLite DB file to replace the current one.

    Creates a backup of the current DB before overwriting.
    The server must be restarted after this operation.
    """
    # Validate: must be a SQLite file
    header = await file.read(16)
    await file.seek(0)
    if header[:6] != b"SQLite":
        return Response(
            status_code=400,
            content='{"detail":"유효한 SQLite 파일이 아닙니다."}',
            media_type="application/json",
        )

    # Backup current DB
    if DB_PATH.exists():
        backup_name = DB_PATH.with_suffix(
            f".db.before_restore.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy2(DB_PATH, backup_name)

    # Write uploaded file
    content = await file.read()
    DB_PATH.write_bytes(content)

    return {
        "ok": True,
        "message": "DB 파일 복원 완료. 서버를 재시작하세요.",
        "size": len(content),
    }


def get_local_ip() -> str:
    """Detect the local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _run_server(host: str, port: int) -> None:
    local_ip = get_local_ip()
    print()
    print("=" * 50)
    print("  Task Manager")
    print("=" * 50)
    print(f"  Local:   http://127.0.0.1:{port}")
    print(f"  Network: http://{local_ip}:{port}")
    print()
    print("  Share the Network URL with your team!")
    print("=" * 50)
    print()

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
    )


# ── Admin CLI commands ─────────────────────────


def _ensure_db_ready() -> None:
    """Run migrations up to head. Needed because CLI commands bypass
    the FastAPI lifespan where migrations normally run."""
    try:
        run_migrations()
    except Exception as e:
        print(f"  Migration error (non-fatal): {e}")


def _cmd_list_workspaces() -> int:
    """Print all workspaces with their password hash info."""
    from sqlmodel import Session, select

    from app.models import User, Workspace

    _ensure_db_ready()

    with Session(engine) as session:
        workspaces = session.exec(select(Workspace).order_by(Workspace.id)).all()
        if not workspaces:
            print("(no workspaces)")
            return 0

        print(f"{'ID':<5} {'NAME':<28} {'OWNER':<18} {'PASSWORD HASH'}")
        print("-" * 110)
        for ws in workspaces:
            owner = session.get(User, ws.owner_id) if ws.owner_id else None
            owner_label = owner.nickname if owner else f"#{ws.owner_id}"
            hash_display = ws.password_hash or "(none)"
            print(
                f"{ws.id:<5} {ws.name[:28]:<28} {owner_label[:18]:<18} {hash_display}"
            )
    return 0


def _cmd_stats() -> int:
    """Print self-hosted usage analytics (funnel, churn, engagement)."""
    from sqlmodel import Session

    from app.stats import compute_stats, format_stats

    _ensure_db_ready()

    with Session(engine) as session:
        stats = compute_stats(session, str(DB_PATH))
    print(format_stats(stats))
    return 0


def _cmd_reset_password(
    workspace_id: int,
    new_password: str | None,
    clear: bool,
) -> int:
    """Reset a single workspace's password.

    - ``clear=True`` wipes the password.
    - ``new_password`` is used directly if provided.
    - Otherwise prompts interactively with getpass (safer — no shell history).
    """
    from sqlmodel import Session

    from app.models import Workspace
    from app.routers.workspaces import _hash_password

    _ensure_db_ready()

    with Session(engine) as session:
        ws = session.get(Workspace, workspace_id)
        if not ws:
            print(f"Error: workspace id {workspace_id} not found.", file=sys.stderr)
            return 1

        old_hash = ws.password_hash or "(none)"

        if clear:
            ws.password_hash = None
            action = "cleared (no password)"
        else:
            if new_password is None:
                try:
                    pw1 = getpass.getpass(f"New password for '{ws.name}': ")
                    pw2 = getpass.getpass("Confirm: ")
                except (EOFError, KeyboardInterrupt):
                    print("\nAborted.", file=sys.stderr)
                    return 1
                if pw1 != pw2:
                    print("Passwords do not match.", file=sys.stderr)
                    return 1
                new_password = pw1

            if not new_password or len(new_password) < 4:
                print("Password must be at least 4 characters.", file=sys.stderr)
                return 1

            ws.password_hash = _hash_password(new_password)
            action = f"set (length={len(new_password)})"

        session.add(ws)
        session.commit()

        print(f"Workspace #{workspace_id} '{ws.name}': password {action}")
        print(f"  Old hash: {old_hash}")
        print(f"  New hash: {ws.password_hash or '(none)'}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Lightweight Task Manager (server + admin CLI)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # run (default): start the web server
    run_parser = subparsers.add_parser("run", help="Run the web server (default)")
    run_parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    run_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")

    # list-workspaces
    subparsers.add_parser(
        "list-workspaces",
        help="List all workspaces with their password_hash column value",
    )

    # stats: print usage analytics (funnel / churn / engagement)
    subparsers.add_parser(
        "stats",
        help="Print self-hosted usage analytics read from the local DB",
    )

    # reset-password <workspace_id>
    reset_parser = subparsers.add_parser(
        "reset-password",
        help="Reset a workspace password (interactive prompt by default)",
    )
    reset_parser.add_argument("workspace_id", type=int, help="Workspace ID to reset")
    reset_parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear the password (no password required to join).",
    )
    reset_parser.add_argument(
        "--new-password",
        default=None,
        help="Set this password directly (visible in shell history — prefer interactive).",
    )

    # Backwards compatibility: `python -m app --host X --port Y` (no subcommand)
    # We only register --host/--port on the top-level parser if no subcommand is given.
    if len(sys.argv) > 1 and sys.argv[1] in {"run", "list-workspaces", "reset-password", "stats", "-h", "--help"}:
        args = parser.parse_args()
    else:
        legacy = argparse.ArgumentParser(description="Lightweight Task Manager")
        legacy.add_argument("--host", default=DEFAULT_HOST)
        legacy.add_argument("--port", type=int, default=DEFAULT_PORT)
        legacy_args = legacy.parse_args()
        _run_server(legacy_args.host, legacy_args.port)
        return

    if args.command == "list-workspaces":
        sys.exit(_cmd_list_workspaces())
    if args.command == "stats":
        sys.exit(_cmd_stats())
    if args.command == "reset-password":
        sys.exit(
            _cmd_reset_password(
                workspace_id=args.workspace_id,
                new_password=args.new_password,
                clear=args.clear,
            )
        )

    # Default (`run` or unspecified): start server.
    _run_server(
        getattr(args, "host", DEFAULT_HOST),
        getattr(args, "port", DEFAULT_PORT),
    )


if __name__ == "__main__":
    main()
