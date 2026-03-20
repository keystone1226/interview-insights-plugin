"""FastAPI application entry point."""

import argparse
import socket

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from sqlmodel import Session

from app.config import DEFAULT_HOST, DEFAULT_PORT, UPLOAD_DIR
from app.database import engine, init_default_columns, run_migrations
from app.routers import columns, comments, notifications, reports, tasks, users

app = FastAPI(title="Task Manager", version="0.1.0")

# Mount routers
app.include_router(users.router)
app.include_router(tasks.router)
app.include_router(comments.router)
app.include_router(notifications.router)
app.include_router(columns.router)
app.include_router(reports.router)

# Mount static files
STATIC_DIR = str(__file__.replace("main.py", "") + "static")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.on_event("startup")
def on_startup():
    run_migrations()
    with Session(engine) as session:
        init_default_columns(session)


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR + "/index.html")


@app.get("/style.css")
async def serve_css():
    return FileResponse(STATIC_DIR + "/style.css", media_type="text/css")


@app.get("/app.js")
async def serve_js():
    return FileResponse(STATIC_DIR + "/app.js", media_type="application/javascript")


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


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
