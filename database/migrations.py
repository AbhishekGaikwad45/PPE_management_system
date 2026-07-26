import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from database.db import get_database_url


def _alembic_config():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return Config(os.path.join(root, 'alembic.ini'))


def run_migrations():
    """Apply pending Alembic migrations (alembic upgrade head)."""
    cfg = _alembic_config()
    url = get_database_url()
    engine = create_engine(url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    # Database was created with the old init_db() — mark as migrated without re-running DDL.
    if 'users' in tables and 'alembic_version' not in tables:
        print('Existing database detected — stamping current schema as migrated.')
        command.stamp(cfg, 'head')
        print('Database stamped successfully.')
        return

    command.upgrade(cfg, 'head')
    print('Database migrations applied successfully.')
