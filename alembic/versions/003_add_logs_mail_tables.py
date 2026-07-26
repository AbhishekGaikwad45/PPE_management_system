"""Add audit_logs, error_logs, smtp_config, mail_queue tables.

Revision ID: 003_add_logs_mail
Revises: 002_add_created_at
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '003_add_logs_mail'
down_revision: Union[str, None] = '002_add_created_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Who did what (create / edit / delete) across the app
    op.execute('''
        CREATE TABLE audit_logs (
            id SERIAL PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            action TEXT NOT NULL,          -- create | edit | delete
            module TEXT NOT NULL,          -- e.g. 'users', 'items', 'stock'
            record_id TEXT,                -- id of the affected row (as text)
            description TEXT,              -- human readable summary
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('CREATE INDEX idx_audit_logs_created_at ON audit_logs (created_at)')
    op.execute('CREATE INDEX idx_audit_logs_module ON audit_logs (module)')

    # Unhandled exceptions / errors captured by the global Flask error handler
    op.execute('''
        CREATE TABLE error_logs (
            id SERIAL PRIMARY KEY,
            level TEXT NOT NULL DEFAULT 'ERROR',
            source TEXT,                   -- e.g. 'app:215'
            method TEXT,
            path TEXT,
            message TEXT,
            traceback TEXT,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('CREATE INDEX idx_error_logs_created_at ON error_logs (created_at)')

    # SMTP configuration - editable from the admin UI (single row table)
    op.execute('''
        CREATE TABLE smtp_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            host TEXT,
            port INTEGER DEFAULT 587,
            username TEXT,
            password TEXT,
            from_email TEXT,
            from_name TEXT,
            use_tls BOOLEAN NOT NULL DEFAULT TRUE,
            schedule_minutes INTEGER DEFAULT 5,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT smtp_config_single_row CHECK (id = 1)
        )
    ''')

    # Outgoing mail queue / history
    op.execute('''
        CREATE TABLE mail_queue (
            id SERIAL PRIMARY KEY,
            to_email TEXT NOT NULL,
            subject TEXT,
            body TEXT,
            status TEXT NOT NULL DEFAULT 'pending',   -- pending | sent | failed
            retries INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP
        )
    ''')
    op.execute('CREATE INDEX idx_mail_queue_status ON mail_queue (status)')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS mail_queue')
    op.execute('DROP TABLE IF EXISTS smtp_config')
    op.execute('DROP TABLE IF EXISTS error_logs')
    op.execute('DROP TABLE IF EXISTS audit_logs')
