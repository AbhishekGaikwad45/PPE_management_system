"""Add is_deleted column to existing tables including stock-related tables.

Revision ID: 007_add_is_deleted_columns
Revises: 006_assigned_departments
Create Date: 2026-08-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '007_add_is_deleted_columns'
down_revision: Union[str, None] = '006_assigned_departments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables to add the `is_deleted` column to (including stock-related and core domain tables)
TABLES = [
    'users',
    'role_permissions',
    'departments',
    'department_role_permissions',
    'contractors',
    'employees',
    'items',
    'stock_receipts',
    'issue_register',
    'contractor_issue_register',
    'contractor_alias_map',
    'return_register',
    'expiry_tracking',
    'calibration_tracking',
    'password_reset_otp',
    'audit_logs',
    'error_logs',
    'smtp_config',
    'mail_queue',
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
            ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
        """)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS is_deleted")
