from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchone
from modules.logs import log_action

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = fetchone(c)
        conn.close()
        if user:
            session['user'] = username
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            session['department'] = user['department'] if user['department'] else None
            session['assigned_departments'] = user['assigned_departments'] if 'assigned_departments' in user and user['assigned_departments'] else []
            
            dept_str = user['department'] or 'All Access'
            log_action('login', 'auth', user['id'], f"User '{username}' ({user['full_name']}) logged in successfully", department=dept_str)
            flash(f"Welcome, {user['full_name']}!", 'success')
            return redirect(url_for('dashboard.index'))
        else:
            log_action('login_failed', 'auth', None, f"Failed login attempt for username '{username}'")
            flash('Invalid username or password.', 'danger')
    return render_template('login/login.html')

@auth_bp.route('/logout')
def logout():
    user = session.get('user')
    if user:
        log_action('logout', 'auth', None, f"User '{user}' logged out")
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('auth.login'))
