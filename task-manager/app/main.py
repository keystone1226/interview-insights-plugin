"""FastAPI application entry point."""

import argparse
import shutil
import socket
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.config import DB_PATH, DEFAULT_HOST, DEFAULT_PORT, UPLOAD_DIR
from app.database import engine, init_default_columns, run_migrations
from app.routers import columns, comments, notifications, reports, tasks, users, workspaces

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

# Mount static files
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/")
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


def main():
    parser = argparse.ArgumentParser(description="Lightweight Task Manager")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")
    args = parser.parse_args()

    local_ip = get_local_ip()
    print()
    print("=" * 50)
    print("  Task Manager")
    print("=" * 50)
    print(f"  Local:   http://127.0.0.1:{args.port}")
    print(f"  Network: http://{local_ip}:{args.port}")
    print()
    print("  Share the Network URL with your team!")
    print("=" * 50)
    print()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
