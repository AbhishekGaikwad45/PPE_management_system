"""Add assigned_departments column to users table.

Revision ID: 006_assigned_departments
Revises: 005_add_dept_to_items
Create Date: 2026-08-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '006_assigned_departments'
down_revision: Union[str, None] = '005_add_dept_to_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS assigned_departments TEXT[] DEFAULT NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS assigned_departments")
