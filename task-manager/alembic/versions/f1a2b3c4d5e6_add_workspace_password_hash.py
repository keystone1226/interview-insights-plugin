"""add workspace password_hash column

Revision ID: f1a2b3c4d5e6
Revises: d404a698e810
Create Date: 2026-04-13 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "d404a698e810"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite: nullable column add is safe without batch mode.
    op.add_column(
        "workspace",
        sa.Column(
            "password_hash",
            sqlmodel.sql.sqltypes.AutoString(length=200),
            nullable=True,
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("workspace") as batch_op:
        batch_op.drop_column("password_hash")
