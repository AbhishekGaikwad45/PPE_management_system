"""
utils/mailer.py
Small helper to send OTP / notification emails via SMTP.

Supports BOTH SMTP modes, chosen automatically based on SMTP_PORT:
    - Port 465  -> implicit SSL (smtplib.SMTP_SSL)
    - Port 587  -> STARTTLS (smtplib.SMTP + starttls())
    - Any other port -> STARTTLS by default

WHY: some corporate/industrial firewalls block port 587 (STARTTLS)
but allow port 465 (SSL), or vice versa. If 587 fails with
WinError 10060, try switching SMTP_PORT to 465 in your .env
WITHOUT changing any code - this file adapts automatically.

Add these to your .env file:

    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587            <- try 465 if 587 is blocked
    SMTP_USER=your_email@gmail.com
    SMTP_PASSWORD=your_app_password
    SMTP_FROM_NAME=PPE Management System
    SMTP_TIMEOUT=15

Note: for Gmail you must use an "App Password", not your normal
account password (Google account -> Security -> App Passwords).

Quick test before touching the app, from PowerShell:
    Test-NetConnection smtp.gmail.com -Port 465
    Test-NetConnection smtp.gmail.com -Port 587
Whichever one returns TcpTestSucceeded : True is the port to use.
"""

import os
import socket
import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("mailer")
logging.basicConfig(level=logging.INFO)

SMTP_TIMEOUT = int(os.environ.get('SMTP_TIMEOUT', '15'))


def get_settings():
    """
    SMTP settings, DB-first: reads the `smtp_config` table (row id=1, saved
    from the admin Mail page) and falls back to .env values for any field
    that hasn't been configured in the DB yet, so first-run / no-DB-row
    still works exactly like before.
    Returns a dict: host, port, username, password, from_name, from_email,
    use_tls, enabled.
    """
    db_row = None
    try:
        from database.db import get_db, fetchone
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM smtp_config WHERE id=1")
        db_row = fetchone(c)
        conn.close()
    except Exception:
        db_row = None

    env_defaults = {
        'host': os.environ.get('SMTP_HOST', 'smtp.gmail.com'),
        'port': int(os.environ.get('SMTP_PORT', '587')),
        'username': os.environ.get('SMTP_USER', ''),
        'password': os.environ.get('SMTP_PASSWORD', ''),
        'from_name': os.environ.get('SMTP_FROM_NAME', 'PPE Management System'),
        'from_email': os.environ.get('SMTP_USER', ''),
        'use_tls': True,
        'enabled': True,
    }

    if not db_row:
        return env_defaults

    return {
        'host': db_row.get('host') or env_defaults['host'],
        'port': db_row.get('port') or env_defaults['port'],
        'username': db_row.get('username') or env_defaults['username'],
        'password': db_row.get('password') or env_defaults['password'],
        'from_name': db_row.get('from_name') or env_defaults['from_name'],
        'from_email': db_row.get('from_email') or db_row.get('username') or env_defaults['from_email'],
        'use_tls': db_row.get('use_tls') if db_row.get('use_tls') is not None else env_defaults['use_tls'],
        'enabled': db_row.get('enabled') if db_row.get('enabled') is not None else True,
    }


def _connect(settings):
    """
    Returns a connected (and, for STARTTLS mode, TLS-upgraded) SMTP
    server object, using SSL mode for port 465 and STARTTLS otherwise.
    Raises the underlying exception on failure - caller handles it.
    """
    host = settings['host']
    port = settings['port']
    context = ssl.create_default_context()

    if port == 465:
        logger.info(f"[STEP 1] Connecting via SSL to {host}:{port} (timeout={SMTP_TIMEOUT}s)...")
        server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT, context=context)
        logger.info("[STEP 1] SSL connection established.")
        return server
    else:
        logger.info(f"[STEP 1] Connecting to {host}:{port} (timeout={SMTP_TIMEOUT}s)...")
        server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT)
        logger.info("[STEP 1] Connected. Starting TLS handshake...")
        if settings.get('use_tls', True):
            server.starttls(context=context)
            logger.info("[STEP 2] TLS handshake OK.")
        return server


def send_email(to_email, subject, html_body):
    """
    Returns (success: bool, error_message: str|None)
    error_message is prefixed with the STEP that failed, e.g.:
        "[DNS/CONNECT] ..."
        "[STARTTLS] ..."
        "[LOGIN] ..."
        "[SEND] ..."
    """
    settings = get_settings()

    if not settings.get('enabled', True):
        return False, "[CONFIG] Mail is disabled in Admin > Mail settings."

    if not settings['username'] or not settings['password']:
        return False, "[CONFIG] SMTP is not configured (set Username / Password in Admin > Mail)"

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{settings['from_name']} <{settings['from_email']}>"
    msg['To'] = to_email
    msg.attach(MIMEText(html_body, 'html'))

    server = None
    host, port = settings['host'], settings['port']

    # --- STEP 1 (+2 for STARTTLS mode): connect / TLS ---
    try:
        server = _connect(settings)
    except socket.gaierror as e:
        msg_err = f"[DNS/CONNECT] Could not resolve host '{host}'. Check the Host field. Detail: {e}"
        logger.error(msg_err)
        return False, msg_err
    except (socket.timeout, TimeoutError) as e:
        msg_err = (f"[DNS/CONNECT] Timed out reaching {host}:{port}. "
                   f"Almost always a firewall/network block on this port. "
                   f"Try switching Port to {'587' if port == 465 else '465'} in Admin > Mail. Detail: {e}")
        logger.error(msg_err)
        return False, msg_err
    except OSError as e:
        # This is what WinError 10060 / 10061 surface as
        msg_err = (f"[DNS/CONNECT] Connection to {host}:{port} failed "
                   f"(likely blocked port / firewall / no route). "
                   f"Try switching Port to {'587' if port == 465 else '465'} in Admin > Mail. Detail: {e}")
        logger.error(msg_err)
        return False, msg_err
    except smtplib.SMTPException as e:
        msg_err = f"[STARTTLS] Server rejected/failed STARTTLS. Detail: {e}"
        logger.error(msg_err)
        return False, msg_err
    except ssl.SSLError as e:
        msg_err = f"[STARTTLS] TLS/SSL error during handshake. Detail: {e}"
        logger.error(msg_err)
        return False, msg_err

    try:
        # --- STEP 3: Authentication ---
        try:
            logger.info(f"[STEP 3] Logging in as {settings['username']}...")
            server.login(settings['username'], settings['password'])
            logger.info("[STEP 3] Login OK.")
        except smtplib.SMTPAuthenticationError as e:
            msg_err = (f"[LOGIN] Authentication failed. For Gmail, make sure SMTP_PASSWORD "
                       f"is an App Password, not your normal password, and that 2FA is enabled. Detail: {e}")
            logger.error(msg_err)
            return False, msg_err
        except smtplib.SMTPException as e:
            msg_err = f"[LOGIN] Login step failed. Detail: {e}"
            logger.error(msg_err)
            return False, msg_err

        # --- STEP 4: Send the message ---
        try:
            logger.info(f"[STEP 4] Sending email to {to_email}...")
            server.sendmail(settings['username'], to_email, msg.as_string())
            logger.info("[STEP 4] Email sent OK.")
        except smtplib.SMTPRecipientsRefused as e:
            msg_err = f"[SEND] Recipient address refused: {to_email}. Detail: {e}"
            logger.error(msg_err)
            return False, msg_err
        except smtplib.SMTPException as e:
            msg_err = f"[SEND] Failed to send message. Detail: {e}"
            logger.error(msg_err)
            return False, msg_err

        return True, None

    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_otp_email(to_email, otp_code, full_name=None):
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    subject = "Your Password Reset OTP - PPE Management System"
    html_body = f"""
    <div style="font-family:Segoe UI,sans-serif; max-width:480px; margin:auto;">
      <h3 style="color:#1A3A5C;">Password Reset Request</h3>
      <p>{greeting}</p>
      <p>We received a request to reset your password for the PPE & Equipment
      Management System. Use the OTP below to continue. It is valid for
      <b>10 minutes</b>.</p>
      <div style="font-size:28px; font-weight:bold; letter-spacing:6px;
                  background:#EEF2FF; color:#1A3A5C; padding:16px 0;
                  text-align:center; border-radius:8px; margin:20px 0;">
        {otp_code}
      </div>
      <p>If you did not request this, you can safely ignore this email —
      your password will remain unchanged.</p>
      <p style="color:#888; font-size:12px;">JSW Dharamtar Port Operations
      Safety Management</p>
    </div>
    """
    return send_email(to_email, subject, html_body)

# ---------- mail queue (Admin > Mail page: queue list, Send Now, Retry Failed) ----------

def queue_mail(to_email, subject, html_body):
    """Insert a row into mail_queue as 'pending'. Does not send immediately -
    call process_mail_queue() (or use the Admin > Mail 'Send Now' button)
    to actually deliver it. Returns the new row id, or None on failure."""
    try:
        from database.db import get_db
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO mail_queue (to_email, subject, body, status) VALUES (%s,%s,%s,'pending') RETURNING id",
            (to_email, subject, html_body)
        )
        new_id = c.fetchone()[0]
        conn.commit()
        conn.close()
        return new_id
    except Exception as e:
        logger.error(f"[QUEUE] Failed to queue mail to {to_email}: {e}")
        return None


def process_mail_queue(limit=50):
    """Sends all 'pending' rows in mail_queue (used by Send Now / Retry Failed
    and can also be called from a scheduler). Returns (sent_count, failed_count)."""
    from database.db import get_db, fetchall

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, to_email, subject, body, retries FROM mail_queue WHERE status='pending' ORDER BY created_at LIMIT %s", (limit,))
    rows = fetchall(c)
    conn.close()

    sent, failed = 0, 0
    for row in rows:
        ok, err = send_email(row['to_email'], row['subject'] or '', row['body'] or '')
        conn = get_db()
        c = conn.cursor()
        if ok:
            c.execute(
                "UPDATE mail_queue SET status='sent', sent_at=CURRENT_TIMESTAMP, error=NULL WHERE id=%s",
                (row['id'],)
            )
            sent += 1
        else:
            c.execute(
                "UPDATE mail_queue SET status='failed', retries=retries+1, error=%s WHERE id=%s",
                (err, row['id'])
            )
            failed += 1
        conn.commit()
        conn.close()

    return sent, failed
