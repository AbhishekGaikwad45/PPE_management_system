from flask import Blueprint, render_template, request, redirect, url_for, session
from database.db import get_db, fetchall
from modules.employees import _display_dept_name, COMBINE_GROUPS
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

    # Normalize departments using the app's combine-group logic
    unique_display_depts = set()
    for raw_dept in all_departments:
        display_dept = _display_dept_name(raw_dept)
        unique_display_depts.add(display_dept)

    # ========== STEP 2: Determine access permissions ==========
    if not is_admin and dept:
        display_name = _display_dept_name(dept)
        allowed_variants = {v.lower() for v in COMBINE_GROUPS.get(display_name, [dept])}
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
    # { "Marine / Operations": { "Dust Mask": {"qty": 12, "unit": "Nos"}, ... }, ... }
    dept_data = {}
    for row in rows:
        raw_dept = row['raw_department']

        # Skip rows belonging to a department this user isn't allowed to see
        if allowed_variants is not None and (raw_dept or '').lower() not in allowed_variants:
            continue

        display_dept = _display_dept_name(raw_dept)
        item_name = row['item_name']
        unit = row['unit']
        qty = row['qty'] or 0

        dept_data.setdefault(display_dept, {})
        dept_data[display_dept].setdefault(item_name, {'qty': 0, 'unit': unit})
        dept_data[display_dept][item_name]['qty'] += qty

    # ========== STEP 4: Get current stock per item per department ==========
    # This section calculates available stock for each department.
    # If you have a dedicated department_stock table, use that instead.
    # For now, we'll show all items with their current overall stock,
    # and calculate what's left for each department.

    c.execute("SELECT id, item_name, stock, unit FROM items ORDER BY item_name")
    all_items = fetchall(c)
    
    # Create a mapping of item_id -> item_name, stock, unit
    item_info = {row['id']: row for row in all_items}

    # Get issued quantities per item per department (in detail)
    c.execute("""
        SELECT e.department AS raw_department, i.id AS item_id, i.item_name, 
               i.unit, SUM(ir.qty) AS total_issued
        FROM issue_register ir
        JOIN employees e ON ir.employee_id = e.id
        JOIN items i ON ir.item_id = i.id
        GROUP BY e.department, i.id, i.item_name, i.unit
    """)
    dept_issued_detail = fetchall(c)

    # dept_current_stock structure:
    # { "Marine / Operations": { "Dust Mask": {"current": 8, "issued": 2, "unit": "Nos"}, ... }, ... }
    dept_current_stock = defaultdict(lambda: defaultdict(dict))
    
    for row in dept_issued_detail:
        raw_dept = row['raw_department']
        
        # Skip rows belonging to a department this user isn't allowed to see
        if allowed_variants is not None and (raw_dept or '').lower() not in allowed_variants:
            continue
        
        display_dept = _display_dept_name(raw_dept)
        item_id = row['item_id']
        item_name = row['item_name']
        unit = row['unit']
        total_issued = row['total_issued'] or 0
        
        # Get overall current stock from items table
        overall_current = item_info.get(item_id, {}).get('stock', 0)
        
        dept_current_stock[display_dept][item_name] = {
            'current': overall_current,
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