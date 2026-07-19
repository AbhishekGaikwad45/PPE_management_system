from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response
from database.db import get_db, fetchall, fetchone
from datetime import date
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from modules.user_admin import has_permission   # ← ADDED

contractor_issues_bp = Blueprint('contractor_issues', __name__)
_thin = Side(style='thin', color='C7CDD4')
_border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_ctr = Alignment(horizontal='center', vertical='center', wrap_text=True)
_left = Alignment(horizontal='left', vertical='center', wrap_text=True)


@contractor_issues_bp.route('/contractor-issues')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    conn = get_db(); c = conn.cursor()
    dept = session.get('department')

    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')

    role = session.get("role")
    is_admin = role in ["Admin", "Super Admin"]

    if is_admin:
        c.execute("""
            SELECT DISTINCT
                COALESCE(c.id, 0) AS id,
                e.contractor AS name,
                COALESCE(c.contact, '') AS contact,
                e.department
            FROM employees e
            LEFT JOIN contractors c
                ON UPPER(TRIM(c.name)) = UPPER(TRIM(e.contractor))
            WHERE
                e.status = 'Active'
                AND e.contractor IS NOT NULL
                AND TRIM(e.contractor) <> ''
            ORDER BY e.department, e.contractor
        """)
    else:
        c.execute("""
            SELECT DISTINCT
                COALESCE(c.id, 0) AS id,
                e.contractor AS name,
                COALESCE(c.contact, '') AS contact,
                e.department
            FROM employees e
            LEFT JOIN contractors c
                ON UPPER(TRIM(c.name)) = UPPER(TRIM(e.contractor))
            WHERE
                e.status = 'Active'
                AND e.department = %s
                AND e.contractor IS NOT NULL
                AND TRIM(e.contractor) <> ''
            ORDER BY e.contractor
        """, (dept,))

    contractors_raw = fetchall(c)

    contractors = [
        {
            "id": ct["id"],
            "name": ct["name"],
            "label": f"{ct['name']} ({ct['department']})"
        }
        for ct in contractors_raw
    ]


    query = """
    SELECT
        e.id,
        e.emp_code,
        e.name,
        COALESCE(c.id,0) AS contractor_id
    FROM employees e
    LEFT JOIN contractors c
        ON UPPER(TRIM(c.name)) = UPPER(TRIM(e.contractor))
    WHERE
        e.status='Active'
        AND e.contractor IS NOT NULL
        AND TRIM(e.contractor) <> ''
    """

    params = []

    if not is_admin:
        query += " AND LOWER(TRIM(e.department)) = LOWER(TRIM(%s))"
        params.append(dept)

    query += " ORDER BY e.name"

    c.execute(query, tuple(params))
    contractor_employees_raw = fetchall(c)

    contractor_employees = []

    for emp in contractor_employees_raw:
        contractor_employees.append({
            "id": emp["id"],
            "contractor_id": emp["contractor_id"],
            "label": f"{emp['emp_code']} - {emp['name']}"
        })

    c.execute("SELECT id, item_name, unit FROM items ORDER BY item_name")
    items_raw = fetchall(c)
    items = [{
        "id": i["id"],
        "unit": i["unit"],
        "label": i["item_name"],
    } for i in items_raw]

    query = """
        SELECT
            cir.id,
            cir.contractor_id,
            cir.employee_id,
            cir.item_id,
            cir.issue_date,
            cir.qty,
            cir.returnable,
            cir.return_due_date,
            cir.status,
            cir.issued_by,
            cir.remarks,

            ct.name AS contractor_name,
            ct.department,

            e.id AS emp_id,
            e.emp_code,
            e.name AS employee_name,

            i.item_name,
            i.unit

        FROM contractor_issue_register cir

        LEFT JOIN contractors ct
            ON ct.id = cir.contractor_id

        LEFT JOIN employees e
            ON e.id = cir.employee_id

        LEFT JOIN items i
            ON i.id = cir.item_id

        WHERE 1=1
        """
    params = []
    if not is_admin:
        query += " AND e.department=%s"
        params.append(dept)
    if from_date:
        query += " AND cir.issue_date >= %s"; params.append(from_date)
    if to_date:
        query += " AND cir.issue_date <= %s"; params.append(to_date)
    query += " ORDER BY cir.issue_date DESC"

    c.execute(query, tuple(params))
    issues = fetchall(c)
    conn.close()

    # ← FIXED — has_permission() takes ONE argument ('can_create' / 'can_edit'
    # / 'can_delete'), not (module, action). The old two-arg call silently
    # always evaluated wrong, which is why Add/Edit/Delete stayed visible
    # even for roles with no permission (same bug as modules/issues.py).
    can_create = has_permission('can_create')
    can_edit   = has_permission('can_edit')
    can_delete = has_permission('can_delete')

    return render_template('contractor_issues.html', contractors=contractors, items=items, issues=issues,
                            contractor_employees=contractor_employees,
                            today=date.today(), from_date=from_date, to_date=to_date,
                            can_create=can_create, can_edit=can_edit, can_delete=can_delete)


@contractor_issues_bp.route('/contractor-issues/add', methods=['POST'])
def add():
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if not has_permission('can_create'):                        # ← FIXED
        flash("You don't have permission to issue PPE to contractors.", "danger")
        return redirect(url_for("contractor_issues.index"))

    conn = get_db()
    c = conn.cursor()

    try:
        contractor_id = int(request.form['contractor_id'])
        employee_ids = [int(x) for x in request.form['employee_id'].split(',') if x.strip()]
        item_ids = [int(x) for x in request.form['item_id'].split(',') if x.strip()]

        qty = int(request.form['qty'])
        issue_date = request.form['issue_date']
        remarks = request.form.get('remarks', '')
        issued_by = session['full_name']

        returnable = 1 if request.form.get('returnable') else 0
        return_due = request.form.get('return_due_date') if returnable else None

        role = session.get("role")
        dept = session.get("department")
        print("=" * 50)
        print("Session Department :", repr(dept))
        print("Selected Contractor ID :", contractor_id)

        if role not in ["Admin", "Super Admin"]:
            c.execute("""
                SELECT DISTINCT department
                FROM employees
                WHERE contractor = (
                    SELECT name
                    FROM contractors
                    WHERE id=%s
                )
                LIMIT 1
            """, (contractor_id,))

            ct = fetchone(c)
            print("Contractor Row :", ct)
            print("=" * 50)
            session_dept = (dept or "").strip().lower()
            contractor_dept = (ct["department"] or "").strip().lower() if ct else ""
            if not ct or contractor_dept != session_dept:
                conn.close()
                flash("You can only issue PPE to contractors in your department.", "danger")
                return redirect(url_for("contractor_issues.index"))

        for emp_id in employee_ids:
            for item_id in item_ids:
                c.execute("""
                    INSERT INTO contractor_issue_register
                    (issue_date, contractor_id, employee_id, item_id, qty, issued_by,
                     returnable, return_due_date, status, remarks)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (issue_date, contractor_id, emp_id, item_id, qty, issued_by,
                      returnable, return_due, 'Issued', remarks))

        conn.commit()
        flash("PPE/Equipment issued to contractor employee(s) successfully.", "success")

    except Exception as e:
        import traceback
        traceback.print_exc()
        conn.rollback()
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("contractor_issues.index"))


@contractor_issues_bp.route('/contractor-issues/edit/<int:id>', methods=['POST'])
def edit(id):
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if not has_permission('can_edit'):                          # ← FIXED
        flash("You don't have permission to edit contractor issue records.", "danger")
        return redirect(url_for('contractor_issues.index'))

    conn = get_db(); c = conn.cursor()
    try:
        c.execute("SELECT * FROM contractor_issue_register WHERE id=%s", (id,))
        old = fetchone(c)
        if not old:
            flash('Issue record not found.', 'danger')
            conn.close()
            return redirect(url_for('contractor_issues.index'))

        contractor_id = request.form.get('contractor_id')
        employee_id = request.form.get('employee_id')
        item_id = request.form.get('item_id')
        issue_date = request.form.get('issue_date')
        qty_raw = request.form.get('qty')

        def is_blank(v):
            return not v or v.strip().lower() in ('none', 'null')

        if is_blank(employee_id) and old.get('employee_id'):
            employee_id = old['employee_id']

        missing = [name for name, val in [
            ('Contractor', contractor_id), ('Employee', employee_id),
            ('Item', item_id), ('Issue Date', issue_date), ('Quantity', qty_raw)
        ] if is_blank(val)]
        if missing:
            conn.close()
            flash(f"Update failed — missing required field(s): {', '.join(missing)}. "
                  f"Please reselect them and try again.", 'danger')
            return redirect(url_for('contractor_issues.index'))

        try:
            contractor_id = int(contractor_id)
            employee_id = int(employee_id)
            item_id = int(item_id)
            new_qty = int(qty_raw)
        except (TypeError, ValueError):
            conn.close()
            flash("Update failed — Contractor, Employee, Item, and Quantity must be valid numbers.", 'danger')
            return redirect(url_for('contractor_issues.index'))

        returnable = 1 if request.form.get('returnable') else 0
        return_due = request.form.get('return_due_date') if returnable else None

        c.execute("""
            UPDATE contractor_issue_register
            SET contractor_id=%s,
                employee_id=%s,
                item_id=%s,
                issue_date=%s,
                qty=%s,
                returnable=%s,
                return_due_date=%s,
                remarks=%s
            WHERE id=%s
        """, (
            contractor_id, employee_id, item_id, issue_date,
            new_qty, returnable, return_due,
            request.form.get("remarks", ""), id
        ))

        if c.rowcount == 0:
            conn.rollback()
            flash("Update failed — no matching record found to update.", 'danger')
            conn.close()
            return redirect(url_for('contractor_issues.index'))

        conn.commit()
        flash('Issue record updated successfully.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('contractor_issues.index'))


@contractor_issues_bp.route('/contractor-issues/delete/<int:id>', methods=['POST'])
def delete(id):
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if not has_permission('can_delete'):                        # ← FIXED
        flash("You don't have permission to delete contractor issue records.", "danger")
        return redirect(url_for('contractor_issues.index'))

    conn = get_db(); c = conn.cursor()
    try:
        c.execute("SELECT * FROM contractor_issue_register WHERE id=%s", (id,))
        row = fetchone(c)
        if not row:
            flash('Issue record not found.', 'danger')
            conn.close()
            return redirect(url_for('contractor_issues.index'))

        c.execute("DELETE FROM contractor_issue_register WHERE id=%s", (id,))
        conn.commit()
        flash('Issue record deleted.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {e}', 'danger')
    conn.close()
    return redirect(url_for('contractor_issues.index'))


@contractor_issues_bp.route('/contractor-issues/download')
def download():
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    conn = get_db(); c = conn.cursor()
    dept = session.get('department')
    role = session.get("role")
    is_admin = role in ["Admin", "Super Admin"]

    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')

    query = """
        SELECT cir.issue_date, ct.name as contractor_name, ct.department,
               i.item_name, cir.qty, i.unit, cir.status, cir.returnable,
               cir.return_due_date, cir.issued_by, cir.remarks
        FROM contractor_issue_register cir
        JOIN contractors ct ON cir.contractor_id=ct.id
        JOIN items i ON cir.item_id=i.id
        WHERE 1=1
    """
    params = []
    if not is_admin:
        query += " AND ct.department=%s"
        params.append(dept)
    if from_date:
        query += " AND cir.issue_date >= %s"
        params.append(from_date)
    if to_date:
        query += " AND cir.issue_date <= %s"
        params.append(to_date)
    query += " ORDER BY cir.issue_date DESC"

    c.execute(query, tuple(params))
    rows = fetchall(c)
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Contractor PPE Issue Report'

    headers = ['Date', 'Contractor', 'Department', 'Item', 'Qty', 'Unit',
               'Status', 'Returnable', 'Return Due Date', 'Issued By', 'Remarks']

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    title_cell = ws.cell(1, 1, f'Contractor PPE / Equipment Issue Report ({from_date or "All"} to {to_date or "All"})')
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
            r['issue_date'], r['contractor_name'], r['department'] or '',
            r['item_name'], r['qty'], r['unit'], r['status'],
            'Yes' if r['returnable'] else 'No',
            r['return_due_date'] or '', r['issued_by'], r['remarks'] or '',
        ]
        for col_idx, val in enumerate(values, start=1):
            cell = ws.cell(row_idx, col_idx, val)
            cell.border = _border
            cell.alignment = _left if col_idx in (2, 4, 11) else _ctr
        row_idx += 1

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.column_dimensions['B'].width = 22
    ws.column_dimensions['D'].width = 22
    ws.column_dimensions['K'].width = 26
    ws.freeze_panes = 'A3'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = f'Contractor_PPE_Issue_Report_{from_date or "all"}_to_{to_date or "all"}.xlsx'
    return Response(
        buf.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )