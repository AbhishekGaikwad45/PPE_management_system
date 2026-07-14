from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchall
from datetime import date

calibration_bp = Blueprint('calibration', __name__)

@calibration_bp.route('/calibration')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM items WHERE has_calibration=1 ORDER BY item_name")
    items = fetchall(c)
    c.execute("SELECT c.*, i.item_name, i.item_code FROM calibration_tracking c JOIN items i ON c.item_id=i.id ORDER BY c.next_calibration_date")
    records = fetchall(c)
    conn.close()
    return render_template('calibration.html', items=items, records=records, today=date.today())

@calibration_bp.route('/calibration/add', methods=['POST'])
def add():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    try:
        c.execute("INSERT INTO calibration_tracking (item_id,serial_no,last_calibration_date,next_calibration_date,calibrated_by,status) VALUES (%s,%s,%s,%s,%s,%s)",
                  (request.form['item_id'], request.form.get('serial_no',''), request.form.get('last_calibration_date',''),
                   request.form['next_calibration_date'], request.form.get('calibrated_by',''), 'Valid'))
        conn.commit()
        flash('Calibration record added.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('calibration.index'))

@calibration_bp.route('/calibration/expire/<int:id>')
def expire(id):
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE calibration_tracking SET status='Expired' WHERE id=%s", (id,))
    conn.commit(); conn.close()
    flash('Calibration marked as expired.', 'info')
    return redirect(url_for('calibration.index'))
