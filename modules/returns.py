from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchall, fetchone
from datetime import date
from modules.user_admin import has_permission

returns_bp = Blueprint('returns', __name__)


@returns_bp.route('/returns')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()

    c.execute("SELECT id, item_name FROM items ORDER BY item_name")
    items = fetchall(c)

    c.execute("""
        SELECT rr.*, i.item_name
        FROM return_register rr
        JOIN items i ON rr.item_id = i.id
        ORDER BY rr.return_date DESC, rr.id DESC
        LIMIT 50
    """)
    returns = fetchall(c)
    conn.close()

    can_create = has_permission('can_create')
    can_edit = has_permission('can_edit')
    can_delete = has_permission('can_delete')

    return render_template('returns.html', items=items, returns=returns, today=date.today(),
                            can_create=can_create, can_edit=can_edit, can_delete=can_delete)


@returns_bp.route('/returns/add-disposal', methods=['POST'])
def add_disposal():
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if not has_permission('can_create'):
        flash("You don't have permission to add disposal records.", "danger")
        return redirect(url_for('returns.index'))

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
            qty_no or 0,
            qty_no,
            qty_kg,
            'Disposed',
            session['full_name'],
            request.form.get('remarks', '')
        ))

        if qty_no:
            c.execute("UPDATE items SET stock = stock - %s WHERE id=%s", (qty_no, item_id))

        conn.commit()
        flash('Disposal record saved successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('returns.index'))


@returns_bp.route('/returns/edit/<int:id>', methods=['POST'])
def edit(id):
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if not has_permission('can_edit'):
        flash("You don't have permission to edit disposal records.", "danger")
        return redirect(url_for('returns.index'))

    conn = get_db(); c = conn.cursor()
    try:
        c.execute("SELECT * FROM return_register WHERE id=%s", (id,))
        old = fetchone(c)
        if not old:
            flash('Disposal record not found.', 'danger')
            conn.close()
            return redirect(url_for('returns.index'))

        qty_no_raw = request.form.get('qty_no', '').strip()
        qty_kg_raw = request.form.get('qty_kg', '').strip()
        new_qty_no = int(qty_no_raw) if qty_no_raw else None
        new_qty_kg = float(qty_kg_raw) if qty_kg_raw else None

        if not new_qty_no and not new_qty_kg:
            flash('Please enter a quantity in No. or Kg.', 'danger')
            conn.close()
            return redirect(url_for('returns.index'))

        # Adjust stock: give back old qty_no, then deduct new qty_no
        old_qty_no = old['qty_no'] or 0
        new_qty_no_val = new_qty_no or 0
        diff = new_qty_no_val - old_qty_no   # positive = extra stock needs deducting

        if diff > 0:
            c.execute("SELECT stock FROM items WHERE id=%s", (old['item_id'],))
            stock = fetchone(c)
            if not stock or stock['stock'] < diff:
                conn.close()
                flash('Insufficient stock for this update!', 'danger')
                return redirect(url_for('returns.index'))

        c.execute("""
            UPDATE return_register
            SET return_date=%s, qty_no=%s, qty_kg=%s, qty=%s, remarks=%s
            WHERE id=%s
        """, (
            request.form['return_date'],
            new_qty_no,
            new_qty_kg,
            new_qty_no_val,
            request.form.get('remarks', ''),
            id
        ))

        if diff != 0:
            c.execute("UPDATE items SET stock = stock - %s WHERE id=%s", (diff, old['item_id']))

        conn.commit()
        flash('Disposal record updated successfully.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('returns.index'))


@returns_bp.route('/returns/delete/<int:id>', methods=['POST'])
def delete(id):
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if not has_permission('can_delete'):
        flash("You don't have permission to delete disposal records.", "danger")
        return redirect(url_for('returns.index'))

    conn = get_db(); c = conn.cursor()
    try:
        c.execute("SELECT * FROM return_register WHERE id=%s", (id,))
        row = fetchone(c)
        if not row:
            flash('Disposal record not found.', 'danger')
            conn.close()
            return redirect(url_for('returns.index'))

        c.execute("DELETE FROM return_register WHERE id=%s", (id,))

        # Restore stock that was deducted at disposal time
        if row['qty_no']:
            c.execute("UPDATE items SET stock = stock + %s WHERE id=%s", (row['qty_no'], row['item_id']))

        conn.commit()
        flash('Disposal record deleted and stock restored.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('returns.index'))