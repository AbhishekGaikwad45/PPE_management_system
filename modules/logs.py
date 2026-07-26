"""
modules/logs.py
Admin-only Logs page:
  - Activity / audit log: which user created / edited / deleted what.
  - Error log: unhandled exceptions captured by the global error handler in app.py.

log_action() is imported and called from other modules (e.g. user_admin.py)
right after a successful create/edit/delete, e.g.:

    from modules.logs import log_action
    log_action('create', 'users', user_id, f"Created user '{username}'")
"""

import traceback as tb_module
from flask import Blueprint, render_template, request, session
from database.db import get_db, fetchall

logs_bp = Blueprint('logs', __name__, url_prefix='/admin/logs')


def admin_required(f):
    from functools import wraps
    from flask import redirect, url_for, flash

    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') not in ('Admin', 'Super Admin'):
            flash('You do not have permission to access Logs.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapped


# ---------- write helpers (call these from other modules) ----------

def log_action(action, module, record_id, description):
    """Record a create/edit/delete audit entry for the currently logged-in user.
    Never raises - a logging failure must not break the calling request."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """INSERT INTO audit_logs (username, full_name, action, module, record_id, description)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (session.get('user'), session.get('full_name'), action, module,
             str(record_id) if record_id is not None else None, description)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def log_error(source, message, traceback_str=None, method=None, path=None, level='ERROR'):
    """Record an unhandled exception / error. Never raises."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """INSERT INTO error_logs (level, source, method, path, message, traceback, username)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (level, source, method, path, message, traceback_str, session.get('user'))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ---------- admin page ----------

@logs_bp.route('/')
@admin_required
def index():
    conn = get_db()
    c = conn.cursor()

    # Activity chart: last 8 days, count of audit actions per day
    c.execute("""
        SELECT TO_CHAR(created_at, 'YYYY-MM-DD') AS day, COUNT(*) AS cnt
        FROM audit_logs
        WHERE created_at >= CURRENT_DATE - INTERVAL '8 days'
        GROUP BY day ORDER BY day
    """)
    activity_by_day = fetchall(c)

    action_filter = request.args.get('action', 'all')     # all | create | edit | delete
    module_filter = request.args.get('module', '').strip()
    search = request.args.get('q', '').strip()

    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if action_filter != 'all':
        query += " AND action = %s"
        params.append(action_filter)
    if module_filter:
        query += " AND module = %s"
        params.append(module_filter)
    if search:
        query += " AND (description ILIKE %s OR username ILIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY created_at DESC LIMIT 500"
    c.execute(query, params)
    audit_rows = fetchall(c)

    c.execute("SELECT DISTINCT module FROM audit_logs ORDER BY module")
    modules_list = [r['module'] for r in fetchall(c)]

    # Error logs
    err_search = request.args.get('eq', '').strip()
    err_query = "SELECT * FROM error_logs WHERE 1=1"
    err_params = []
    if err_search:
        err_query += " AND (message ILIKE %s OR source ILIKE %s OR path ILIKE %s)"
        err_params.extend([f"%{err_search}%", f"%{err_search}%", f"%{err_search}%"])
    err_query += " ORDER BY created_at DESC LIMIT 300"
    c.execute(err_query, err_params)
    error_rows = fetchall(c)

    conn.close()

    return render_template(
        "logs_admin.html",
        activity_by_day=activity_by_day,
        audit_rows=audit_rows,
        error_rows=error_rows,
        modules_list=modules_list,
        action_filter=action_filter,
        module_filter=module_filter,
        search=search,
        err_search=err_search,
    )
