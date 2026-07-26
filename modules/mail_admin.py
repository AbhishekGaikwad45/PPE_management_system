"""
modules/mail_admin.py
Admin-only Mail page:
  - SMTP configuration, stored in DB (smtp_config table, single row id=1)
    and editable from the UI (host/port/username/password/from/TLS/schedule).
  - Mail queue: list of queued/sent/failed emails with retry.

modules/mailer.py reads its settings via get_smtp_settings() below so both
the .env values (fallback / first-run defaults) and DB-saved values work.
"""

from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchall, fetchone

mail_admin_bp = Blueprint('mail_admin', __name__, url_prefix='/admin/mail')


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') not in ('Admin', 'Super Admin'):
            flash('You do not have permission to access Mail settings.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapped


def get_smtp_settings():
    """Returns the saved SMTP config as a dict, or None if never configured."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM smtp_config WHERE id=1")
    row = fetchone(c)
    conn.close()
    return row


@mail_admin_bp.route('/')
@admin_required
def index():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM smtp_config WHERE id=1")
    config = fetchone(c)

    c.execute("SELECT * FROM mail_queue ORDER BY created_at DESC LIMIT 200")
    queue = fetchall(c)
    conn.close()

    return render_template("mail_admin.html", config=config, queue=queue)


@mail_admin_bp.route('/save', methods=['POST'])
@admin_required
def save_config():
    enabled = 'enabled' in request.form
    host = request.form.get('host', '').strip()
    port = request.form.get('port', '').strip() or 587
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    from_email = request.form.get('from_email', '').strip()
    from_name = request.form.get('from_name', '').strip()
    use_tls = 'use_tls' in request.form
    schedule_minutes = request.form.get('schedule_minutes', '').strip() or 5

    conn = get_db()
    c = conn.cursor()
    try:
        # Keep the existing password if the field was left blank (masked in UI)
        if password:
            c.execute(
                """INSERT INTO smtp_config (id, enabled, host, port, username, password,
                       from_email, from_name, use_tls, schedule_minutes, updated_at)
                   VALUES (1,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                   ON CONFLICT (id) DO UPDATE SET
                       enabled=%s, host=%s, port=%s, username=%s, password=%s,
                       from_email=%s, from_name=%s, use_tls=%s, schedule_minutes=%s,
                       updated_at=CURRENT_TIMESTAMP""",
                (enabled, host, port, username, password, from_email, from_name, use_tls, schedule_minutes,
                 enabled, host, port, username, password, from_email, from_name, use_tls, schedule_minutes)
            )
        else:
            c.execute(
                """INSERT INTO smtp_config (id, enabled, host, port, username, password,
                       from_email, from_name, use_tls, schedule_minutes, updated_at)
                   VALUES (1,%s,%s,%s,%s,'',%s,%s,%s,%s,CURRENT_TIMESTAMP)
                   ON CONFLICT (id) DO UPDATE SET
                       enabled=%s, host=%s, port=%s, username=%s,
                       from_email=%s, from_name=%s, use_tls=%s, schedule_minutes=%s,
                       updated_at=CURRENT_TIMESTAMP""",
                (enabled, host, port, username, from_email, from_name, use_tls, schedule_minutes,
                 enabled, host, port, username, from_email, from_name, use_tls, schedule_minutes)
            )
        conn.commit()
        flash('SMTP configuration saved.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f"Error saving SMTP config: {e}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('mail_admin.index'))


@mail_admin_bp.route('/send-now', methods=['POST'])
@admin_required
def send_now():
    """Manually trigger sending of all pending mail in the queue."""
    from modules.mailer import process_mail_queue
    sent, failed = process_mail_queue()
    flash(f"Mail run complete: {sent} sent, {failed} failed.", 'success' if not failed else 'warning')
    return redirect(url_for('mail_admin.index'))


@mail_admin_bp.route('/retry-failed', methods=['POST'])
@admin_required
def retry_failed():
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE mail_queue SET status='pending', error=NULL WHERE status='failed'")
    conn.commit()
    conn.close()

    from modules.mailer import process_mail_queue
    sent, failed = process_mail_queue()
    flash(f"Retried failed mail: {sent} sent, {failed} still failed.", 'success' if not failed else 'warning')
    return redirect(url_for('mail_admin.index'))
