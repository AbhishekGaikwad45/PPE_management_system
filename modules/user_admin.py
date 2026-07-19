"""
modules/user_admin.py
Admin-only User Management (full CRUD) — permissions for Create/Edit/Delete
are dynamic, stored per DEPARTMENT + ROLE in the `department_role_permissions`
table, editable by Admin/Super Admin from a new "Manage Permissions" page.

Users that have no department assigned (department IS NULL, e.g. Admin /
Viewer with "All access") fall back to the old global `role_permissions`
table so existing behaviour keeps working for them.

Users now also have an `email` column (used for the forgot-password OTP flow).

Run init_db() once (see database/db.py) before using this file — it creates
the `department_role_permissions` table this module depends on.
"""

from flask import Blueprint, render_template, render_template_string, request, redirect, url_for, session, flash
from database.db import get_db, fetchall, fetchone
from functools import wraps

users_admin_bp = Blueprint('users_admin', __name__, url_prefix='/admin/users')

ROLES = ['Admin', 'Super Admin', 'Safety Officer', 'Store Keeper', 'Viewer', 'Department User']

# Roles that are shown/edited in the department permission matrix.
# Admin / Super Admin are excluded — they always have full access everywhere.
ASSIGNABLE_ROLES = [r for r in ROLES if r not in ('Admin', 'Super Admin')]


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


def has_permission(action, department=None):
    """
    action: 'can_create' | 'can_edit' | 'can_delete'
    department: optional override — if not given, uses the current session
                user's own department. If that user has no department
                (None), falls back to the old global role_permissions table.
    """
    role = session.get('role')
    if role in ('Admin', 'Super Admin'):
        return True

    dept = department if department is not None else session.get('department')

    if dept:
        perms = get_department_role_permissions(dept)
        return bool(perms.get(role, {}).get(action))

    # No department context -> global/legacy role permission
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
        SELECT id, username, role, full_name, department, email, created_at
        FROM users
        ORDER BY id
    """)
    users = fetchall(c)

    c.execute("SELECT role, can_create, can_edit, can_delete FROM role_permissions")
    global_perms = {row["role"]: row for row in fetchall(c)}

    conn.close()

    # department -> role -> perms, used to show the correct badges per user
    dept_perms = get_department_role_permissions()

    return render_template(
        "users_admin.html",
        users=users,
        roles=ROLES,
        departments=get_departments(),
        perms=global_perms,
        dept_perms=dept_perms,
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

    if not username or not password or not role:
        flash('Username, password and role are required.', 'danger')
        return redirect(url_for('users_admin.index'))

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password, role, full_name, department, email) VALUES (%s,%s,%s,%s,%s,%s)",
            (username, password, role, full_name, department, email)
        )
        conn.commit()
        flash(f"User '{username}' created successfully.", 'success')
    except Exception as e:
        conn.rollback()
        flash(f"Error creating user: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('users_admin.index'))


@users_admin_bp.route('/edit/<int:user_id>', methods=['POST'])
@permission_required('can_edit')
def edit(user_id):
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', '').strip()
    department = request.form.get('department', '').strip() or None
    email = request.form.get('email', '').strip() or None
    password = request.form.get('password', '').strip()  # optional — blank keeps current

    conn = get_db()
    c = conn.cursor()
    try:
        if password:
            c.execute(
                "UPDATE users SET full_name=%s, role=%s, department=%s, email=%s, password=%s WHERE id=%s",
                (full_name, role, department, email, password, user_id)
            )
        else:
            c.execute(
                "UPDATE users SET full_name=%s, role=%s, department=%s, email=%s WHERE id=%s",
                (full_name, role, department, email, user_id)
            )
        conn.commit()
        flash('User updated successfully.', 'success')
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
        if emp_count or user_count:
            flash(f"Note: {emp_count} employee(s) and {user_count} user(s) still have '{name}' recorded "
                  f"against them — reassign them manually if needed.", 'warning')
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting department: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('users_admin.permissions'))


# ---------- Admin: manage which role gets which permission, per department ----------

PERMISSIONS_PAGE = """
{% extends "base.html" %}
{% block title %}Role Permissions{% endblock %}
{% block page_title %}Role Permissions{% endblock %}
{% block content %}

<div class="row">
  <!-- Department list -->
  <div class="col-md-3 mb-3">
    <div class="card">
      <div class="card-header bg-light fw-bold">Departments</div>
      <div class="list-group list-group-flush">
        <a href="{{ url_for('users_admin.permissions') }}"
           class="list-group-item list-group-item-action {% if not selected_department %}active{% endif %}">
          All (No department / legacy)
        </a>
        {% for d in departments %}
        <div class="list-group-item d-flex justify-content-between align-items-center {% if selected_department == d %}active{% endif %} p-0">
          <a href="{{ url_for('users_admin.permissions', department=d) }}"
             class="flex-grow-1 px-3 py-2 text-decoration-none {% if selected_department == d %}text-white{% else %}text-dark{% endif %}">
            {{ d }}
          </a>
          <span class="px-2 d-flex">
            <button type="button" class="btn btn-sm btn-link p-1"
                    onclick="document.getElementById('renameForm_{{ loop.index }}').classList.toggle('d-none')"
                    title="Rename">
              <i class="fas fa-edit"></i>
            </button>
            <form method="POST" action="{{ url_for('users_admin.delete_department') }}" class="d-inline"
                  onsubmit="return confirm('Delete department \'{{ d }}\'? It will not be re-created by the HR sync. This cannot be undone.');">
              <input type="hidden" name="name" value="{{ d }}">
              <button type="submit" class="btn btn-sm btn-link p-1 text-danger" title="Delete">
                <i class="fas fa-trash"></i>
              </button>
            </form>
          </span>
        </div>
        <div id="renameForm_{{ loop.index }}" class="list-group-item d-none">
          <form method="POST" action="{{ url_for('users_admin.rename_department') }}" class="d-flex gap-1">
            <input type="hidden" name="old_name" value="{{ d }}">
            <input type="text" name="new_name" value="{{ d }}" class="form-control form-control-sm" required>
            <button type="submit" class="btn btn-sm btn-jsw">Save</button>
          </form>
        </div>
        {% endfor %}
      </div>
    </div>

    <div class="card mt-3">
      <div class="card-body">
        <form method="POST" action="{{ url_for('users_admin.add_department') }}" class="d-flex gap-1">
          <input type="text" name="name" class="form-control form-control-sm" placeholder="New department name" required>
          <button type="submit" class="btn btn-sm btn-outline-primary">Add</button>
        </form>
      </div>
    </div>
  </div>

  <!-- Permission matrix for the selected department -->
  <div class="col-md-9">
    <div class="card">
      <div class="card-header bg-light fw-bold">
        {% if selected_department %}
          Permissions for: {{ selected_department }}
        {% else %}
          Permissions for users with no department assigned (legacy / global)
        {% endif %}
      </div>
      <div class="card-body">
        <form method="POST">
          <input type="hidden" name="department" value="{{ selected_department or '' }}">
          <table class="table">
            <thead>
              <tr><th>Role</th><th>Create</th><th>Edit</th><th>Delete</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>Admin</td>
                <td><input type="checkbox" disabled checked></td>
                <td><input type="checkbox" disabled checked></td>
                <td><input type="checkbox" disabled checked></td>
              </tr>
              <tr>
                <td>Super Admin</td>
                <td><input type="checkbox" disabled checked></td>
                <td><input type="checkbox" disabled checked></td>
                <td><input type="checkbox" disabled checked></td>
              </tr>
              {% for r in assignable_roles %}
              <tr>
                <td>{{ r }}</td>
                <td><input type="checkbox" name="create_{{ r }}" {% if perms.get(r, {}).get('can_create') %}checked{% endif %}></td>
                <td><input type="checkbox" name="edit_{{ r }}" {% if perms.get(r, {}).get('can_edit') %}checked{% endif %}></td>
                <td><input type="checkbox" name="delete_{{ r }}" {% if perms.get(r, {}).get('can_delete') %}checked{% endif %}></td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
          <button type="submit" class="btn btn-jsw">Save Permissions</button>
        </form>
      </div>
    </div>
  </div>
</div>

{% endblock %}
"""


@users_admin_bp.route('/permissions', methods=['GET', 'POST'])
@admin_required
def permissions():
    # department can come from query string (GET, clicking a department in
    # the sidebar) or from the hidden form field (POST, saving that department)
    selected_department = (request.values.get('department') or '').strip() or None

    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':
        try:
            for r in ASSIGNABLE_ROLES:
                can_create = 'create_' + r in request.form
                can_edit = 'edit_' + r in request.form
                can_delete = 'delete_' + r in request.form

                if selected_department:
                    c.execute(
                        """INSERT INTO department_role_permissions (department, role, can_create, can_edit, can_delete)
                           VALUES (%s,%s,%s,%s,%s)
                           ON CONFLICT (department, role) DO UPDATE
                           SET can_create=%s, can_edit=%s, can_delete=%s""",
                        (selected_department, r, can_create, can_edit, can_delete,
                         can_create, can_edit, can_delete)
                    )
                else:
                    # legacy/global table, for users with no department
                    c.execute(
                        """INSERT INTO role_permissions (role, can_create, can_edit, can_delete)
                           VALUES (%s,%s,%s,%s)
                           ON CONFLICT (role) DO UPDATE
                           SET can_create=%s, can_edit=%s, can_delete=%s""",
                        (r, can_create, can_edit, can_delete, can_create, can_edit, can_delete)
                    )
            conn.commit()
            flash(f"Permissions updated{' for ' + selected_department if selected_department else ''}.", 'success')
        except Exception as e:
            conn.rollback()
            flash(f"Error updating permissions: {e}", 'danger')

    if selected_department:
        perms = get_department_role_permissions(selected_department)
    else:
        c.execute("SELECT role, can_create, can_edit, can_delete FROM role_permissions")
        perms = {row['role']: row for row in fetchall(c)}

    conn.close()
    return render_template_string(
        PERMISSIONS_PAGE,
        roles=ROLES,
        assignable_roles=ASSIGNABLE_ROLES,
        departments=get_departments(),
        selected_department=selected_department,
        perms=perms
    )