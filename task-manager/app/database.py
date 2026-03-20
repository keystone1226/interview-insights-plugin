"""Database connection and migration utilities."""

import shutil
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlmodel import Session, SQLModel, create_engine

from app.config import BASE_DIR, DATABASE_URL, DB_PATH

engine = create_engine(DATABASE_URL, echo=False)


def get_session():
    with Session(engine) as session:
        yield session


def _get_alembic_config() -> Config:
    alembic_ini = BASE_DIR / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(BASE_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def backup_database() -> str | None:
    """Backup the database file before migration."""
    if not DB_PATH.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.with_suffix(f".db.bak.{timestamp}")
    shutil.copy2(DB_PATH, backup_path)
    print(f"  DB backup: {backup_path}")
    return str(backup_path)


def run_migrations():
    """Run Alembic migrations automatically on startup."""
    print("Checking database migrations...")
    backup_database()
    try:
        config = _get_alembic_config()
        command.upgrade(config, "heads")
        print("  Database is up to date.")
    except Exception as e:
        print(f"  Migration warning: {e}")
        print("  Attempting to stamp current state...")
        try:
            config = _get_alembic_config()
            command.stamp(config, "heads")
            print("  Database stamped at current heads.")
        except Exception as e2:
            print(f"  Stamp also failed: {e2}")
            print("  Continuing anyway – tables may already exist.")


def init_default_columns(session: Session):
    """Create default board columns if none exist."""
    from app.models import BoardColumn

    existing = session.query(BoardColumn).first()
    if existing:
        return
    defaults = [
        BoardColumn(name="TODO", sort_order=0, color="#6B7280"),
        BoardColumn(name="IN_PROGRESS", sort_order=1, color="#3B82F6"),
        BoardColumn(name="REVIEW", sort_order=2, color="#F59E0B"),
        BoardColumn(name="DONE", sort_order=3, color="#10B981"),
    ]
    for col in defaults:
        session.add(col)
    session.commit()
    print("  Default board columns created.")
