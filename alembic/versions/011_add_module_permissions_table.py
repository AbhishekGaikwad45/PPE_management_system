"""
011_add_module_permissions_table.py

Revision ID: 011_add_module_permissions_table
Revises: 010_add_auto_sync_config_table
Create Date: 2026-08-14
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '011_add_module_permissions_table'
down_revision: Union[str, None] = '010_add_auto_sync_config_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS module_permissions (
            id SERIAL PRIMARY KEY,
            department TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL,
            module TEXT NOT NULL,
            can_view BOOLEAN DEFAULT TRUE,
            can_create BOOLEAN DEFAULT FALSE,
            can_edit BOOLEAN DEFAULT FALSE,
            can_delete BOOLEAN DEFAULT FALSE,
            CONSTRAINT uq_dept_role_module UNIQUE (department, role, module)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS module_permissions;")
