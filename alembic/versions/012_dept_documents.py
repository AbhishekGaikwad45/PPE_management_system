"""Add department_documents table

Revision ID: 012_dept_documents
Revises: 011_add_module_permissions_table
Create Date: 2026-10-13
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '012_dept_documents'
down_revision: Union[str, None] = '011_add_module_permissions_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS department_documents (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(100) DEFAULT 'General',
            department VARCHAR(100) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            stored_filename VARCHAR(255) NOT NULL,
            file_path TEXT NOT NULL,
            file_size_bytes BIGINT DEFAULT 0,
            file_type VARCHAR(100),
            uploaded_by VARCHAR(100),
            uploaded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_dept_docs_dept ON department_documents(department);
        CREATE INDEX IF NOT EXISTS idx_dept_docs_deleted ON department_documents(is_deleted);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS department_documents;")
