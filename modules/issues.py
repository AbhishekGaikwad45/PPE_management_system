from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response
from database.db import get_db, fetchall, fetchone
from datetime import date
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from modules.employees import _display_dept_name, COMBINE_GROUPS
from modules.user_admin import has_permission   # ← ADDED

issues_bp = Blueprint('issues', __name__)
_thin = Side(style='thin', color='C7CDD4')
_border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_ctr = Alignment(horizontal='center', vertical='center', wrap_text=True)
_left = Alignment(horizontal='left', vertical='center', wrap_text=True)


@issues_bp.route('/issues')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    # View access — everyone with login can see their own dept issues; no gate needed here
    conn = get_db(); c = conn.cursor()
    dept = session.get('department')
    role = session.get('role')
    is_admin = role in ['Admin', 'Super Admin']

    if not is_admin and dept:
        display_name = _display_dept_name(dept)
        dept_variants = [v.lower() for v in COMBINE_GROUPS.get(display_name, [dept])]
    else:
        dept_variants = []

    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')

    if dept_variants:
        c.execute("SELECT id, emp_code, name, department FROM employees WHERE status='Active' AND LOWER(department)=ANY(%s) ORDER BY name", (dept_variants,))
    else:
        c.execute("SELECT id, emp_code, name, department FROM employees WHERE status='Active' ORDER BY name")
    employees_raw = fetchall(c)
    employees = [{"id": e["id"], "label": f"{e['emp_code']} - {e['name']} ({e['department']})", "badge": f"{e['emp_code']} — {e['name']}"} for e in employees_raw]

    c.execute("SELECT id, item_name, stock, unit FROM items ORDER BY item_name")
    items_raw = fetchall(c)
    items = [{"id": i["id"], "stock": i["stock"], "unit": i["unit"], "label": f"{i['item_name']} [Stock: {i['stock']} {i['unit']}]", "badge": f"{i['item_name']} [{i['stock']} {i['unit']}]"} for i in items_raw]

    query = """
        SELECT ir.*, e.name as emp_name, e.emp_code, e.department, i.item_name, i.unit
        FROM issue_register ir
        JOIN employees e ON ir.employee_id=e.id
        JOIN items i ON ir.item_id=i.id
        WHERE 1=1
    """
    params = []
    if dept_variants:
        query += " AND LOWER(e.department)=ANY(%s)"
        params.append(dept_variants)
    if from_date:
        query += " AND ir.issue_date >= %s"
        params.append(from_date)
    if to_date:
        query += " AND ir.issue_date <= %s"
        params.append(to_date)
    query += " ORDER BY ir.issue_date DESC"

    c.execute(query, tuple(params))
    issues = fetchall(c)
    conn.close()

    # ← FIXED — has_permission() takes ONE argument ('can_create' / 'can_edit'
    # / 'can_delete'), not (module, action). The old two-arg call silently
    # always evaluated wrong, which is why Add/Edit/Delete stayed visible
    # even for roles with no permission.
    can_create = has_permission('can_create')
    can_edit   = has_permission('can_edit')
    can_delete = has_permission('can_delete')

    return render_template('issues.html', employees=employees, items=items, issues=issues,
                            today=date.today(), from_date=from_date, to_date=to_date,
                            can_create=can_create, can_edit=can_edit, can_delete=can_delete)


@issues_bp.route('/issues/add', methods=['POST'])
def add():
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    role = session.get("role")
    if not has_permission('can_create'):                       # ← FIXED
        flash("You don't have permission to issue PPE/Equipment.", "danger")
        return redirect(url_for("issues.index"))

    conn = get_db()
    c = conn.cursor()

    try:
        employee_ids = [int(x) for x in request.form['employee_id'].split(',') if x.strip()]
        item_ids = [int(x) for x in request.form['item_id'].split(',') if x.strip()]

        qty = int(request.form['qty'])
        issue_date = request.form['issue_date']
        remarks = request.form.get('remarks', '')
        issued_by = session['full_name']

        returnable = 1 if request.form.get('returnable') else 0
        return_due = request.form.get('return_due_date') if returnable else None

        dept = session.get("department")
        is_admin = role in ["Admin", "Super Admin"]

        if not is_admin:
            display_name = _display_dept_name(dept)
            allowed_variants = [v.lower() for v in COMBINE_GROUPS.get(display_name, [dept])]
            for emp_id in employee_ids:
                c.execute("SELECT department FROM employees WHERE id=%s", (emp_id,))
                emp = fetchone(c)
                if not emp or (emp["department"] or '').lower() not in allowed_variants:
                    conn.close()
                    flash("You can only issue PPE to employees in your department.", "danger")
                    return redirect(url_for("issues.index"))

        for item_id in item_ids:
            c.execute("SELECT stock FROM items WHERE id=%s", (item_id,))
            stock = fetchone(c)
            if not stock or stock["stock"] < qty:
                conn.close()
                flash("Insufficient stock!", "danger")
                return redirect(url_for("issues.index"))

        for emp_id in employee_ids:
            c.execute("SELECT department FROM employees WHERE id=%s", (emp_id,))
            emp_row = fetchone(c)
            emp_department = emp_row["department"] if emp_row else dept

            for item_id in item_ids:
                c.execute("""
                    INSERT INTO issue_register
                    (issue_date, employee_id, item_id, qty, issued_by,
                     returnable, return_due_date, status, remarks, department)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (issue_date, emp_id, item_id, qty, issued_by,
                      returnable, return_due, 'Issued', remarks, emp_department))

                c.execute("UPDATE items SET stock = stock - %s WHERE id=%s", (qty, item_id))

        conn.commit()
        flash("PPE/Equipment issued successfully.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("issues.index"))


@issues_bp.route('/issues/edit/<int:id>', methods=['POST'])
def edit(id):
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if not has_permission('can_edit'):                          # ← FIXED
        flash("You don't have permission to edit issue records.", "danger")
        return redirect(url_for('issues.index'))

    conn = get_db(); c = conn.cursor()
    try:
        c.execute("SELECT * FROM issue_register WHERE id=%s", (id,))
        old = fetchone(c)
        if not old:
            flash('Issue record not found.', 'danger')
            conn.close()
            return redirect(url_for('issues.index'))

        new_qty = int(request.form['qty'])
        qty_diff = new_qty - old['qty']

        if qty_diff > 0:
            c.execute("SELECT stock FROM items WHERE id=%s", (old['item_id'],))
            stock = fetchone(c)
            if not stock or stock['stock'] < qty_diff:
                conn.close()
                flash('Insufficient stock for this update!', 'danger')
                return redirect(url_for('issues.index'))

        returnable = 1 if request.form.get('returnable') else 0
        return_due = request.form.get('return_due_date') if returnable else None

        c.execute("""
            UPDATE issue_register
            SET issue_date=%s, qty=%s, returnable=%s, return_due_date=%s, remarks=%s
            WHERE id=%s
        """, (request.form['issue_date'], new_qty, returnable, return_due,
              request.form.get('remarks', ''), id))

        c.execute("UPDATE items SET stock=stock-%s WHERE id=%s", (qty_diff, old['item_id']))

        conn.commit()
        flash('Issue record updated successfully.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('issues.index'))


@issues_bp.route('/issues/delete/<int:id>', methods=['POST'])
def delete(id):
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if not has_permission('can_delete'):                        # ← FIXED
        flash("You don't have permission to delete issue records.", "danger")
        return redirect(url_for('issues.index'))

    conn = get_db(); c = conn.cursor()
    try:
        c.execute("SELECT * FROM issue_register WHERE id=%s", (id,))
        row = fetchone(c)
        if not row:
            flash('Issue record not found.', 'danger')
            conn.close()
            return redirect(url_for('issues.index'))

        c.execute("DELETE FROM issue_register WHERE id=%s", (id,))
        c.execute("UPDATE items SET stock=stock+%s WHERE id=%s", (row['qty'], row['item_id']))
        conn.commit()
        flash('Issue record deleted and stock restored.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('issues.index'))


@issues_bp.route('/issues/download')
def download():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    # Download = read-only report; login gate hi purese ahe, extra permission nako vatly tar hi line kadhu shakta

    conn = get_db(); c = conn.cursor()
    dept = session.get('department')
    role = session.get('role')
    is_admin = role in ['Admin', 'Super Admin']

    if not is_admin and dept:
        display_name = _display_dept_name(dept)
        dept_variants = [v.lower() for v in COMBINE_GROUPS.get(display_name, [dept])]
    else:
        dept_variants = []

    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')

    query = """
        SELECT ir.issue_date, e.emp_code, e.name as emp_name, e.department,
               i.item_name, ir.qty, i.unit, ir.status, ir.returnable,
               ir.return_due_date, ir.issued_by, ir.remarks
        FROM issue_register ir
        JOIN employees e ON ir.employee_id=e.id
        JOIN items i ON ir.item_id=i.id
        WHERE 1=1
    """
    params = []
    if dept_variants:
        query += " AND LOWER(e.department)=ANY(%s)"
        params.append(dept_variants)
    if from_date:
        query += " AND ir.issue_date >= %s"
        params.append(from_date)
    if to_date:
        query += " AND ir.issue_date <= %s"
        params.append(to_date)
    query += " ORDER BY ir.issue_date DESC"

    c.execute(query, tuple(params))
    rows = fetchall(c)
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = 'PPE Issue Report'

    headers = ['Date', 'Emp Code', 'Name', 'Department', 'Item', 'Qty', 'Unit',
               'Status', 'Returnable', 'Return Due Date', 'Issued By', 'Remarks']

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    title_cell = ws.cell(1, 1, f'PPE / Equipment Issue Report ({from_date or "All"} to {to_date or "All"})')
    title_cell.font = Font(bold=True, size=13, color='2C3E50')
    title_cell.alignment = _ctr
    title_cell.fill = PatternFill('solid', fgColor='F6F8FB')
    for col in range(2, len(headers) + 1):
        ws.cell(1, col).fill = PatternFill('solid', fgColor='F6F8FB')

    for idx, h in enumerate(headers, start=1):
        cell = ws.cell(2, idx, h)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='2C3E50')
        cell.alignment = _ctr
        cell.border = _border

    row_idx = 3
    for r in rows:
        values = [
            r['issue_date'], r['emp_code'], r['emp_name'], r['department'],
            r['item_name'], r['qty'], r['unit'], r['status'],
            'Yes' if r['returnable'] else 'No',
            r['return_due_date'] or '', r['issued_by'], r['remarks'] or '',
        ]
        for col_idx, val in enumerate(values, start=1):
            cell = ws.cell(row_idx, col_idx, val)
            cell.border = _border
            cell.alignment = _left if col_idx in (3, 5, 12) else _ctr
        row_idx += 1

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.column_dimensions['C'].width = 22
    ws.column_dimensions['E'].width = 22
    ws.column_dimensions['L'].width = 26
    ws.freeze_panes = 'A3'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = f'PPE_Issue_Report_{from_date or "all"}_to_{to_date or "all"}.xlsx'
    return Response(
        buf.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )