import re
from flask import Blueprint, redirect, url_for, flash, session
from database.db import get_db, fetchall, fetchone
from database.sqlserver import get_sql_connection
from modules.user_admin import admin_required

employee_sync_bp = Blueprint('employee_sync', __name__)

SOURCE_VIEWS = [
    'view_EmployeeMaster_Report_staff',
    'view_EmployeeMaster_Report_Associates',
]

# We match columns loosely (case/whitespace-insensitive) because your two SQL
# Server views don't spell their headers identically ("EMPLOYEE  NAME" has a
# double space, "Employee Status" is mixed-case, etc). First alias in each
# list that's found in the view wins.
FIELD_ALIASES = {
    'emp_code':    ['EMPLOYEE ID', 'EMP ID', 'EMPLOYEE CODE'],
    'name':        ['EMPLOYEE NAME', 'EMP NAME', 'NAME'],
    'department':  ['DEPARTMENT'],
    'designation': ['DESIGNATION'],
    'contractor':  ['CONTRACTOR NAME', 'SUB CONTRACTOR NAME'],
    'status':      ['EMPLOYEE STATUS', 'STATUS', 'CARDACTIVESTATUS'],
}

# SQL Server sends department names in ALL CAPS with different wording than
# our curated Postgres department list (e.g. "INFORMATION TECHNOLOGY" vs "IT").
# Map known variants here -> the exact name as it appears in your `departments` table.
DEPARTMENT_ALIASES = {
    'INFORMATION TECHNOLOGY': 'IT',
    'HR & ADMIN': 'HR/Admin',
    'HR AND ADMIN': 'HR/Admin',
    'HUMAN RESOURCE': 'HR/Admin',
    'CIVIL & PROJECT': 'Civil/Project',
    'CIVIL AND PROJECT': 'Civil/Project',
    'ELECTRICAL OPERATIONS': 'Electrical Operation',
}


def _normalize(s):
    return re.sub(r'\s+', ' ', (s or '').strip()).upper()


def _fetch_from_view(sql_cursor, view_name):
    """
    SELECT * and build a normalized-column lookup per row, so we don't break
    when a view's headers have extra spaces / different casing / are missing
    a column entirely.
    """
    sql_cursor.execute(f"SELECT * FROM {view_name}")
    actual_cols = [desc[0] for desc in sql_cursor.description]
    normalized_cols = [_normalize(c) for c in actual_cols]

    rows = []
    for raw_row in sql_cursor.fetchall():
        row = {}
        for field, aliases in FIELD_ALIASES.items():
            value = None
            for alias in aliases:
                if alias in normalized_cols:
                    idx = normalized_cols.index(alias)
                    value = raw_row[idx]
                    break
            row[field] = value
        rows.append(row)
    return rows


def _load_department_lookup(pg_cursor):
    """Case-insensitive lookup: 'MAINTENANCE' -> 'Maintenance' (the real casing in departments table)."""
    pg_cursor.execute("SELECT name FROM departments")
    return {row['name'].upper(): row['name'] for row in fetchall(pg_cursor)}


def _normalize_department(raw_dept, dept_lookup, pg_cursor):
    """
    Resolve a raw SQL Server department string to the canonical name used in
    our `departments` table — case-insensitive match first, then known
    aliases, then auto-register it as a brand-new department if we've truly
    never seen it before (so no employee silently disappears into nothing).
    """
    if not raw_dept:
        return ''

    key = raw_dept.strip().upper()

    # 1. Exact case-insensitive match against existing departments
    if key in dept_lookup:
        return dept_lookup[key]

    # 2. Known alias (different wording, e.g. "INFORMATION TECHNOLOGY" -> "IT")
    if key in DEPARTMENT_ALIASES:
        canonical = DEPARTMENT_ALIASES[key]
        if canonical.upper() not in dept_lookup:
            pg_cursor.execute("INSERT INTO departments (name) VALUES (%s) ON CONFLICT DO NOTHING", (canonical,))
            dept_lookup[canonical.upper()] = canonical
        return canonical

    # 3. Genuinely new department — register it as-is (title case) so it shows up as its own card
    canonical = raw_dept.strip().title()
    pg_cursor.execute("INSERT INTO departments (name) VALUES (%s) ON CONFLICT DO NOTHING", (canonical,))
    dept_lookup[key] = canonical
    return canonical


@employee_sync_bp.route('/admin/sync-employees', methods=['POST'])
@admin_required
def sync_employees():
    """
    Pulls employees from the SQL Server HR views and upserts them into the
    PostgreSQL `employees` table (by emp_code) and `contractors` table
    (by contractor name). Employees that exist in Postgres but are no longer
    present in SQL Server are marked Inactive rather than deleted, so issue
    history / references are preserved.
    """
    try:
        sql_conn = get_sql_connection()
    except Exception as e:
        flash(f'Could not connect to SQL Server: {e}', 'danger')
        return redirect(url_for('users_admin.index'))

    pg = get_db()
    pg_cursor = pg.cursor()

    added = updated = unchanged = skipped = 0
    contractors_added = 0
    seen_emp_codes = set()
    error_log = []
    dept_lookup = _load_department_lookup(pg_cursor)

    try:
        sql_cursor = sql_conn.cursor()

        for view_name in SOURCE_VIEWS:
            try:
                rows = _fetch_from_view(sql_cursor, view_name)
            except Exception as e:
                error_log.append(f"{view_name}: could not read view — {e}")
                continue

            for row in rows:
                emp_code = str(row.get('emp_code')).strip() if row.get('emp_code') else None
                name = str(row.get('name')).strip() if row.get('name') else None

                if not emp_code or not name or emp_code.lower() == 'none':
                    skipped += 1
                    continue

                department = _normalize_department(str(row.get('department') or '').strip(), dept_lookup, pg_cursor)
                designation = str(row.get('designation') or '').strip()
                contractor = str(row.get('contractor') or '').strip()
                raw_status = str(row.get('status') or '').strip().lower()
                # Active unless explicitly marked otherwise
                status = 'Inactive' if raw_status in ('inactive', 'in active', 'no', 'n', '0', 'false') else 'Active'

                seen_emp_codes.add(emp_code)

                if contractor:
                    pg_cursor.execute("SELECT id FROM contractors WHERE LOWER(name)=LOWER(%s)", (contractor,))
                    if fetchone(pg_cursor) is None:
                        pg_cursor.execute(
                            "INSERT INTO contractors (name, department) VALUES (%s,%s) ON CONFLICT (name) DO NOTHING",
                            (contractor, department)
                        )
                        contractors_added += 1

                pg_cursor.execute("SELECT * FROM employees WHERE emp_code=%s", (emp_code,))
                existing = fetchone(pg_cursor)

                if existing is None:
                    pg_cursor.execute("""
                        INSERT INTO employees (emp_code, name, department, contractor, designation, status)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (emp_code, name, department, contractor, designation, status))
                    added += 1
                else:
                    if (existing.get('name') != name or existing.get('department') != department or
                            existing.get('contractor') != contractor or existing.get('designation') != designation or
                            existing.get('status') != status):
                        pg_cursor.execute("""
                            UPDATE employees
                            SET name=%s, department=%s, contractor=%s, designation=%s, status=%s
                            WHERE emp_code=%s
                        """, (name, department, contractor, designation, status, emp_code))
                        updated += 1
                    else:
                        unchanged += 1

        deactivated = 0
        if seen_emp_codes:
            pg_cursor.execute("SELECT emp_code FROM employees WHERE status != 'Inactive'")
            all_active = fetchall(pg_cursor)
            codes_to_deactivate = [r['emp_code'] for r in all_active if r['emp_code'] not in seen_emp_codes]
            for code in codes_to_deactivate:
                pg_cursor.execute("UPDATE employees SET status='Inactive' WHERE emp_code=%s", (code,))
                deactivated += 1

        pg.commit()

        summary = (f'Sync complete: {added} added, {updated} updated, {unchanged} unchanged, '
                   f'{deactivated} marked inactive, {contractors_added} new contractors.')
        flash(summary, 'success')
        if skipped:
            flash(f'{skipped} rows skipped (missing Employee ID or Name).', 'warning')
        if error_log:
            flash('Issues: ' + ' | '.join(error_log), 'warning')

    except Exception as e:
        pg.rollback()
        flash(f'Sync failed: {e}', 'danger')
    finally:
        pg.close()
        sql_conn.close()

    return redirect(url_for('users_admin.index'))