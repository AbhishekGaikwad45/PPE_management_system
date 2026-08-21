import os
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from database.db import get_database_url


def _alembic_config():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return Config(os.path.join(root, 'alembic.ini'))


def ensure_schema_columns(engine):
    """Ensure all required columns exist across tables, even if DB was stamped or migrated before."""
    statements = [
        # employees table
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS entry_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS inactive_date TIMESTAMP DEFAULT NULL;",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT '';",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;",

        # users table
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS assigned_departments TEXT[] DEFAULT NULL;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department TEXT DEFAULT NULL;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;",

        # items table
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS added_by_department TEXT DEFAULT NULL;",
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;",

        # stock_receipts table
        "ALTER TABLE stock_receipts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE stock_receipts ADD COLUMN IF NOT EXISTS department TEXT DEFAULT NULL;",

        # issue_register table
        "ALTER TABLE issue_register ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE issue_register ADD COLUMN IF NOT EXISTS department TEXT DEFAULT NULL;",

        # return_register table
        "ALTER TABLE return_register ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE return_register ADD COLUMN IF NOT EXISTS department TEXT DEFAULT NULL;",
        "ALTER TABLE return_register ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;",

        # contractors & other tables
        "ALTER TABLE contractors ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE role_permissions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE departments ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE department_role_permissions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE contractor_issue_register ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE contractor_alias_map ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE expiry_tracking ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE calibration_tracking ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
    ]

    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(sa.text(stmt))
            except Exception as exc:
                print(f"Warning executing schema reconciliation statement: {exc}")


def run_migrations():
    """Apply pending Alembic migrations and ensure schema columns are present."""
    cfg = _alembic_config()
    url = get_database_url()
    engine = create_engine(url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    # Database was created with the old init_db() — stamp if version table missing
    if 'users' in tables and 'alembic_version' not in tables:
        print('Existing database detected — stamping current schema as migrated.')
        command.stamp(cfg, 'head')
        print('Database stamped successfully.')
    else:
        try:
            command.upgrade(cfg, 'head')
            print('Database migrations applied successfully.')
        except Exception as e:
            print(f'Warning running alembic upgrade: {e}')

    # Always run column/schema reconciliation to guarantee required columns exist
    ensure_schema_columns(engine)
    print('Schema column reconciliation completed.')

