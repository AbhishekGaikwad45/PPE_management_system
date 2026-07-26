"""Apply Alembic database migrations.

First-time setup (or after pulling new migrations):
    python init_database.py

Equivalent CLI:
    alembic upgrade head
"""
from database.migrations import run_migrations

if __name__ == '__main__':
    run_migrations()
