"""Initial PPE database schema and seed data.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            full_name TEXT,
            department TEXT DEFAULT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    op.execute('''
        CREATE TABLE role_permissions (
            role TEXT PRIMARY KEY,
            can_create BOOLEAN NOT NULL DEFAULT FALSE,
            can_edit BOOLEAN NOT NULL DEFAULT FALSE,
            can_delete BOOLEAN NOT NULL DEFAULT FALSE
        )
    ''')

    op.execute('''
        CREATE TABLE departments (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    op.execute('''
        CREATE TABLE department_role_permissions (
            id SERIAL PRIMARY KEY,
            department TEXT NOT NULL,
            role TEXT NOT NULL,
            can_create BOOLEAN NOT NULL DEFAULT FALSE,
            can_edit BOOLEAN NOT NULL DEFAULT FALSE,
            can_delete BOOLEAN NOT NULL DEFAULT FALSE,
            UNIQUE(department, role)
        )
    ''')

    op.execute('''
        CREATE TABLE deleted_departments (
            name TEXT PRIMARY KEY,
            deleted_by TEXT,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    op.execute('''
        CREATE TABLE deleted_contractors (
            name TEXT PRIMARY KEY,
            deleted_by TEXT,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    op.execute('''
        CREATE TABLE contractors (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            contact TEXT,
            department TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE employees (
            id SERIAL PRIMARY KEY,
            emp_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department TEXT,
            contractor TEXT,
            designation TEXT,
            status TEXT DEFAULT 'Active'
        )
    ''')

    op.execute('CREATE INDEX idx_employees_department ON employees(department)')
    op.execute('CREATE INDEX idx_employees_status ON employees(status)')

    op.execute('''
        CREATE TABLE deleted_employees (
            emp_code TEXT PRIMARY KEY,
            name TEXT,
            deleted_by TEXT,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    op.execute('''
        CREATE TABLE items (
            id SERIAL PRIMARY KEY,
            item_code TEXT UNIQUE NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT,
            unit TEXT DEFAULT 'Nos',
            min_stock INTEGER DEFAULT 0,
            reorder_level INTEGER DEFAULT 0,
            stock INTEGER DEFAULT 0,
            has_expiry INTEGER DEFAULT 0,
            has_calibration INTEGER DEFAULT 0
        )
    ''')

    op.execute('''
        CREATE TABLE stock_receipts (
            id SERIAL PRIMARY KEY,
            receipt_date TEXT NOT NULL,
            item_id INTEGER NOT NULL REFERENCES items(id),
            qty INTEGER NOT NULL,
            grn_no TEXT,
            received_by TEXT,
            remarks TEXT,
            department TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE issue_register (
            id SERIAL PRIMARY KEY,
            issue_date TEXT NOT NULL,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            item_id INTEGER NOT NULL REFERENCES items(id),
            qty INTEGER NOT NULL,
            issued_by TEXT,
            returnable INTEGER DEFAULT 0,
            return_due_date TEXT,
            status TEXT DEFAULT 'Issued',
            remarks TEXT,
            department TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE contractor_issue_register (
            id SERIAL PRIMARY KEY,
            issue_date TEXT NOT NULL,
            contractor_id INTEGER NOT NULL REFERENCES contractors(id),
            item_id INTEGER NOT NULL REFERENCES items(id),
            qty INTEGER NOT NULL,
            issued_by TEXT,
            returnable INTEGER DEFAULT 0,
            return_due_date TEXT,
            status TEXT DEFAULT 'Issued',
            remarks TEXT,
            employee_id INTEGER REFERENCES employees(id)
        )
    ''')

    op.execute('''
        CREATE TABLE contractor_alias_map (
            id SERIAL PRIMARY KEY,
            contractor_id INTEGER NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
            external_contractor_name TEXT NOT NULL UNIQUE
        )
    ''')

    op.execute('''
        CREATE TABLE return_register (
            id SERIAL PRIMARY KEY,
            return_date TEXT NOT NULL,
            issue_id INTEGER,
            employee_id INTEGER REFERENCES employees(id),
            item_id INTEGER NOT NULL REFERENCES items(id),
            qty INTEGER NOT NULL,
            condition TEXT,
            received_by TEXT,
            remarks TEXT,
            qty_no INTEGER,
            qty_kg NUMERIC
        )
    ''')

    op.execute('''
        CREATE TABLE expiry_tracking (
            id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items(id),
            batch_no TEXT,
            manufacture_date TEXT,
            expiry_date TEXT NOT NULL,
            qty INTEGER,
            status TEXT DEFAULT 'Active'
        )
    ''')

    op.execute('''
        CREATE TABLE calibration_tracking (
            id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items(id),
            serial_no TEXT,
            last_calibration_date TEXT,
            next_calibration_date TEXT NOT NULL,
            calibrated_by TEXT,
            status TEXT DEFAULT 'Valid'
        )
    ''')

    op.execute('''
        CREATE TABLE password_reset_otp (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            otp_code TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    bind = op.get_bind()

    departments = [
        'Operations', 'Maintenance', 'Safety', 'Security', 'Administration',
        'Marine', 'Cargo', 'Logistics', 'Electrical', 'Civil',
        'Mechanical', 'Electrical Operation', 'Civil/Project', 'HR/Admin', 'IT',
    ]
    for name in departments:
        bind.execute(
            sa.text('INSERT INTO departments (name) VALUES (:name) ON CONFLICT DO NOTHING'),
            {'name': name},
        )

    role_permissions = [
        ('Admin', True, True, True),
        ('Super Admin', True, True, True),
        ('Safety Officer', False, False, False),
        ('Store Keeper', False, False, False),
        ('Viewer', False, False, False),
        ('Department User', False, False, False),
    ]
    for role, can_create, can_edit, can_delete in role_permissions:
        bind.execute(
            sa.text(
                'INSERT INTO role_permissions (role, can_create, can_edit, can_delete) '
                'VALUES (:role, :can_create, :can_edit, :can_delete) ON CONFLICT DO NOTHING'
            ),
            {
                'role': role,
                'can_create': can_create,
                'can_edit': can_edit,
                'can_delete': can_delete,
            },
        )


def downgrade() -> None:
    op.drop_table('password_reset_otp')
    op.drop_table('calibration_tracking')
    op.drop_table('expiry_tracking')
    op.drop_table('return_register')
    op.drop_table('contractor_alias_map')
    op.drop_table('contractor_issue_register')
    op.drop_table('issue_register')
    op.drop_table('stock_receipts')
    op.drop_table('items')
    op.drop_table('deleted_employees')
    op.drop_index('idx_employees_status', table_name='employees')
    op.drop_index('idx_employees_department', table_name='employees')
    op.drop_table('employees')
    op.drop_table('contractors')
    op.drop_table('deleted_contractors')
    op.drop_table('deleted_departments')
    op.drop_table('department_role_permissions')
    op.drop_table('departments')
    op.drop_table('role_permissions')
    op.drop_table('users')