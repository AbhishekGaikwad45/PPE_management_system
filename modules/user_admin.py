"""
modules/user_admin.py
Admin-only User Management (full CRUD) — permissions for Create/Edit/Delete
are dynamic, stored per DEPARTMENT + ROLE in the `department_role_permissions`
table, editable by Admin/Super Admin from a new "Manage Permissions" page.

Users that have no department assigned (department IS NULL, e.g. Admin /
Viewer with "All access") fall back to the old global `role_permissions`
table so existing behaviour keeps working for them.

Users now also have an `email` column (used for the forgot-password OTP flow).

Run database migrations once before using this file:
    python init_database.py   (or: alembic upgrade head)
It creates the `department_role_permissions` table this module depends on.
"""

from flask import Blueprint, render_template, render_template_string, request, redirect, url_for, session, flash
from database.db import get_db, fetchall, fetchone
from functools import wraps
from modules.logs import log_action

users_admin_bp = Blueprint('users_admin', __name__, url_prefix='/admin/users')

ROLES = ['Admin', 'Super Admin', 'Safety Officer', 'Store Keeper', 'Viewer', 'Department User']

# Roles that are shown/edited in the department permission matrix.
# Admin / Super Admin are excluded — they always have full access everywhere.
ASSIGNABLE_ROLES = [r for r in ROLES if r not in ('Admin', 'Super Admin')]

SYSTEM_MODULES = [
    {'id': 'employees', 'name': 'Employees', 'icon': 'fas fa-users'},
    {'id': 'contractors', 'name': 'Contractors', 'icon': 'fas fa-hard-hat'},
    {'id': 'items', 'name': 'Item Master', 'icon': 'fas fa-boxes'},
    {'id': 'department_stock', 'name': 'Department Stock', 'icon': 'fas fa-warehouse'},
    {'id': 'stock', 'name': 'Stock Receipt', 'icon': 'fas fa-truck-loading'},
    {'id': 'issues', 'name': 'Issue PPE', 'icon': 'fas fa-hand-holding'},
    {'id': 'returns', 'name': 'Returns', 'icon': 'fas fa-undo'},
    {'id': 'contractor_issues', 'name': 'Provided by Contractor', 'icon': 'fas fa-hard-hat'},
    {'id': 'calibration', 'name': 'Calibration', 'icon': 'fas fa-tools'},
    {'id': 'reports', 'name': 'Reports & KPI', 'icon': 'fas fa-chart-bar'},
    {'id': 'logs', 'name': 'Activity & Error Logs', 'icon': 'fas fa-history'},
]


def get_departments():
    """Pulls the live list of departments from the `departments` table
    (the same table used elsewhere in the app), so any department added
    there shows up here automatically — no code change needed."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM departments ORDER BY name")
    rows = fetchall(c)
    conn.close()
    return [r['name'] for r in rows]


def get_user_departments():
    """Pulls the distinct list of group display names created in the users table."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT department FROM users WHERE department IS NOT NULL AND TRIM(department) != '' ORDER BY department")
    rows = fetchall(c)
    conn.close()
    return [r['department'] for r in rows]


def get_user_dept_variants():
    """Returns None for Admin/Super Admin (sees everything),
    otherwise returns a list of lowercase department names for the logged-in user
    combining session['department'] and session['assigned_departments']."""
    role = session.get('role')
    if role in ('Admin', 'Super Admin'):
        return None
    dept = session.get('department')
    assigned = session.get('assigned_departments') or []

    raw_list = []
    if dept:
        raw_list.append(dept.strip())
    for d in assigned:
        if d:
            raw_list.append(d.strip())

    if not raw_list:
        return None

    variants = []
    for d in raw_list:
        d_lower = d.lower()
        if d_lower not in variants:
            variants.append(d_lower)

    return variants if variants else None


# ---------- permission helpers ----------

def get_role_permissions():
    """Global fallback permissions (used for users with no department).
    Returns {role: {'can_create': bool, 'can_edit': bool, 'can_delete': bool}}"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT role, can_create, can_edit, can_delete FROM role_permissions")
    rows = fetchall(c)
    conn.close()
    return {r['role']: r for r in rows}


def get_department_role_permissions(department=None):
    """
    If `department` is given: returns {role: {'can_create':.., 'can_edit':.., 'can_delete':..}}
    for that department only.
    If `department` is None: returns the full map {department: {role: {...}}}.
    """
    conn = get_db()
    c = conn.cursor()
    if department:
        c.execute(
            "SELECT role, can_create, can_edit, can_delete FROM department_role_permissions WHERE department=%s",
            (department,)
        )
        rows = fetchall(c)
        conn.close()
        return {r['role']: r for r in rows}
    else:
        c.execute("SELECT department, role, can_create, can_edit, can_delete FROM department_role_permissions")
        rows = fetchall(c)
        conn.close()
        result = {}
        for r in rows:
            result.setdefault(r['department'], {})[r['role']] = r
        return result


def get_module_permissions(department=None):
    """
    Returns { (role, module): {'can_view': bool, 'can_create': bool, 'can_edit': bool, 'can_delete': bool} }
    For the specified department (or '' for global/legacy).
    """
    dept_str = department if department is not None else ''
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT role, module, can_view, can_create, can_edit, can_delete
        FROM module_permissions
        WHERE department = %s
    """, (dept_str,))
    rows = fetchall(c)
    conn.close()
    return {(r['role'], r['module']): r for r in rows}


def has_permission(action, module=None, department=None):
    """
    action: 'can_view' | 'can_create' | 'can_edit' | 'can_delete'
    module: optional module id e.g. 'employees', 'items', 'issues', etc.
    department: optional department override — if not given, uses current session.
    """
    role = session.get('role')
    if role in ('Admin', 'Super Admin'):
        return True

    dept = department if department is not None else session.get('department')
    dept_str = dept if dept else ''

    if module:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT can_view, can_create, can_edit, can_delete
            FROM module_permissions
            WHERE role = %s AND module = %s AND (department = %s OR department = '')
            ORDER BY CASE WHEN department != '' THEN 1 ELSE 2 END
            LIMIT 1
        """, (role, module, dept_str))
        row = fetchone(c)
        conn.close()

        if row:
            col_map = {
                'view': 'can_view',
                'can_view': 'can_view',
                'create': 'can_create',
                'can_create': 'can_create',
                'edit': 'can_edit',
                'can_edit': 'can_edit',
                'delete': 'can_delete',
                'can_delete': 'can_delete',
            }
            col = col_map.get(action, action)
            return bool(row.get(col, False))

    if action in ('view', 'can_view'):
        return True

    if dept:
        perms = get_department_role_permissions(dept)
        return bool(perms.get(role, {}).get(action))

    perms = get_role_permissions()
    return bool(perms.get(role, {}).get(action))


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapped


def permission_required(action):
    """Decorator factory — checks the dynamic department+role permission table
    (falls back to global role_permissions for department-less users)."""
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            if not has_permission(action):
                flash('You do not have permission to perform this action.', 'danger')
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(f):
    """Restrict a route to Admin / Super Admin only (used for index + permissions page)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') not in ['Admin', 'Super Admin']:
            flash('You do not have permission to access User Management.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapped


# ---------- user CRUD ----------

@users_admin_bp.route('/')
@admin_required
def index():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT id, username, role, full_name, department, email, created_at, assigned_departments
        FROM users
        ORDER BY id
    """)
    users = fetchall(c)

    c.execute("SELECT role, can_create, can_edit, can_delete FROM role_permissions")
    global_perms = {row["role"]: row for row in fetchall(c)}

    conn.close()

    # department -> role -> perms, used to show the correct badges per user
    dept_perms = get_department_role_permissions()

    from modules.employee_sync import get_auto_sync_config
    auto_sync_config = get_auto_sync_config()

    return render_template(
        "users_admin.html",
        users=users,
        roles=ROLES,
        departments=get_departments(),
        perms=global_perms,
        dept_perms=dept_perms,
        auto_sync_config=auto_sync_config,
        can_create=has_permission("can_create"),
        can_edit=has_permission("can_edit"),
        can_delete=has_permission("can_delete")
    )


@users_admin_bp.route('/add', methods=['POST'])
@permission_required('can_create')
def add():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', '').strip()
    department = request.form.get('department', '').strip() or None
    email = request.form.get('email', '').strip() or None
    assigned_departments = request.form.getlist('assigned_departments')

    if not username or not password or not role:
        flash('Username, password and role are required.', 'danger')
        return redirect(url_for('users_admin.index'))

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password, role, full_name, department, email, assigned_departments) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (username, password, role, full_name, department, email, assigned_departments)
        )
        new_id = c.fetchone()[0]
        conn.commit()
        flash(f"User '{username}' created successfully.", 'success')
        log_action('create', 'users', new_id, f"Created user '{username}' (role: {role})")
    except Exception as e:
        conn.rollback()
        flash(f"Error creating user: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('users_admin.index'))


@users_admin_bp.route('/edit/<int:user_id>', methods=['POST'])
@permission_required('can_edit')
def edit(user_id):
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', '').strip()
    department = request.form.get('department', '').strip() or None
    email = request.form.get('email', '').strip() or None
    password = request.form.get('password', '').strip()  # optional — blank keeps current
    assigned_departments = request.form.getlist('assigned_departments')

    if not username:
        flash('Username cannot be empty.', 'danger')
        return redirect(url_for('users_admin.index'))

    conn = get_db()
    c = conn.cursor()
    try:
        # Prevent duplicate usernames (case-insensitive), excluding this user itself
        c.execute("SELECT id FROM users WHERE LOWER(username)=LOWER(%s) AND id != %s", (username, user_id))
        if fetchone(c):
            flash(f"Username '{username}' is already taken by another user.", 'danger')
            conn.close()
            return redirect(url_for('users_admin.index'))

        # If this user is currently logged in and renames themselves,
        # keep their session in sync so they don't get logged out/mismatched.
        c.execute("SELECT username FROM users WHERE id=%s", (user_id,))
        old = fetchone(c)
        old_username = old['username'] if old else None

        if password:
            c.execute(
                "UPDATE users SET username=%s, full_name=%s, role=%s, department=%s, email=%s, password=%s, assigned_departments=%s WHERE id=%s",
                (username, full_name, role, department, email, password, assigned_departments, user_id)
            )
        else:
            c.execute(
                "UPDATE users SET username=%s, full_name=%s, role=%s, department=%s, email=%s, assigned_departments=%s WHERE id=%s",
                (username, full_name, role, department, email, assigned_departments, user_id)
            )
        conn.commit()

        if old_username and session.get('user') == old_username:
            session['user'] = username

        flash('User updated successfully.', 'success')
        log_action('edit', 'users', user_id,
                    f"Updated user id {user_id} (username: {username}, name: {full_name}, role: {role}"
                    + (", password changed)" if password else ")"))
    except Exception as e:
        conn.rollback()
        flash(f"Error updating user: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('users_admin.index'))


@users_admin_bp.route('/delete/<int:user_id>', methods=['POST'])
@permission_required('can_delete')
def delete(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=%s", (user_id,))
    row = fetchone(c)

    if not row:
        flash('User not found.', 'danger')
        conn.close()
        return redirect(url_for('users_admin.index'))

    if row['username'] == session.get('user'):
        flash('You cannot delete your own logged-in account.', 'danger')
        conn.close()
        return redirect(url_for('users_admin.index'))

    try:
        c.execute("DELETE FROM users WHERE id=%s", (user_id,))
        conn.commit()
        flash(f"User '{row['username']}' deleted.", 'success')
        log_action('delete', 'users', user_id, f"Deleted user '{row['username']}'")
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting user: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('users_admin.index'))


# ---------- Admin: manage departments (rename / delete) ----------

# Every table that stores a department NAME as plain text (not an FK) and
# therefore needs to be kept in sync when a department is renamed.
_DEPARTMENT_TEXT_TABLES = [
    'users', 'employees', 'contractors', 'stock_receipts', 'issue_register'
]


@users_admin_bp.route('/departments/add', methods=['POST'])
@admin_required
def add_department():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Department name cannot be empty.', 'danger')
        return redirect(url_for('users_admin.permissions'))

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO departments (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
        # Adding it back manually un-tombstones it, so the HR sync is
        # allowed to recognise it again too.
        c.execute("DELETE FROM deleted_departments WHERE LOWER(name)=LOWER(%s)", (name,))
        conn.commit()
        flash(f"Department '{name}' added.", 'success')
        log_action('create', 'departments', None, f"Added department '{name}'")
    except Exception as e:
        conn.rollback()
        flash(f"Error adding department: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('users_admin.permissions', department=name))


@users_admin_bp.route('/departments/rename', methods=['POST'])
@admin_required
def rename_department():
    old_name = request.form.get('old_name', '').strip()
    new_name = request.form.get('new_name', '').strip()

    if not old_name or not new_name:
        flash('Department name cannot be empty.', 'danger')
        return redirect(url_for('users_admin.permissions'))

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("UPDATE departments SET name=%s WHERE name=%s", (new_name, old_name))
        c.execute("UPDATE department_role_permissions SET department=%s WHERE department=%s", (new_name, old_name))
        for table in _DEPARTMENT_TEXT_TABLES:
            c.execute(f"UPDATE {table} SET department=%s WHERE department=%s", (new_name, old_name))
        conn.commit()
        flash(f"Department renamed: '{old_name}' → '{new_name}'.", 'success')
        log_action('edit', 'departments', None, f"Renamed department '{old_name}' → '{new_name}'")
    except Exception as e:
        conn.rollback()
        flash(f"Error renaming department: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('users_admin.permissions', department=new_name))


@users_admin_bp.route('/departments/delete', methods=['POST'])
@admin_required
def delete_department():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Department not specified.', 'danger')
        return redirect(url_for('users_admin.permissions'))

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) AS n FROM employees WHERE department=%s", (name,))
        emp_count = fetchone(c)['n']
        c.execute("SELECT COUNT(*) AS n FROM users WHERE department=%s", (name,))
        user_count = fetchone(c)['n']

        c.execute("DELETE FROM department_role_permissions WHERE department=%s", (name,))
        c.execute("DELETE FROM departments WHERE name=%s", (name,))
        c.execute(
            """INSERT INTO deleted_departments (name, deleted_by) VALUES (%s,%s)
               ON CONFLICT (name) DO UPDATE SET deleted_by=%s, deleted_at=CURRENT_TIMESTAMP""",
            (name, session.get('user'), session.get('user'))
        )
        conn.commit()
        flash(f"Department '{name}' deleted. It will not be re-created by the HR sync anymore.", 'success')
        log_action('delete', 'departments', None, f"Deleted department '{name}'")
        if emp_count or user_count:
            flash(f"Note: {emp_count} employee(s) and {user_count} user(s) still have '{name}' recorded "
                  f"against them — reassign them manually if needed.", 'warning')
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting department: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('users_admin.permissions'))


def get_module_permissions(department=None):
    """
    Returns { (role, module): {'can_view': bool, 'can_create': bool, 'can_edit': bool, 'can_delete': bool} }
    For the specified department (or '' for global/legacy).
    """
    dept_str = department if department is not None else ''
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT role, module, can_view, can_create, can_edit, can_delete
        FROM module_permissions
        WHERE department = %s
    """, (dept_str,))
    rows = fetchall(c)
    conn.close()
    return {(r['role'], r['module']): r for r in rows}


def has_permission(action, module=None, department=None):
    """
    action: 'can_view' | 'can_create' | 'can_edit' | 'can_delete'
    module: optional module id e.g. 'employees', 'items', 'issues', etc.
    department: optional department override — if not given, uses current session.
    """
    role = session.get('role')
    if role in ('Admin', 'Super Admin'):
        return True

    dept = department if department is not None else session.get('department')
    dept_str = dept if dept else ''

    if module:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT can_view, can_create, can_edit, can_delete
            FROM module_permissions
            WHERE role = %s AND module = %s AND (department = %s OR department = '')
            ORDER BY CASE WHEN department != '' THEN 1 ELSE 2 END
            LIMIT 1
        """, (role, module, dept_str))
        row = fetchone(c)
        conn.close()

        if row:
            col_map = {
                'view': 'can_view',
                'can_view': 'can_view',
                'create': 'can_create',
                'can_create': 'can_create',
                'edit': 'can_edit',
                'can_edit': 'can_edit',
                'delete': 'can_delete',
                'can_delete': 'can_delete',
            }
            col = col_map.get(action, action)
            return bool(row.get(col, False))

    if action in ('view', 'can_view'):
        return True

    if dept:
        perms = get_department_role_permissions(dept)
        return bool(perms.get(role, {}).get(action))

    perms = get_role_permissions()
    return bool(perms.get(role, {}).get(action))


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapped


def permission_required(action):
    """Decorator factory — checks the dynamic department+role permission table
    (falls back to global role_permissions for department-less users)."""
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            if not has_permission(action):
                flash('You do not have permission to perform this action.', 'danger')
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(f):
    """Restrict a route to Admin / Super Admin only (used for index + permissions page)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') not in ['Admin', 'Super Admin']:
            flash('You do not have permission to access User Management.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapped


# ---------- Admin: manage which role gets which permission, per department ----------

PERMISSIONS_PAGE = """
{% extends "base.html" %}
{% block title %}Module Permissions{% endblock %}
{% block page_title %}Module Permissions{% endblock %}
{% block content %}

<div class="card shadow-sm border-0 mb-4">
  <div class="card-header bg-white py-3">
    <h5 class="mb-0 fw-bold text-dark"><i class="fas fa-shield-alt text-primary me-2"></i>Module Permissions</h5>
  </div>
  <div class="card-body">
    <form method="GET" action="{{ url_for('users_admin.permissions') }}" id="filterForm" class="row g-2 align-items-center mb-3">
      <div class="col-auto d-flex align-items-center gap-2">
        <label class="fw-semibold small text-muted mb-0">Role:</label>
        <select name="role" class="form-select form-select-sm fw-semibold" style="min-width: 170px;" onchange="this.form.submit()">
          {% for r in assignable_roles %}
          <option value="{{ r }}" {% if selected_role == r %}selected{% endif %}>{{ r }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-auto d-flex align-items-center gap-2">
        <label class="fw-semibold small text-muted mb-0">Department:</label>
        <select name="department" class="form-select form-select-sm" style="min-width: 200px;" onchange="this.form.submit()">
          <option value="">All (Global / Legacy)</option>
          {% for d in departments %}
          <option value="{{ d }}" {% if selected_department == d %}selected{% endif %}>{{ d }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-auto">
        <input type="text" id="moduleSearchInput" class="form-control form-control-sm" placeholder="Filter modules..." onkeyup="filterModulesTable()">
      </div>

      <div class="col-auto d-flex gap-1 align-items-center">
        <span class="small fw-semibold text-muted me-1">Bulk:</span>
        <button type="button" class="btn btn-sm btn-light border" onclick="applyBulkAction('read')">Read Only</button>
        <button type="button" class="btn btn-sm btn-light border" onclick="applyBulkAction('read_add_edit')">Read+Add+Edit</button>
        <button type="button" class="btn btn-sm btn-light border" onclick="applyBulkAction('full')">Full Access</button>
        <button type="button" class="btn btn-sm btn-outline-danger" onclick="applyBulkAction('revoke')">Revoke All</button>
      </div>

      <div class="col-auto ms-auto">
        <button type="submit" form="permissionsSaveForm" class="btn btn-sm btn-jsw px-3">
          <i class="fas fa-save me-1"></i> Save Permissions
        </button>
      </div>
    </form>

    <form method="POST" action="{{ url_for('users_admin.permissions') }}" id="permissionsSaveForm">
      <input type="hidden" name="role" value="{{ selected_role }}">
      <input type="hidden" name="department" value="{{ selected_department or '' }}">

      <div class="table-responsive border rounded bg-white" style="max-height: 600px; overflow-y: auto;">
        <table class="table table-hover align-middle table-sm mb-0" id="permissionsTable">
          <thead class="table-light sticky-top" style="z-index: 5;">
            <tr>
              <th style="width: 100px;">Code</th>
              <th>Module Name</th>
              <th class="text-center" style="width: 90px;">Read</th>
              <th class="text-center" style="width: 90px;">Add</th>
              <th class="text-center" style="width: 90px;">Edit</th>
              <th class="text-center" style="width: 90px;">Delete</th>
              <th class="text-center" style="width: 90px;">All</th>
            </tr>
          </thead>
          <tbody>
            {% for mod in system_modules %}
            {% set m_perm = module_perms.get((selected_role, mod.id), {}) %}
            {% set is_read = m_perm.get('can_view', True) %}
            {% set is_add = m_perm.get('can_create', False) %}
            {% set is_edit = m_perm.get('can_edit', False) %}
            {% set is_delete = m_perm.get('can_delete', False) %}
            {% set is_all = is_read and is_add and is_edit and is_delete %}
            <tr class="module-row" data-name="{{ mod.name | lower }}" data-code="{{ mod.code | lower }}">
              <td>
                <span class="badge bg-primary px-2 py-1 font-monospace" style="font-size:11px;">{{ mod.code }}</span>
              </td>
              <td class="fw-medium text-dark">{{ mod.name }}</td>
              <td class="text-center">
                <input type="checkbox" class="form-check-input perm-cb cb-read cb-row-{{ mod.id }}" name="read_{{ mod.id }}" {% if is_read %}checked{% endif %} onchange="updateRowMaster('{{ mod.id }}')">
              </td>
              <td class="text-center">
                <input type="checkbox" class="form-check-input perm-cb cb-add cb-row-{{ mod.id }}" name="add_{{ mod.id }}" {% if is_add %}checked{% endif %} onchange="updateRowMaster('{{ mod.id }}')">
              </td>
              <td class="text-center">
                <input type="checkbox" class="form-check-input perm-cb cb-edit cb-row-{{ mod.id }}" name="edit_{{ mod.id }}" {% if is_edit %}checked{% endif %} onchange="updateRowMaster('{{ mod.id }}')">
              </td>
              <td class="text-center">
                <input type="checkbox" class="form-check-input perm-cb cb-delete cb-row-{{ mod.id }}" name="delete_{{ mod.id }}" {% if is_delete %}checked{% endif %} onchange="updateRowMaster('{{ mod.id }}')">
              </td>
              <td class="text-center">
                <input type="checkbox" class="form-check-input cb-master cb-master-{{ mod.id }}" id="master_{{ mod.id }}" {% if is_all %}checked{% endif %} onchange="toggleRowAll('{{ mod.id }}', this.checked)">
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <div class="mt-3 d-flex justify-content-between align-items-center">
        <span class="small text-muted">Configuring permissions for Role: <strong class="text-dark">{{ selected_role }}</strong> | Department: <strong class="text-dark">{{ selected_department or 'All Access (Global / Legacy)' }}</strong></span>
        <button type="submit" class="btn btn-jsw px-4">
          <i class="fas fa-save me-1"></i> Save Permissions
        </button>
      </div>
    </form>
  </div>
</div>

<script>
function filterModulesTable() {
  const query = document.getElementById('moduleSearchInput').value.toLowerCase().trim();
  const rows = document.querySelectorAll('.module-row');
  rows.forEach(row => {
    const name = row.getAttribute('data-name');
    const code = row.getAttribute('data-code');
    if (name.includes(query) || code.includes(query)) {
      row.style.display = '';
    } else {
      row.style.display = 'none';
    }
  });
}

function toggleRowAll(modId, state) {
  const cbs = document.querySelectorAll('.cb-row-' + modId);
  cbs.forEach(cb => cb.checked = state);
}

function updateRowMaster(modId) {
  const cbs = document.querySelectorAll('.cb-row-' + modId);
  let allChecked = true;
  cbs.forEach(cb => {
    if (!cb.checked) allChecked = false;
  });
  const master = document.querySelector('.cb-master-' + modId);
  if (master) master.checked = allChecked;
}

function applyBulkAction(type) {
  const rows = document.querySelectorAll('.module-row');
  rows.forEach(row => {
    if (row.style.display === 'none') return;
    const read = row.querySelector('.cb-read');
    const add = row.querySelector('.cb-add');
    const edit = row.querySelector('.cb-edit');
    const del = row.querySelector('.cb-delete');
    const master = row.querySelector('.cb-master');

    if (type === 'read') {
      if (read) read.checked = true;
      if (add) add.checked = false;
      if (edit) edit.checked = false;
      if (del) del.checked = false;
      if (master) master.checked = false;
    } else if (type === 'read_add_edit') {
      if (read) read.checked = true;
      if (add) add.checked = true;
      if (edit) edit.checked = true;
      if (del) del.checked = false;
      if (master) master.checked = false;
    } else if (type === 'full') {
      if (read) read.checked = true;
      if (add) add.checked = true;
      if (edit) edit.checked = true;
      if (del) del.checked = true;
      if (master) master.checked = true;
    } else if (type === 'revoke') {
      if (read) read.checked = false;
      if (add) add.checked = false;
      if (edit) edit.checked = false;
      if (del) del.checked = false;
      if (master) master.checked = false;
    }
  });
}
</script>
{% endblock %}
"""


@users_admin_bp.route('/permissions', methods=['GET', 'POST'])
@admin_required
def permissions():
    selected_role = (request.values.get('role') or 'Safety Officer').strip()
    if selected_role not in ASSIGNABLE_ROLES:
        selected_role = ASSIGNABLE_ROLES[0] if ASSIGNABLE_ROLES else 'Safety Officer'

    selected_department = (request.values.get('department') or '').strip() or None
    dept_key = selected_department or ''

    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':
        try:
            for mod in SYSTEM_MODULES:
                mod_id = mod['id']
                can_view = f"read_{mod_id}" in request.form
                can_create = f"add_{mod_id}" in request.form
                can_edit = f"edit_{mod_id}" in request.form
                can_delete = f"delete_{mod_id}" in request.form

                c.execute("""
                    INSERT INTO module_permissions (department, role, module, can_view, can_create, can_edit, can_delete)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (department, role, module) DO UPDATE
                    SET can_view=EXCLUDED.can_view,
                        can_create=EXCLUDED.can_create,
                        can_edit=EXCLUDED.can_edit,
                        can_delete=EXCLUDED.can_delete
                """, (dept_key, selected_role, mod_id, can_view, can_create, can_edit, can_delete))

            # Synchronize legacy permission table
            c.execute("""
                SELECT bool_or(can_create) as c, bool_or(can_edit) as e, bool_or(can_delete) as d
                FROM module_permissions WHERE department = %s AND role = %s
            """, (dept_key, selected_role))
            leg = fetchone(c)
            can_c = bool(leg and leg['c']) if leg else False
            can_e = bool(leg and leg['e']) if leg else False
            can_d = bool(leg and leg['d']) if leg else False

            if selected_department:
                c.execute("""
                    INSERT INTO department_role_permissions (department, role, can_create, can_edit, can_delete)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (department, role) DO UPDATE
                    SET can_create=%s, can_edit=%s, can_delete=%s
                """, (selected_department, selected_role, can_c, can_e, can_d, can_c, can_e, can_d))
            else:
                c.execute("""
                    INSERT INTO role_permissions (role, can_create, can_edit, can_delete)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (role) DO UPDATE
                    SET can_create=%s, can_edit=%s, can_delete=%s
                """, (selected_role, can_c, can_e, can_d, can_c, can_e, can_d))

            conn.commit()
            flash(f"Permissions for role '{selected_role}' updated successfully.", 'success')
            log_action('edit', 'permissions', None, f"Updated module permissions for role '{selected_role}' (Dept: '{selected_department or 'Global'}')")
        except Exception as e:
            conn.rollback()
            flash(f"Error updating permissions: {e}", 'danger')

    module_perms = get_module_permissions(selected_department)
    conn.close()

    return render_template_string(
        PERMISSIONS_PAGE,
        roles=ROLES,
        assignable_roles=ASSIGNABLE_ROLES,
        system_modules=SYSTEM_MODULES,
        departments=get_user_departments(),
        selected_role=selected_role,
        selected_department=selected_department,
        module_perms=module_perms
    )