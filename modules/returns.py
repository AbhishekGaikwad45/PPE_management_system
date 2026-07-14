from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchall, fetchone
from datetime import date

returns_bp = Blueprint('returns', __name__)

@returns_bp.route('/returns')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT ir.id, e.name as emp_name, e.emp_code, e.department, i.item_name, ir.qty, ir.issue_date, ir.return_due_date FROM issue_register ir JOIN employees e ON ir.employee_id=e.id JOIN items i ON ir.item_id=i.id WHERE ir.returnable=1 AND ir.status='Issued' ORDER BY ir.return_due_date")
    pending = fetchall(c)
    c.execute("SELECT rr.*, e.name as emp_name, i.item_name FROM return_register rr JOIN employees e ON rr.employee_id=e.id JOIN items i ON rr.item_id=i.id ORDER BY rr.return_date DESC LIMIT 50")
    returns = fetchall(c)
    conn.close()
    return render_template('returns.html', pending=pending, returns=returns, today=date.today())

@returns_bp.route('/returns/add', methods=['POST'])
def add():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    try:
        issue_id = int(request.form['issue_id'])
        qty = int(request.form['qty'])
        c.execute("SELECT * FROM issue_register WHERE id=%s", (issue_id,))
        issue = fetchone(c)
        if not issue:
            flash('Issue record not found.', 'danger')
            conn.close()
            return redirect(url_for('returns.index'))
        c.execute("INSERT INTO return_register (return_date,issue_id,employee_id,item_id,qty,condition,received_by,remarks) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                  (request.form['return_date'], issue_id, issue['employee_id'], issue['item_id'], qty,
                   request.form.get('condition','Good'), session['full_name'], request.form.get('remarks','')))
        c.execute("UPDATE items SET stock=stock+%s WHERE id=%s", (qty, issue['item_id']))
        c.execute("UPDATE issue_register SET status='Returned' WHERE id=%s", (issue_id,))
        conn.commit()
        flash('Return recorded successfully.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('returns.index'))
