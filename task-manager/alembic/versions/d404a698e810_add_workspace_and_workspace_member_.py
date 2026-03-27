"""add workspace and workspace_member tables and workspace_id columns

Revision ID: d404a698e810
Revises: e4da44753596
Create Date: 2026-03-27 01:09:43.282816
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd404a698e810'
down_revision: Union[str, None] = 'e4da44753596'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create workspace table
    op.create_table(
        'workspace',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workspace_name'), 'workspace', ['name'], unique=False)

    # Create workspace_member table
    op.create_table(
        'workspacemember',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workspacemember_user_id'), 'workspacemember', ['user_id'], unique=False)
    op.create_index(op.f('ix_workspacemember_workspace_id'), 'workspacemember', ['workspace_id'], unique=False)

    # Add workspace_id column to existing tables
    # Using direct ADD COLUMN (safe for nullable columns in SQLite, no batch needed)
    op.add_column('boardcolumn', sa.Column('workspace_id', sa.Integer(), nullable=True))
    op.add_column('task', sa.Column('workspace_id', sa.Integer(), nullable=True))
    op.add_column('taskhistory', sa.Column('workspace_id', sa.Integer(), nullable=True))
    op.add_column('reporttemplate', sa.Column('workspace_id', sa.Integer(), nullable=True))

    # Create indexes (SQLite supports CREATE INDEX without batch)
    op.create_index('ix_boardcolumn_workspace_id', 'boardcolumn', ['workspace_id'])
    op.create_index('ix_task_workspace_id', 'task', ['workspace_id'])
    op.create_index('ix_taskhistory_workspace_id', 'taskhistory', ['workspace_id'])
    op.create_index('ix_reporttemplate_workspace_id', 'reporttemplate', ['workspace_id'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_reporttemplate_workspace_id', table_name='reporttemplate')
    op.drop_index('ix_taskhistory_workspace_id', table_name='taskhistory')
    op.drop_index('ix_task_workspace_id', table_name='task')
    op.drop_index('ix_boardcolumn_workspace_id', table_name='boardcolumn')

    # Drop columns (SQLite batch mode needed for DROP COLUMN)
    with op.batch_alter_table('reporttemplate') as batch_op:
        batch_op.drop_column('workspace_id')
    with op.batch_alter_table('taskhistory') as batch_op:
        batch_op.drop_column('workspace_id')
    with op.batch_alter_table('task') as batch_op:
        batch_op.drop_column('workspace_id')
    with op.batch_alter_table('boardcolumn') as batch_op:
        batch_op.drop_column('workspace_id')

    # Drop new tables
    op.drop_index(op.f('ix_workspacemember_workspace_id'), table_name='workspacemember')
    op.drop_index(op.f('ix_workspacemember_user_id'), table_name='workspacemember')
    op.drop_table('workspacemember')
    op.drop_index(op.f('ix_workspace_name'), table_name='workspace')
    op.drop_table('workspace')
