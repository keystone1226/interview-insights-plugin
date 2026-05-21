"""Add task relations, external users, comment updated_at

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-21
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # User: add is_external flag
    op.add_column("user", sa.Column("is_external", sa.Boolean(), server_default=sa.text("0"), nullable=False))

    # Comment: add updated_at for edit tracking
    op.add_column("comment", sa.Column("updated_at", sa.DateTime(), nullable=True))

    # TaskRelation: parent-child linkage
    op.create_table(
        "taskrelation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("task.id"), nullable=False, index=True),
        sa.Column("child_id", sa.Integer(), sa.ForeignKey("task.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("parent_id", "child_id", name="uq_task_relation"),
    )


def downgrade() -> None:
    op.drop_table("taskrelation")
    op.drop_column("comment", "updated_at")
    op.drop_column("user", "is_external")
