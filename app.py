from flask import Flask, render_template, redirect, url_for, session, flash
from database.db import init_db
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
import os

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

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    return redirect(url_for('dashboard.index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5001)
