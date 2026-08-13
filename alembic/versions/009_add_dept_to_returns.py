"""Add department column to return_register table.

Revision ID: 009_add_dept_to_returns
Revises: 008_add_entry_and_inactive_dates
Create Date: 2026-08-13
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '009_add_dept_to_returns'
down_revision: Union[str, None] = '008_add_entry_and_inactive_dates'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE return_register
        ADD COLUMN IF NOT EXISTS department TEXT DEFAULT NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE return_register DROP COLUMN IF EXISTS department")
