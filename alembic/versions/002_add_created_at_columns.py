"""Add created_at to tables that existed before timestamp columns.

Revision ID: 002_add_created_at
Revises: 001_initial_schema
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '002_add_created_at'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES_WITH_CREATED_AT = [
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
]


def upgrade() -> None:
    for table in TABLES_WITH_CREATED_AT:
        op.add_column(
            table,
            sa.Column(
                'created_at',
                sa.TIMESTAMP(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table in reversed(TABLES_WITH_CREATED_AT):
        op.drop_column(table, 'created_at')
