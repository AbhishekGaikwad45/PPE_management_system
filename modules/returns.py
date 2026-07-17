from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchall, fetchone
from datetime import date

returns_bp = Blueprint('returns', __name__)

@returns_bp.route('/returns')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()

    # PPE types for the dropdown — auto-populated from Item Master
    c.execute("SELECT id, item_name FROM items ORDER BY item_name")
    items = fetchall(c)

    # History — disposal records, most recent first
    c.execute("""
        SELECT rr.*, i.item_name
        FROM return_register rr
        JOIN items i ON rr.item_id = i.id
        ORDER BY rr.return_date DESC, rr.id DESC
        LIMIT 50
    """)
    returns = fetchall(c)
    conn.close()
    return render_template('returns.html', items=items, returns=returns, today=date.today())


@returns_bp.route('/returns/add-disposal', methods=['POST'])
def add_disposal():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    try:
        item_id = int(request.form['item_id'])

        qty_no_raw = request.form.get('qty_no', '').strip()
        qty_kg_raw = request.form.get('qty_kg', '').strip()
        qty_no = int(qty_no_raw) if qty_no_raw else None
        qty_kg = float(qty_kg_raw) if qty_kg_raw else None

        if not qty_no and not qty_kg:
            flash('Please enter a quantity in No. or Kg.', 'danger')
            conn.close()
            return redirect(url_for('returns.index'))

        c.execute("""
            INSERT INTO return_register
                (return_date, employee_id, item_id, qty, qty_no, qty_kg, condition, received_by, remarks)
            VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.form['return_date'],
            item_id,
            qty_no or 0,          # legacy `qty` column kept satisfied (NOT NULL)
            qty_no,
            qty_kg,
            'Disposed',
            session['full_name'],
            request.form.get('remarks', '')
        ))

        # Only reduce stock count when a countable (No.) quantity was disposed
        if qty_no:
            c.execute("UPDATE items SET stock = stock - %s WHERE id=%s", (qty_no, item_id))

        conn.commit()
        flash('Disposal record saved successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('returns.index'))