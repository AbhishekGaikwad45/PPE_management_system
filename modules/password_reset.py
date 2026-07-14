"""
modules/password_reset.py  -- DEBUG VERSION

This is a TEMPORARY debugging variant of the forgot-password flow.
It shows the EXACT reason a request failed (user not found / no email
on file / OTP insert failed / SMTP send failed with details) instead of
the generic "If that account exists..." message.

*** DO NOT USE THIS IN PRODUCTION. ***
Once you've confirmed things work, switch back to the version that
always shows the generic message (to avoid leaking which
usernames/emails are registered).

Set DEBUG_PASSWORD_RESET = True below to turn debug messages on/off
without deleting the code, so you can flip it back off quickly.
"""

import random
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchone
from modules.mailer import send_otp_email

password_reset_bp = Blueprint('password_reset', __name__)

OTP_VALID_MINUTES = 10

# Flip this to False to restore the generic, non-leaking message.
DEBUG_PASSWORD_RESET = True


def _generate_otp():
    return f"{random.randint(0, 999999):06d}"


@password_reset_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT id, username, full_name, email FROM users WHERE username=%s OR email=%s",
            (identifier, identifier)
        )
        user = fetchone(c)

        generic_msg = "If that account exists and has an email on file, an OTP has been sent."

        # --- CASE 1: no matching user row at all ---
        if not user:
            conn.close()
            if DEBUG_PASSWORD_RESET:
                flash(f"[DEBUG] No user found matching '{identifier}'. "
                      f"Check spelling/case, or that this exact value exists in the users table.", 'danger')
            else:
                flash(generic_msg, 'info')
            return redirect(url_for('password_reset.forgot_password'))

        # --- CASE 2: user found but email is empty/NULL ---
        if not user.get('email'):
            conn.close()
            if DEBUG_PASSWORD_RESET:
                flash(f"[DEBUG] User '{user['username']}' (id={user['id']}) was found, "
                      f"but the email column is empty/NULL for this account. "
                      f"Run: UPDATE users SET email='you@example.com' WHERE id={user['id']};", 'danger')
            else:
                flash(generic_msg, 'info')
            return redirect(url_for('password_reset.forgot_password'))

        # --- CASE 3: user + email both present -> try to create OTP ---
        otp_code = _generate_otp()
        expires_at = datetime.now() + timedelta(minutes=OTP_VALID_MINUTES)

        try:
            c.execute(
                "INSERT INTO password_reset_otp (user_id, otp_code, expires_at) VALUES (%s, %s, %s)",
                (user['id'], otp_code, expires_at)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.close()
            if DEBUG_PASSWORD_RESET:
                flash(f"[DEBUG] Failed to insert OTP row into password_reset_otp table. "
                      f"Detail: {e}", 'danger')
            else:
                flash('Something went wrong generating the OTP. Please try again.', 'danger')
            return redirect(url_for('password_reset.forgot_password'))
        conn.close()

        # --- CASE 4: try to actually send the email ---
        sent, err = send_otp_email(user['email'], otp_code, user.get('full_name'))
        if not sent:
            if DEBUG_PASSWORD_RESET:
                flash(f"[DEBUG] OTP was generated (code: {otp_code}) but the EMAIL FAILED TO SEND. "
                      f"Reason from mailer: {err}", 'danger')
            else:
                flash(f"Could not send OTP email: {err}", 'danger')
            return redirect(url_for('password_reset.forgot_password'))

        # --- SUCCESS ---
        session['reset_user_id'] = user['id']
        session['reset_username'] = user['username']
        if DEBUG_PASSWORD_RESET:
            flash(f"[DEBUG] Email sent successfully to {user['email']}. OTP code was: {otp_code}", 'success')
        else:
            flash(generic_msg, 'info')
        return redirect(url_for('password_reset.verify_otp'))

    return render_template('login/forgot_password.html')


@password_reset_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    user_id = session.get('reset_user_id')
    if not user_id:
        flash('Please start the password reset process again.', 'danger')
        return redirect(url_for('password_reset.forgot_password'))

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()

        conn = get_db()
        c = conn.cursor()
        c.execute(
            """SELECT id, otp_code, expires_at, used FROM password_reset_otp
               WHERE user_id=%s ORDER BY id DESC LIMIT 1""",
            (user_id,)
        )
        row = fetchone(c)
        conn.close()

        if not row:
            flash('No OTP request found. Please request a new one.', 'danger')
            return redirect(url_for('password_reset.forgot_password'))

        if row['used']:
            flash('This OTP has already been used. Please request a new one.', 'danger')
            return redirect(url_for('password_reset.forgot_password'))

        if datetime.now() > row['expires_at']:
            flash('This OTP has expired. Please request a new one.', 'danger')
            return redirect(url_for('password_reset.forgot_password'))

        if entered_otp != row['otp_code']:
            flash('Incorrect OTP. Please try again.', 'danger')
            return redirect(url_for('password_reset.verify_otp'))

        session['reset_otp_verified'] = True
        return redirect(url_for('password_reset.reset_password'))

    return render_template('login/verify_otp.html')


@password_reset_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    user_id = session.get('reset_user_id')
    if not user_id or not session.get('reset_otp_verified'):
        flash('Please verify the OTP first.', 'danger')
        return redirect(url_for('password_reset.forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not new_password or len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('password_reset.reset_password'))

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('password_reset.reset_password'))

        conn = get_db()
        c = conn.cursor()
        try:
            c.execute("UPDATE users SET password=%s WHERE id=%s", (new_password, user_id))
            c.execute(
                "UPDATE password_reset_otp SET used=TRUE WHERE user_id=%s AND used=FALSE",
                (user_id,)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Error resetting password: {e}", 'danger')
            return redirect(url_for('password_reset.reset_password'))
        conn.close()

        session.pop('reset_user_id', None)
        session.pop('reset_username', None)
        session.pop('reset_otp_verified', None)

        flash('Password reset successfully. Please sign in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('login/reset_password.html')