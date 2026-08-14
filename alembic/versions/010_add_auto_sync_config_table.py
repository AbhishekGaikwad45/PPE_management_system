"""
010_add_auto_sync_config_table.py

Revision ID: 010_add_auto_sync_config_table
Revises: 009_add_dept_to_returns
Create Date: 2026-08-14
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '010_add_auto_sync_config_table'
down_revision: Union[str, None] = '009_add_dept_to_returns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS auto_sync_config (
            id INT PRIMARY KEY DEFAULT 1,
            is_enabled BOOLEAN DEFAULT TRUE,
            sync_time VARCHAR(10) DEFAULT '00:00',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO auto_sync_config (id, is_enabled, sync_time)
        VALUES (1, TRUE, '00:00')
        ON CONFLICT (id) DO NOTHING;

        ALTER TABLE audit_logs
        ADD COLUMN IF NOT EXISTS department TEXT DEFAULT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS auto_sync_config;
        ALTER TABLE audit_logs DROP COLUMN IF EXISTS department;
    """)
