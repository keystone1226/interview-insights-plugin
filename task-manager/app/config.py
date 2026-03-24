"""Application configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from project root (task-manager/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "tasks.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"

# SMTP settings (optional - email notifications only work when configured)
SMTP_HOST = os.getenv("TASK_SMTP_HOST", "")
SMTP_PORT = int(os.getenv("TASK_SMTP_PORT", "25"))
SMTP_FROM = os.getenv("TASK_SMTP_FROM", "taskmanager@local")
SMTP_USER = os.getenv("TASK_SMTP_USER", "")
SMTP_PASSWORD = os.getenv("TASK_SMTP_PASSWORD", "")

# Server settings
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000

# SDS LLM API settings
LLM_ENDPOINT = os.getenv(
    "TASK_LLM_ENDPOINT",
    "https://nsds-api.fabrix-s.samsungsds.com/sds/prod/api-llm/v1",
)
LLM_CLIENT_KEY = os.getenv("TASK_LLM_CLIENT_KEY", "")
LLM_PASS_KEY = os.getenv("TASK_LLM_PASS_KEY", "")
LLM_MODEL = os.getenv("TASK_LLM_MODEL", "gpt-oss-120b")
LLM_MODEL_ID = os.getenv("TASK_LLM_MODEL_ID", "")
