from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchone

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
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
            flash(f"Welcome, {user['full_name']}!", 'success')
            return redirect(url_for('dashboard.index'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login/login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('auth.login'))
