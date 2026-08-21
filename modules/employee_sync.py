
import re
import os
import threading
import time
import datetime
from flask import Blueprint, redirect, url_for, flash, session
from database.db import get_db, fetchall, fetchone
from database.sqlserver import get_sql_connection
from modules.user_admin import admin_required
from modules.logs import log_error, log_action

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
    'category':    ['CATEGORY', 'EMPLOYEE CATEGORY', 'EMP CATEGORY'],
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

# Valid categories - only these two will be synced
VALID_CATEGORIES = {
    'MBC',
    'MANPOWER BASED',
    'JBA',
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


def _load_deleted_emp_codes(pg_cursor):
    """emp_codes an admin explicitly deleted from the app. These must never
    be re-inserted by the sync, even though they're still Active in SQL
    Server — deleting them again every sync would defeat the point of
    deleting them at all."""
    pg_cursor.execute("SELECT emp_code FROM deleted_employees")
    return {row['emp_code'] for row in fetchall(pg_cursor)}


def _load_deleted_contractor_names(pg_cursor):
    """Contractor names an admin explicitly deleted from the app.
    Neither the contractor record nor any of their employees should ever
    be re-inserted by the sync."""
    pg_cursor.execute("SELECT LOWER(TRIM(name)) FROM deleted_contractors")
    return {row[0] for row in pg_cursor.fetchall()}


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


def _normalize_category(raw_category):
    """
    Normalize the category string and validate against valid categories.
    Accepted categories: MBC, MANPOWER BASED and JBA.
    Returns the normalized category or empty string if invalid.
    """
    if not raw_category:
        return ''
    
    normalized = raw_category.strip().upper()
    
    # Check if it matches any valid category
    if normalized in VALID_CATEGORIES:
        return normalized
    
    return ''


def perform_employee_sync():
    """
    Executes employee sync from SQL Server views into PostgreSQL database.
    Can be invoked by HTTP admin route or background scheduler.

    Returns dict with sync stats and status:
      {
        'success': bool,
        'summary': str,
        'added': int,
        'updated': int,
        'unchanged': int,
        'deactivated': int,
        'skipped': int,
        'invalid_category': int,
        'blocked_deleted': int,
        'contractors_added': int,
        'error_log': list,
        'error_message': str
      }
    """
    result = {
        'success': False,
        'summary': '',
        'added': 0,
        'updated': 0,
        'unchanged': 0,
        'deactivated': 0,
        'skipped': 0,
        'invalid_category': 0,
        'blocked_deleted': 0,
        'contractors_added': 0,
        'error_log': [],
        'error_message': ''
    }

    try:
        sql_conn = get_sql_connection()
    except Exception as e:
        result['error_message'] = f'Could not connect to SQL Server: {e}'
        return result

    try:
        pg = get_db()
        pg_cursor = pg.cursor()
    except Exception as e:
        try:
            sql_conn.close()
        except Exception:
            pass
        result['error_message'] = f'Could not connect to PostgreSQL: {e}'
        return result

    added = updated = unchanged = skipped = 0
    blocked_deleted = 0
    invalid_category = 0
    contractors_added = 0
    seen_emp_codes = set()
    error_log = []

    try:
        dept_lookup = _load_department_lookup(pg_cursor)
        deleted_emp_codes = _load_deleted_emp_codes(pg_cursor)
        deleted_contractor_names = _load_deleted_contractor_names(pg_cursor)

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

                if emp_code in deleted_emp_codes:
                    blocked_deleted += 1
                    continue
                seen_emp_codes.add(emp_code)

                # ---------------- STAFF VIEW ----------------
                if view_name == "view_EmployeeMaster_Report_staff":
                    category = str(row.get("category") or "").strip()
                # ---------------- ASSOCIATES VIEW ----------------
                else:
                    category = _normalize_category(str(row.get("category") or "").strip())
                    if category not in ("MBC", "MANPOWER BASED", "JBA"):
                        invalid_category += 1
                        continue

                department = _normalize_department(str(row.get('department') or '').strip(), dept_lookup, pg_cursor)
                designation = str(row.get('designation') or '').strip()
                contractor = str(row.get('contractor') or '').strip()
                raw_status = str(row.get('status') or '').strip().lower()
                status = 'Inactive' if raw_status in ('inactive', 'in active', 'no', 'n', '0', 'false') else 'Active'

                if contractor:
                    if contractor.lower().strip() in deleted_contractor_names:
                        blocked_deleted += 1
                        continue

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
                    if status == "Active":
                        pg_cursor.execute("""
                            INSERT INTO employees
                            (emp_code, name, department, contractor,
                            designation, category, status)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            emp_code,
                            name,
                            department,
                            contractor,
                            designation,
                            category,
                            status
                        ))
                        added += 1
                    else:
                        skipped += 1
                else:
                    status_changed = existing.get('status') != status
                    category_changed = existing.get('category') != category
                    
                    if status_changed or category_changed:
                        update_fields = []
                        update_values = []
                        
                        if status_changed:
                            update_fields.append("status=%s")
                            update_values.append(status)
                        
                        if category_changed:
                            update_fields.append("category=%s")
                            update_values.append(category)
                        
                        update_values.append(emp_code)
                        
                        query = f"""
                            UPDATE employees
                            SET {', '.join(update_fields)}
                            WHERE emp_code=%s
                        """
                        pg_cursor.execute(query, update_values)
                        updated += 1
                    else:
                        unchanged += 1

        deactivated = 0
        if seen_emp_codes:
            pg_cursor.execute("SELECT emp_code FROM employees WHERE status != 'Inactive'")
            all_active = fetchall(pg_cursor)
            codes_to_deactivate = [r['emp_code'] for r in all_active if r['emp_code'] not in seen_emp_codes]
            for code in codes_to_deactivate:
                pg_cursor.execute("UPDATE employees SET status='Inactive', inactive_date=CURRENT_TIMESTAMP WHERE emp_code=%s AND (inactive_date IS NULL OR status != 'Inactive')", (code,))
                deactivated += 1

        pg.commit()

        summary = (f'Sync complete: {added} added, {updated} updated, {unchanged} unchanged, '
                   f'{deactivated} marked inactive, {contractors_added} new contractors.')

        result.update({
            'success': True,
            'summary': summary,
            'added': added,
            'updated': updated,
            'unchanged': unchanged,
            'deactivated': deactivated,
            'skipped': skipped,
            'invalid_category': invalid_category,
            'blocked_deleted': blocked_deleted,
            'contractors_added': contractors_added,
            'error_log': error_log
        })

    except Exception as e:
        pg.rollback()
        result['error_message'] = str(e)
    finally:
        try:
            pg.close()
        except Exception:
            pass
        try:
            sql_conn.close()
        except Exception:
            pass

    return result


@employee_sync_bp.route('/admin/sync-employees', methods=['POST'])
@admin_required
def sync_employees():
    """
    HTTP route trigger for manual employee sync via Admin panel.
    """
    res = perform_employee_sync()

    if not res['success']:
        log_action('sync_failed', 'employee_sync', None, f"Manual sync failed: {res.get('error_message', 'Unknown error')}")
        flash(f"Sync failed: {res.get('error_message', 'Unknown error')}", 'danger')
    else:
        log_action('manual_sync', 'employee_sync', None, res['summary'])
        flash(res['summary'], 'success')
        if res['skipped']:
            flash(f"{res['skipped']} rows skipped (missing Employee ID/Name, or new-but-Inactive).", 'warning')
        if res['invalid_category']:
            flash(
                f"{res['invalid_category']} rows skipped due to invalid category (only MBC, MANPOWER BASED and JBA accepted).",
                'info'
            )
        if res['blocked_deleted']:
            flash(f"{res['blocked_deleted']} rows skipped because they were previously deleted from the app.", 'info')
        if res['error_log']:
            flash('Issues: ' + ' | '.join(res['error_log']), 'warning')

    return redirect(url_for('users_admin.index'))


# -------------------------------------------------------------------
# Automated Daily Sync Scheduler (Configurable Time & ON/OFF Toggle)
# -------------------------------------------------------------------

_scheduler_thread = None
_scheduler_lock = threading.Lock()
_stop_event = threading.Event()
_last_executed_day = None

RETRY_INTERVAL_SECONDS = 15 * 60  # 15 minutes wait between retries
MAX_SYNC_RETRIES = 3              # Maximum 3 attempts per day


def init_auto_sync_db():
    """Ensure auto_sync_config table exists in PostgreSQL."""
    try:
        pg = get_db()
        c = pg.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS auto_sync_config (
                id INT PRIMARY KEY DEFAULT 1,
                is_enabled BOOLEAN DEFAULT TRUE,
                sync_time VARCHAR(10) DEFAULT '00:00',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO auto_sync_config (id, is_enabled, sync_time)
            VALUES (1, TRUE, '00:00')
            ON CONFLICT (id) DO NOTHING;
        """)
        pg.commit()
        pg.close()
    except Exception as e:
        print(f"[AutoSync DB Init Error] {e}")


def get_auto_sync_config():
    """Fetches auto sync config (is_enabled, sync_time, last_sync_at, last_sync_summary) from existing DB tables without adding columns."""
    init_auto_sync_db()
    last_sync_at = None
    last_sync_summary = None
    try:
        pg = get_db()
        c = pg.cursor()
        c.execute("SELECT is_enabled, sync_time FROM auto_sync_config WHERE id=1")
        row = fetchone(c)

        # Query existing audit_logs table for the last employee sync entry
        c.execute("""
            SELECT created_at, description FROM audit_logs
            WHERE module='employee_sync' OR action IN ('manual_sync', 'auto_sync', 'sync', 'sync_failed')
            ORDER BY created_at DESC LIMIT 1
        """)
        audit_last = fetchone(c)
        if audit_last:
            last_sync_at = audit_last.get('created_at')
            last_sync_summary = audit_last.get('description')

        pg.close()
        if row:
            return {
                'is_enabled': bool(row.get('is_enabled', True)),
                'sync_time': str(row.get('sync_time', '00:00')).strip() or '00:00',
                'last_sync_at': last_sync_at,
                'last_sync_summary': last_sync_summary
            }
    except Exception as e:
        print(f"[AutoSync Get Config Error] {e}")
    return {'is_enabled': True, 'sync_time': '00:00', 'last_sync_at': last_sync_at, 'last_sync_summary': last_sync_summary}


def save_auto_sync_config(is_enabled, sync_time):
    """Saves auto sync config into DB."""
    init_auto_sync_db()
    sync_time_clean = (sync_time or '00:00').strip()
    try:
        pg = get_db()
        c = pg.cursor()
        c.execute("""
            INSERT INTO auto_sync_config (id, is_enabled, sync_time, updated_at)
            VALUES (1, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE
            SET is_enabled = EXCLUDED.is_enabled,
                sync_time = EXCLUDED.sync_time,
                updated_at = CURRENT_TIMESTAMP
        """, (is_enabled, sync_time_clean))
        pg.commit()
        pg.close()
        return True
    except Exception as e:
        print(f"[AutoSync Save Config Error] {e}")
        return False


def get_seconds_until_target_time(sync_time_str):
    """
    Calculates seconds remaining from now until target sync time (HH:MM format).
    If target time today is in the future, target is today HH:MM.
    If target time today has already passed, target is tomorrow HH:MM.
    """
    now = datetime.datetime.now()
    try:
        parts = sync_time_str.split(':')
        target_hour = int(parts[0])
        target_minute = int(parts[1])
    except Exception:
        target_hour = 0
        target_minute = 0

    target_today = datetime.datetime.combine(
        now.date(),
        datetime.time(hour=target_hour, minute=target_minute)
    )

    if now < target_today:
        target_dt = target_today
    else:
        target_dt = target_today + datetime.timedelta(days=1)

    return max(1.0, (target_dt - now).total_seconds())


def run_daily_auto_sync(scheduled_time="00:00"):
    """
    Executes daily employee sync at scheduled time with up to 3 tries.
    If an attempt fails, it waits 15 minutes before the next retry.
    After 3 failed attempts, it stops for the day and waits for next scheduled time.
    """
    log_error(source='auto_sync', message=f"Starting daily auto-sync process scheduled at {scheduled_time}.", level='INFO')

    for attempt in range(1, MAX_SYNC_RETRIES + 1):
        res = perform_employee_sync()
        if res['success']:
            msg = f"Auto-sync succeeded on attempt {attempt}/{MAX_SYNC_RETRIES} (Scheduled for {scheduled_time}): {res['summary']}"
            log_action('auto_sync', 'employee_sync', None, msg)
            if res.get('error_log'):
                log_error(source='auto_sync', message=f"Auto-sync warnings: {' | '.join(res['error_log'])}", level='WARNING')
            return True
        else:
            err = res.get('error_message') or 'Sync process returned failure'
            if attempt < MAX_SYNC_RETRIES:
                log_error(
                    source='auto_sync',
                    message=f"Auto-sync attempt {attempt}/{MAX_SYNC_RETRIES} failed: {err}. Retrying in 15 minutes...",
                    level='WARNING'
                )
                if _stop_event.wait(RETRY_INTERVAL_SECONDS):
                    return False
            else:
                log_error(
                    source='auto_sync',
                    message=f"Auto-sync failed all {MAX_SYNC_RETRIES} attempts today. Last error: {err}. Next try scheduled for tomorrow at {scheduled_time}.",
                    level='ERROR'
                )
                return False


def _auto_sync_worker():
    """Background worker loop that checks config and triggers daily auto-sync."""
    global _last_executed_day

    while not _stop_event.is_set():
        config = get_auto_sync_config()
        if not config['is_enabled']:
            # Auto sync is disabled: check again in 5 seconds
            if _stop_event.wait(5):
                break
            continue

        sync_time_str = config['sync_time']
        seconds_to_wait = get_seconds_until_target_time(sync_time_str)
        today_key = f"{datetime.datetime.now().strftime('%Y-%m-%d')}_{sync_time_str}"

        # If we are within 5 seconds of target time AND haven't run for today's key:
        if seconds_to_wait <= 5 and _last_executed_day != today_key:
            _last_executed_day = today_key
            run_daily_auto_sync(sync_time_str)
        else:
            # Sleep in short 5-second intervals to remain responsive to UI config updates
            sleep_chunk = min(seconds_to_wait, 5.0)
            if _stop_event.wait(sleep_chunk):
                break


def start_auto_sync_scheduler():
    """
    Starts the auto-sync background daemon thread once when application starts.
    """
    global _scheduler_thread

    # Prevent duplicate thread in Flask debug reloader parent process
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
        return

    with _scheduler_lock:
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _stop_event.clear()
            _scheduler_thread = threading.Thread(target=_auto_sync_worker, daemon=True, name="AutoSyncScheduler")
            _scheduler_thread.start()
            print("[AutoSync] Background employee sync scheduler started.")


@employee_sync_bp.route('/admin/auto-sync-config', methods=['POST'])
@admin_required
def update_auto_sync_config():
    """Updates auto-sync configuration (is_enabled toggle and sync_time)."""
    from flask import request
    is_enabled = request.form.get('is_enabled') == 'on'
    sync_time = request.form.get('sync_time', '00:00').strip()

    if save_auto_sync_config(is_enabled, sync_time):
        status_str = "ENABLED (ON)" if is_enabled else "DISABLED (OFF)"
        flash(f"Auto-sync settings updated: Status = {status_str}, Daily Time = {sync_time}", "success")
        log_action('update_config', 'auto_sync', None, f"Updated Auto-Sync to {status_str} at {sync_time}")
    else:
        flash("Failed to save Auto-sync configuration.", "danger")

    return redirect(url_for('users_admin.index'))
