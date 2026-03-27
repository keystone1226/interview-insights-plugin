"""Alembic environment configuration."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from app.models import (  # noqa: F401 - ensure all models are registered
    BoardColumn,
    Comment,
    Notification,
    ReportTemplate,
    Task,
    TaskHistory,
    User,
    Workspace,
    WorkspaceMember,
)

config = context.config

# Allow overriding sqlalchemy.url via -x flag (for sandbox testing)
cmd_opts = context.get_x_argument(as_dictionary=True)
if "sqlalchemy.url" in cmd_opts:
    config.set_main_option("sqlalchemy.url", cmd_opts["sqlalchemy.url"])
else:
    from app.config import DATABASE_URL
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
