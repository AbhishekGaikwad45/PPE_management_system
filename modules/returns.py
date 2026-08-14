from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db, fetchall, fetchone
from datetime import date
from modules.user_admin import has_permission, get_user_dept_variants
from modules.logs import log_action

returns_bp = Blueprint('returns', __name__)


@returns_bp.route('/returns')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()

    c.execute("SELECT id, item_name FROM items ORDER BY item_name")
    items = fetchall(c)

    role = session.get('role')
    is_admin = role in ['Admin', 'Super Admin']
    dept_variants = get_user_dept_variants()

    # Build departments_list for filter dropdown
    departments_list = []
    if is_admin:
        try:
            from modules.user_admin import get_departments
            departments_list = get_departments()
        except Exception:
            c.execute("SELECT DISTINCT department FROM departments ORDER BY department")
            departments_list = [r['department'] for r in fetchall(c) if r.get('department')]
    else:
        dept = session.get("department")
        if dept:
            departments_list.append(dept.strip())
        assigned = session.get("assigned_departments") or []
        for d in assigned:
            if d and not any(x.lower() == d.strip().lower() for x in departments_list):
                departments_list.append(d.strip())

    selected_dept = request.args.get('department', '').strip()
    search_query = request.args.get('search', '').strip()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()

    query = """
        SELECT rr.*, i.item_name, e.emp_code, e.name AS employee_name,
               COALESCE(NULLIF(TRIM(rr.department), ''), NULLIF(TRIM(e.department), ''), NULLIF(TRIM(ir.department), ''), NULLIF(TRIM(i.added_by_department), '')) AS department
        FROM return_register rr
        JOIN items i ON rr.item_id = i.id
        LEFT JOIN employees e ON rr.employee_id = e.id
        LEFT JOIN issue_register ir ON rr.issue_id = ir.id
        WHERE (rr.is_deleted IS FALSE OR rr.is_deleted IS NULL)
    """
    params = []

    if not is_admin:
        if dept_variants:
            placeholders = ', '.join(['%s'] * len(dept_variants))
            query += f" AND LOWER(TRIM(COALESCE(NULLIF(TRIM(rr.department), ''), NULLIF(TRIM(e.department), ''), NULLIF(TRIM(ir.department), ''), NULLIF(TRIM(i.added_by_department), '')))) IN ({placeholders})"
            params.extend(dept_variants)
        else:
            query += " AND 1=0"

    if selected_dept:
        query += " AND LOWER(TRIM(COALESCE(NULLIF(TRIM(rr.department), ''), NULLIF(TRIM(e.department), ''), NULLIF(TRIM(ir.department), ''), NULLIF(TRIM(i.added_by_department), '')))) = LOWER(TRIM(%s))"
        params.append(selected_dept)

    if from_date:
        query += " AND rr.return_date >= %s"
        params.append(from_date)

    if to_date:
        query += " AND rr.return_date <= %s"
        params.append(to_date)

    if search_query:
        query += " AND (i.item_name ILIKE %s OR e.name ILIKE %s OR e.emp_code ILIKE %s OR rr.remarks ILIKE %s)"
        s = f"%{search_query}%"
        params.extend([s, s, s, s])

    query += " ORDER BY rr.return_date DESC, rr.id DESC LIMIT 100"

    c.execute(query, tuple(params))
    returns = fetchall(c)
    conn.close()

    can_create = has_permission('can_create')
    can_edit = has_permission('can_edit')
    can_delete = has_permission('can_delete')

    return render_template('returns.html', items=items, returns=returns, today=date.today(),
                            can_create=can_create, can_edit=can_edit, can_delete=can_delete,
                            departments_list=departments_list, selected_dept=selected_dept,
                            search_query=search_query, from_date=from_date, to_date=to_date)


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

        dept_input = request.form.get('department', '').strip()
        dept_variants = get_user_dept_variants()
        if dept_variants:
            if not dept_input or dept_input.lower() not in dept_variants:
                flash("You can only add returns for your assigned department(s).", "danger")
                conn.close()
                return redirect(url_for('returns.index'))

        target_dept = dept_input or session.get('department')

        c.execute("""
            INSERT INTO return_register
                (return_date, employee_id, item_id, qty, qty_no, qty_kg, condition, received_by, remarks, department)
            VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            request.form['return_date'],
            item_id,
            qty_no or 0,
            qty_no,
            qty_kg,
            'Disposed',
            session.get('full_name', ''),
            request.form.get('remarks', ''),
            target_dept
        ))
        res = fetchone(c)
        ret_id = res['id'] if res else None

        if qty_no:
            c.execute("UPDATE items SET stock = stock - %s WHERE id=%s", (qty_no, item_id))

        conn.commit()
        log_action('create', 'returns', ret_id, f"Added return/disposal for item ID #{item_id}", department=target_dept)
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
        c.execute("""
            SELECT rr.*,
                   COALESCE(NULLIF(TRIM(rr.department), ''), NULLIF(TRIM(e.department), ''), NULLIF(TRIM(ir.department), ''), NULLIF(TRIM(i.added_by_department), '')) AS dept
            FROM return_register rr
            JOIN items i ON rr.item_id = i.id
            LEFT JOIN employees e ON rr.employee_id = e.id
            LEFT JOIN issue_register ir ON rr.issue_id = ir.id
            WHERE rr.id=%s AND (rr.is_deleted IS FALSE OR rr.is_deleted IS NULL)
        """, (id,))
        old = fetchone(c)
        if not old:
            flash('Disposal record not found.', 'danger')
            conn.close()
            return redirect(url_for('returns.index'))

        dept_variants = get_user_dept_variants()
        if dept_variants:
            rec_dept = (old.get('dept') or '').strip().lower()
            if rec_dept and rec_dept not in dept_variants:
                conn.close()
                flash('You do not have permission to edit records outside your assigned department.', 'danger')
                return redirect(url_for('returns.index'))

        dept_input = request.form.get('department', '').strip()
        if dept_input:
            if dept_variants and dept_input.lower() not in dept_variants:
                conn.close()
                flash("You can only assign returns to your assigned department(s).", "danger")
                return redirect(url_for('returns.index'))
            target_dept = dept_input
        else:
            target_dept = old.get('department')

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
            SET return_date=%s, qty_no=%s, qty_kg=%s, qty=%s, remarks=%s, department=%s
            WHERE id=%s
        """, (
            request.form['return_date'],
            new_qty_no,
            new_qty_kg,
            new_qty_no_val,
            request.form.get('remarks', ''),
            target_dept,
            id
        ))

        if diff != 0:
            c.execute("UPDATE items SET stock = stock - %s WHERE id=%s", (diff, old['item_id']))

        conn.commit()
        log_action('edit', 'returns', id, f"Updated disposal record #{id}", department=target_dept)
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
        c.execute("""
            SELECT rr.*,
                   COALESCE(NULLIF(TRIM(rr.department), ''), NULLIF(TRIM(e.department), ''), NULLIF(TRIM(ir.department), ''), NULLIF(TRIM(i.added_by_department), '')) AS dept
            FROM return_register rr
            JOIN items i ON rr.item_id = i.id
            LEFT JOIN employees e ON rr.employee_id = e.id
            LEFT JOIN issue_register ir ON rr.issue_id = ir.id
            WHERE rr.id=%s AND (rr.is_deleted IS FALSE OR rr.is_deleted IS NULL)
        """, (id,))
        row = fetchone(c)
        if not row:
            flash('Disposal record not found.', 'danger')
            conn.close()
            return redirect(url_for('returns.index'))

        dept_variants = get_user_dept_variants()
        if dept_variants:
            rec_dept = (row.get('dept') or '').strip().lower()
            if rec_dept and rec_dept not in dept_variants:
                conn.close()
                flash('You do not have permission to delete records outside your assigned department.', 'danger')
                return redirect(url_for('returns.index'))

        c.execute("UPDATE return_register SET is_deleted = TRUE WHERE id=%s", (id,))

        # Restore stock that was deducted at disposal time
        if row['qty_no']:
            c.execute("UPDATE items SET stock = stock + %s WHERE id=%s", (row['qty_no'], row['item_id']))

        conn.commit()
        log_action('delete', 'returns', id, f"Deleted disposal record #{id}", department=row.get('dept'))
        flash('Disposal record deleted and stock restored.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('returns.index'))