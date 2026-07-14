"""
modules/user_admin.py
Admin-only User Management (full CRUD) — permissions for Create/Edit/Delete
are dynamic, stored in the `role_permissions` table, and editable by
Admin/Super Admin from a new "Manage Permissions" page.

Users now also have an `email` column (used for the forgot-password OTP flow).

Run migration.sql / init_db() once before using this file.
"""

from flask import Blueprint, render_template, render_template_string, request, redirect, url_for, session, flash
from database.db import get_db, fetchall, fetchone
from functools import wraps

users_admin_bp = Blueprint('users_admin', __name__, url_prefix='/admin/users')

ROLES = ['Admin', 'Super Admin', 'Safety Officer', 'Store Keeper', 'Viewer', 'Department User']

DEPARTMENTS = [
    'Mechanical', 'Electrical Operation', 'Civil/Project', 'Marine', 'HR/Admin',
    'Safety', 'Security', 'IT', 'Operations', 'Maintenance', 'Administration',
    'Cargo', 'Logistics', 'Electrical', 'Civil'
]


# ---------- permission helpers ----------

def get_role_permissions():
    """Returns {role: {'can_create': bool, 'can_edit': bool, 'can_delete': bool}}"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT role, can_create, can_edit, can_delete FROM role_permissions")
    rows = fetchall(c)
    conn.close()
    return {r['role']: r for r in rows}


def has_permission(action):
    """action: 'can_create' | 'can_edit' | 'can_delete'"""
    role = session.get('role')
    if role in ('Admin', 'Super Admin'):
        return True
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
    """Decorator factory — checks the dynamic role_permissions table."""
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

    c.execute("""
        SELECT role, can_create, can_edit, can_delete
        FROM role_permissions
    """)
    perms = {
        row["role"]: row
        for row in fetchall(c)
    }

    conn.close()

    return render_template(
        "users_admin.html",
        users=users,
        roles=ROLES,
        departments=DEPARTMENTS,
        perms=perms,
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


# ---------- Admin: manage which role gets which permission ----------

PERMISSIONS_PAGE = """
{% extends "base.html" %}
{% block title %}Role Permissions{% endblock %}
{% block page_title %}Role Permissions{% endblock %}
{% block content %}
<div class="card">
  <div class="card-body">
    <form method="POST">
      <table class="table">
        <thead>
          <tr><th>Role</th><th>Create</th><th>Edit</th><th>Delete</th></tr>
        </thead>
        <tbody>
          {% for r in roles %}
          <tr>
            <td>{{ r }}</td>
            <td><input type="checkbox" name="create_{{ r }}" {% if perms.get(r, {}).get('can_create') %}checked{% endif %} {% if r in ['Admin','Super Admin'] %}disabled checked{% endif %}></td>
            <td><input type="checkbox" name="edit_{{ r }}" {% if perms.get(r, {}).get('can_edit') %}checked{% endif %} {% if r in ['Admin','Super Admin'] %}disabled checked{% endif %}></td>
            <td><input type="checkbox" name="delete_{{ r }}" {% if perms.get(r, {}).get('can_delete') %}checked{% endif %} {% if r in ['Admin','Super Admin'] %}disabled checked{% endif %}></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <button type="submit" class="btn btn-jsw">Save Permissions</button>
    </form>
  </div>
</div>
{% endblock %}
"""


@users_admin_bp.route('/permissions', methods=['GET', 'POST'])
@admin_required
def permissions():
    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':
        try:
            for r in ROLES:
                if r in ('Admin', 'Super Admin'):
                    continue  # always full access, not editable
                can_create = 'create_' + r in request.form
                can_edit = 'edit_' + r in request.form
                can_delete = 'delete_' + r in request.form
                c.execute(
                    """INSERT INTO role_permissions (role, can_create, can_edit, can_delete)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (role) DO UPDATE
                       SET can_create=%s, can_edit=%s, can_delete=%s""",
                    (r, can_create, can_edit, can_delete, can_create, can_edit, can_delete)
                )
            conn.commit()
            flash('Permissions updated.', 'success')
        except Exception as e:
            conn.rollback()
            flash(f"Error updating permissions: {e}", 'danger')

    c.execute("SELECT role, can_create, can_edit, can_delete FROM role_permissions")
    perms = {row['role']: row for row in fetchall(c)}
    conn.close()
    return render_template_string(PERMISSIONS_PAGE, roles=ROLES, perms=perms)