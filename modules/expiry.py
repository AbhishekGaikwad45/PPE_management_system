from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchall
from datetime import date

expiry_bp = Blueprint('expiry', __name__)

@expiry_bp.route('/expiry')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM items WHERE has_expiry=1 ORDER BY item_name")
    items = fetchall(c)
    c.execute("SELECT e.*, i.item_name, i.item_code FROM expiry_tracking e JOIN items i ON e.item_id=i.id ORDER BY e.expiry_date")
    records = fetchall(c)
    conn.close()
    return render_template('expiry.html', items=items, records=records, today=date.today().strftime('%Y-%m-%d'))

@expiry_bp.route('/expiry/add', methods=['POST'])
def add():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    try:
        c.execute("INSERT INTO expiry_tracking (item_id,batch_no,manufacture_date,expiry_date,qty,status) VALUES (%s,%s,%s,%s,%s,%s)",
                  (request.form['item_id'], request.form.get('batch_no',''), request.form.get('manufacture_date',''),
                   request.form['expiry_date'], request.form.get('qty',0), 'Active'))
        conn.commit()
        flash('Expiry record added.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('expiry.index'))

@expiry_bp.route('/expiry/dispose/<int:id>')
def dispose(id):
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE expiry_tracking SET status='Disposed' WHERE id=%s", (id,))
    conn.commit(); conn.close()
    flash('Item marked as disposed.', 'info')
    return redirect(url_for('expiry.index'))
