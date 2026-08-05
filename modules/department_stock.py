from flask import Blueprint, render_template, request, redirect, url_for, session
from database.db import get_db, fetchall
from collections import defaultdict

department_stock_bp = Blueprint('department_stock', __name__)


@department_stock_bp.route('/department-stock')
def index():
    # Login required, same pattern as every other module in this app
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    conn = get_db()
    c = conn.cursor()
    role = session.get('role')
    dept = session.get('department')
    is_admin = role in ['Admin', 'Super Admin']

    # Optional item-name search box (?search=...)
    search = request.args.get('search', '').strip()

    # ========== STEP 1: Get all unique departments from issue_register ==========
    c.execute("""
        SELECT DISTINCT e.department AS raw_department
        FROM issue_register ir
        JOIN employees e ON ir.employee_id = e.id
        WHERE e.department IS NOT NULL AND e.department != ''
        ORDER BY e.department
    """)
    all_departments = [row['raw_department'] for row in fetchall(c)]

    # ========== STEP 2: Determine access permissions ==========
    if not is_admin:
        allowed_variants = set()
        if dept:
            allowed_variants.add(dept.lower())
        assigned = session.get("assigned_departments") or []
        for d in assigned:
            if d:
                allowed_variants.add(d.lower())
    else:
        allowed_variants = None  # None = no restriction (Admin sees everything)

    # ========== STEP 3: Get issued quantities per department per item ==========
    c.execute("""
        SELECT e.department AS raw_department, i.item_name, i.unit, ir.qty
        FROM issue_register ir
        JOIN employees e ON ir.employee_id = e.id
        JOIN items i ON ir.item_id = i.id
    """)
    rows = fetchall(c)

    # dept_data shape:
    # { "Marine": { "Dust Mask": {"qty": 12, "unit": "Nos"}, ... }, ... }
    dept_data = {}
    for row in rows:
        raw_dept = row['raw_department'] or 'Unassigned'

        # Skip rows belonging to a department this user isn't allowed to see
        if allowed_variants is not None and raw_dept.lower() not in allowed_variants:
            continue

        display_dept = raw_dept
        item_name = row['item_name']
        unit = row['unit']
        qty = row['qty'] or 0

        dept_data.setdefault(display_dept, {})
        dept_data[display_dept].setdefault(item_name, {'qty': 0, 'unit': unit})
        dept_data[display_dept][item_name]['qty'] += qty

# ========== STEP 4: Get REAL current stock per item per department ==========
    # A department's own stock balance is receipts - issues + returns for
    # THAT department specifically — computed the exact same way
    # find_issue_department() in issues.py decides whether a department has
    # enough stock to issue from. It is NOT items.stock (that's the
    # company-wide total across every department combined, and must never
    # be shown here or it leaks other departments' stock into this view).
    #
    # Note: we group by issue_register.department / stock_receipts.department
    # directly — NOT by the employee's own department — because an issue
    # may have actually been drawn from a sibling department's stock.
    # issue_register.department always records which department's ledger was actually decremented.

    c.execute("SELECT id, item_name, unit FROM items ORDER BY item_name")
    all_items = fetchall(c)
    item_info = {row['id']: row for row in all_items}

    c.execute("""
        SELECT department AS raw_department, item_id, COALESCE(SUM(qty),0) AS total
        FROM stock_receipts
        GROUP BY department, item_id
    """)
    receipts_rows = fetchall(c)

    c.execute("""
        SELECT department AS raw_department, item_id, COALESCE(SUM(qty),0) AS total
        FROM issue_register
        GROUP BY department, item_id
    """)
    issued_rows = fetchall(c)

    c.execute("""
        SELECT i.department AS raw_department, r.item_id, COALESCE(SUM(r.qty_no),0) AS total
        FROM return_register r
        JOIN issue_register i ON i.id = r.issue_id
        GROUP BY i.department, r.item_id
    """)
    returned_rows = fetchall(c)

    # balances[(raw_department, item_id)] = running total
    balances = defaultdict(int)
    for row in receipts_rows:
        balances[(row['raw_department'], row['item_id'])] += row['total']
    for row in issued_rows:
        balances[(row['raw_department'], row['item_id'])] -= row['total']
    for row in returned_rows:
        balances[(row['raw_department'], row['item_id'])] += row['total']

    # Total issued (for the "Issued Qty" column) keyed the same way
    issued_totals = {
        (row['raw_department'], row['item_id']): row['total'] for row in issued_rows
    }

    dept_current_stock = defaultdict(dict)
    for (raw_dept, item_id), balance in balances.items():
        if not raw_dept:
            continue

        # Skip rows belonging to a department this user isn't allowed to see
        if allowed_variants is not None and raw_dept.lower() not in allowed_variants:
            continue

        item = item_info.get(item_id)
        if not item:
            continue

        display_dept = raw_dept
        item_name = item['item_name']
        unit = item['unit']
        total_issued = issued_totals.get((raw_dept, item_id), 0)

        existing = dept_current_stock[display_dept].get(item_name)
        if existing:
            # Combined-group departments (e.g. Marine + Operations) merge into one row
            existing['current'] += balance
            existing['issued'] += total_issued
        else:
            dept_current_stock[display_dept][item_name] = {
                'current': balance,
                'issued': total_issued,
                'unit': unit
            }

    # ========== STEP 5: Apply search filter if provided ==========
    if search:
        filtered = {}
        for d, items in dept_data.items():
            matched_items = {
                name: info for name, info in items.items()
                if search.lower() in name.lower()
            }
            if matched_items:
                filtered[d] = matched_items
        dept_data = filtered

        # Also filter department current stock
        filtered_current = {}
        for d, items in dept_current_stock.items():
            matched_items = {
                name: info for name, info in items.items()
                if search.lower() in name.lower()
            }
            if matched_items:
                filtered_current[d] = matched_items
        dept_current_stock = filtered_current

    # ========== STEP 6: Sort departments alphabetically, and items within each ==========
    sorted_dept_data = {
        d: dict(sorted(dept_data[d].items()))
        for d in sorted(dept_data.keys())
    }

    sorted_dept_current_stock = {
        d: dict(sorted(dept_current_stock[d].items()))
        for d in sorted(dept_current_stock.keys())
    }

    # ========== STEP 7: Get company-wide current stock ==========
    c.execute("SELECT item_name, stock, unit FROM items ORDER BY item_name")
    current_stock = fetchall(c)

    conn.close()

    return render_template(
        'department_stock.html',
        dept_data=sorted_dept_data,
        dept_current_stock=sorted_dept_current_stock,
        current_stock=current_stock,
        search=search,
        is_admin=is_admin
    )