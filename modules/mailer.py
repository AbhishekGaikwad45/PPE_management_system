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

SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_NAME = os.environ.get('SMTP_FROM_NAME', 'PPE Management System')
SMTP_TIMEOUT = int(os.environ.get('SMTP_TIMEOUT', '15'))


def _connect():
    """
    Returns a connected (and, for STARTTLS mode, TLS-upgraded) SMTP
    server object, using SSL mode for port 465 and STARTTLS otherwise.
    Raises the underlying exception on failure - caller handles it.
    """
    context = ssl.create_default_context()

    if SMTP_PORT == 465:
        logger.info(f"[STEP 1] Connecting via SSL to {SMTP_HOST}:{SMTP_PORT} (timeout={SMTP_TIMEOUT}s)...")
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT, context=context)
        logger.info("[STEP 1] SSL connection established.")
        return server
    else:
        logger.info(f"[STEP 1] Connecting to {SMTP_HOST}:{SMTP_PORT} (timeout={SMTP_TIMEOUT}s)...")
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
        logger.info("[STEP 1] Connected. Starting TLS handshake...")
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
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "[CONFIG] SMTP is not configured (missing SMTP_USER / SMTP_PASSWORD in .env)"

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg['To'] = to_email
    msg.attach(MIMEText(html_body, 'html'))

    server = None

    # --- STEP 1 (+2 for STARTTLS mode): connect / TLS ---
    try:
        server = _connect()
    except socket.gaierror as e:
        msg_err = f"[DNS/CONNECT] Could not resolve host '{SMTP_HOST}'. Check SMTP_HOST spelling / DNS. Detail: {e}"
        logger.error(msg_err)
        return False, msg_err
    except (socket.timeout, TimeoutError) as e:
        msg_err = (f"[DNS/CONNECT] Timed out reaching {SMTP_HOST}:{SMTP_PORT}. "
                   f"Almost always a firewall/network block on this port. "
                   f"Try switching SMTP_PORT to {'587' if SMTP_PORT == 465 else '465'} in .env. Detail: {e}")
        logger.error(msg_err)
        return False, msg_err
    except OSError as e:
        # This is what WinError 10060 / 10061 surface as
        msg_err = (f"[DNS/CONNECT] Connection to {SMTP_HOST}:{SMTP_PORT} failed "
                   f"(likely blocked port / firewall / no route). "
                   f"Try switching SMTP_PORT to {'587' if SMTP_PORT == 465 else '465'} in .env. Detail: {e}")
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
            logger.info(f"[STEP 3] Logging in as {SMTP_USER}...")
            server.login(SMTP_USER, SMTP_PASSWORD)
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
            server.sendmail(SMTP_USER, to_email, msg.as_string())
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