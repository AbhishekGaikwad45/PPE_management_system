import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv  # ← ADD

load_dotenv()  # ← ADD — .env file

DB_CONFIG = {
    'host':     os.environ.get('PG_HOST',     'localhost'),
    'port':     os.environ.get('PG_PORT',     '5432'),
    'database': os.environ.get('PG_DATABASE', 'ppe_db'),
    'user':     os.environ.get('PG_USER',     'postgres'),
    'password': os.environ.get('PG_PASSWORD', 'postgres'),
}

def get_db():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn

def fetchall(cursor):
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]

def fetchone(cursor):
    if cursor.description is None:
        return None
    cols = [desc[0] for desc in cursor.description]
    row = cursor.fetchone()
    return dict(zip(cols, row)) if row else None

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,
        full_name TEXT,
        department TEXT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ← ADD — email column for the user (used for password-reset OTP)
    c.execute('''ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT''')

    # ← ADD — controls which role can Create / Edit / Delete users (set by Admin)
    c.execute('''CREATE TABLE IF NOT EXISTS role_permissions (
        role TEXT PRIMARY KEY,
        can_create BOOLEAN NOT NULL DEFAULT FALSE,
        can_edit BOOLEAN NOT NULL DEFAULT FALSE,
        can_delete BOOLEAN NOT NULL DEFAULT FALSE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS departments (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS contractors (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            contact TEXT,
            department TEXT
        )''')
    c.execute('''ALTER TABLE contractors ADD COLUMN IF NOT EXISTS department TEXT''')

    c.execute('''CREATE TABLE IF NOT EXISTS employees (
        id SERIAL PRIMARY KEY,
        emp_code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        department TEXT,
        contractor TEXT,
        designation TEXT,
        status TEXT DEFAULT 'Active'
    )''')

    c.execute('''CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_employees_status ON employees(status)''')

    c.execute('''CREATE TABLE IF NOT EXISTS items (
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
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS stock_receipts (
        id SERIAL PRIMARY KEY,
        receipt_date TEXT NOT NULL,
        item_id INTEGER NOT NULL REFERENCES items(id),
        qty INTEGER NOT NULL,
        grn_no TEXT,
        received_by TEXT,
        remarks TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS issue_register (
        id SERIAL PRIMARY KEY,
        issue_date TEXT NOT NULL,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        item_id INTEGER NOT NULL REFERENCES items(id),
        qty INTEGER NOT NULL,
        issued_by TEXT,
        returnable INTEGER DEFAULT 0,
        return_due_date TEXT,
        status TEXT DEFAULT 'Issued',
        remarks TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS contractor_issue_register (
        id SERIAL PRIMARY KEY,
        issue_date TEXT NOT NULL,
        contractor_id INTEGER NOT NULL REFERENCES contractors(id),
        item_id INTEGER NOT NULL REFERENCES items(id),
        qty INTEGER NOT NULL,
        issued_by TEXT,
        returnable INTEGER DEFAULT 0,
        return_due_date TEXT,
        status TEXT DEFAULT 'Issued',
        remarks TEXT
    )''')

    c.execute('''ALTER TABLE contractor_issue_register ADD COLUMN IF NOT EXISTS employee_id INTEGER REFERENCES employees(id)''')
    c.execute("""
        CREATE TABLE IF NOT EXISTS contractor_alias_map (
            id SERIAL PRIMARY KEY,
            contractor_id INTEGER NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
            external_contractor_name TEXT NOT NULL UNIQUE
        )
        """)
    c.execute('''CREATE TABLE IF NOT EXISTS return_register (
        id SERIAL PRIMARY KEY,
        return_date TEXT NOT NULL,
        issue_id INTEGER,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        item_id INTEGER NOT NULL REFERENCES items(id),
        qty INTEGER NOT NULL,
        condition TEXT,
        received_by TEXT,
        remarks TEXT
    )''')


     # ← ADD — disposal records aren't tied to an employee, so employee_id must be optional
    c.execute('''ALTER TABLE return_register ALTER COLUMN employee_id DROP NOT NULL''')
    # ← ADD — separate quantity fields: count (No.) vs weight (Kg)
    c.execute('''ALTER TABLE return_register ADD COLUMN IF NOT EXISTS qty_no INTEGER''')
    c.execute('''ALTER TABLE return_register ADD COLUMN IF NOT EXISTS qty_kg NUMERIC''')

    c.execute('''CREATE TABLE IF NOT EXISTS expiry_tracking (
        id SERIAL PRIMARY KEY,
        item_id INTEGER NOT NULL REFERENCES items(id),
        batch_no TEXT,
        manufacture_date TEXT,
        expiry_date TEXT NOT NULL,
        qty INTEGER,
        status TEXT DEFAULT 'Active'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS calibration_tracking (
        id SERIAL PRIMARY KEY,
        item_id INTEGER NOT NULL REFERENCES items(id),
        serial_no TEXT,
        last_calibration_date TEXT,
        next_calibration_date TEXT NOT NULL,
        calibrated_by TEXT,
        status TEXT DEFAULT 'Valid'
    )''')

    # ← ADD — one-time-password records used for the "forgot password" email flow
    c.execute('''CREATE TABLE IF NOT EXISTS password_reset_otp (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        otp_code TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        used BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    conn.commit()

    depts = [
        'Operations', 'Maintenance', 'Safety', 'Security', 'Administration',
        'Marine', 'Cargo', 'Logistics', 'Electrical', 'Civil',
        'Mechanical', 'Electrical Operation', 'Civil/Project', 'HR/Admin', 'IT'
    ]
    for d in depts:
        try:
            c.execute("INSERT INTO departments (name) VALUES (%s) ON CONFLICT DO NOTHING", (d,))
        except:
            pass
    conn.commit()

    # ← ADD — seed default role permissions (Admin can change these later from the UI)
    role_perms = [
        ('Admin',            True,  True,  True),
        ('Super Admin',      True,  True,  True),
        ('Safety Officer',   False, False, False),
        ('Store Keeper',     False, False, False),
        ('Viewer',           False, False, False),
        ('Department User',  False, False, False),
    ]
    for role, can_create, can_edit, can_delete in role_perms:
        try:
            c.execute(
                "INSERT INTO role_permissions (role, can_create, can_edit, can_delete) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (role, can_create, can_edit, can_delete)
            )
        except:
            pass
    conn.commit()

    conn.close()
    print("PostgreSQL Database initialized successfully.")