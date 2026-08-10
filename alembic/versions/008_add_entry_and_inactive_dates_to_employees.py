"""Add entry_date and inactive_date columns to employees table.

Revision ID: 008_add_entry_and_inactive_dates
Revises: 007_add_is_deleted_columns
Create Date: 2026-08-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '008_add_entry_and_inactive_dates'
down_revision: Union[str, None] = '007_add_is_deleted_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure created_at exists on employees table
    op.execute("""
        ALTER TABLE employees
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """)

    # Add entry_date (date/timestamp when employee was created/entered)
    op.execute("""
        ALTER TABLE employees
        ADD COLUMN IF NOT EXISTS entry_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """)

    # Add inactive_date (timestamp when employee was set to Inactive)
    op.execute("""
        ALTER TABLE employees
        ADD COLUMN IF NOT EXISTS inactive_date TIMESTAMP DEFAULT NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS inactive_date")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS entry_date")
