"""Add added_by_department column to items table.

Revision ID: 005_add_dept_to_items
Revises: 004_add_category_to_employees
Create Date: 2026-08-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '005_add_dept_to_items'
down_revision: Union[str, None] = '004_add_category_to_employees'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add column — NULL means "added before this feature / visible to all"
    op.execute("""
        ALTER TABLE items
        ADD COLUMN IF NOT EXISTS added_by_department TEXT DEFAULT NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE items DROP COLUMN IF EXISTS added_by_department")
