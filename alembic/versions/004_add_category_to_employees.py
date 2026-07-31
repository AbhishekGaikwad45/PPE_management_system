"""Add category column to employees table.

Revision ID: 004_add_category_to_employees
Revises: 003_add_logs_mail
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '004_add_category_to_employees'
down_revision: Union[str, None] = '003_add_logs_mail'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Category synced from SQL Server HR views (MBC / MANPOWER BASED).
    # Only rows matching a valid category are synced in from HR; existing
    # rows default to '' until the next sync run populates them.
    op.execute('''
        ALTER TABLE employees
        ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT ''
    ''')


def downgrade() -> None:
    op.execute('ALTER TABLE employees DROP COLUMN IF EXISTS category')