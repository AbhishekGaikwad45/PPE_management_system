from flask import Flask, render_template, redirect, url_for, session, flash, request
from database.migrations import run_migrations
from modules.auth import auth_bp
from modules.employees import employees_bp
from modules.items import items_bp
from modules.stock import stock_bp
from modules.issues import issues_bp
from modules.returns import returns_bp
from modules.expiry import expiry_bp
from modules.calibration import calibration_bp
from modules.reports import reports_bp
from modules.dashboard import dashboard_bp
from modules.user_admin import users_admin_bp 
from modules.contractor_issues import contractor_issues_bp
from modules.employee_sync import employee_sync_bp
from modules.password_reset import password_reset_bp
from modules.logs import logs_bp, log_error
from modules.mail_admin import mail_admin_bp
from modules.department_stock import department_stock_bp
import os
import traceback

app = Flask(__name__)
app.secret_key = "ppe_jsw_secret_2024"

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(employees_bp)
app.register_blueprint(items_bp)
app.register_blueprint(stock_bp)
app.register_blueprint(issues_bp)
app.register_blueprint(returns_bp)
app.register_blueprint(expiry_bp)
app.register_blueprint(calibration_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(users_admin_bp)
app.register_blueprint(contractor_issues_bp)
app.register_blueprint(employee_sync_bp)
app.register_blueprint(password_reset_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(mail_admin_bp)
app.register_blueprint(department_stock_bp)


@app.errorhandler(Exception)
def handle_unhandled_exception(e):
    """Logs every unhandled exception to error_logs (visible on Admin > Logs)
    then re-raises so Flask's normal error handling (debug page in dev,
    500 page in prod) still runs exactly as before."""
    tb_str = traceback.format_exc()
    last_frame = traceback.extract_tb(e.__traceback__)[-1] if e.__traceback__ else None
    source = f"{os.path.basename(last_frame.filename)}:{last_frame.lineno}" if last_frame else "app"

    log_error(
        source=source,
        message=f"Unhandled exception on {request.method} {request.path}",
        traceback_str=tb_str,
        method=request.method,
        path=request.path,
    )
    raise e


@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    return redirect(url_for('dashboard.index'))

@app.route("/favicon.ico")
def favicon():
    return "", 204    

if __name__ == '__main__':
    # Run migrations once with: python init_database.py  (or: alembic upgrade head)
    # Set RUN_MIGRATIONS_ON_STARTUP=true in .env only if you want this on every start.
    if os.environ.get('RUN_MIGRATIONS_ON_STARTUP', '').lower() in ('1', 'true', 'yes'):
        run_migrations()
    app.run(debug=True, host='0.0.0.0', port=5002)
