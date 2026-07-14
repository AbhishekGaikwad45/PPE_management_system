from flask import Blueprint, render_template, session, redirect, url_for
from database.db import get_db, fetchall
from datetime import date
from modules.employees import _display_dept_name, COMBINE_GROUPS   # ← ADDED

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/dashboard')
def index():
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    conn = get_db()
    c = conn.cursor()

    today = date.today().strftime('%Y-%m-%d')
    month = date.today().strftime('%Y-%m')

    role = session.get("role")
    dept = session.get("department")

    is_admin = role in ["Admin", "Super Admin"]

    # Resolve every raw variant of the user's department (handles combined
    # groups like IT/Information Technology, Civil/Projects, Admin/HR/Administration)
    if not is_admin:
        display_name = _display_dept_name(dept)
        dept_variants = [v.lower() for v in COMBINE_GROUPS.get(display_name, [dept])]
    else:
        dept_variants = []

    # ==========================
    # Employees
    # ==========================
    if is_admin:
        c.execute("SELECT COUNT(*) FROM employees WHERE status='Active'")
    else:
        c.execute(
            "SELECT COUNT(*) FROM employees WHERE status='Active' AND LOWER(department) = ANY(%s)",
            (dept_variants,)
        )
    total_employees = c.fetchone()[0]

    # ==========================
    # Total Stock (role-based)
    # ==========================
    if is_admin:
        c.execute("SELECT COALESCE(SUM(stock),0) FROM items")
        total_stock = c.fetchone()[0]
    else:
        c.execute("""
            SELECT COALESCE(SUM(
                CASE WHEN ir.status='Issued' THEN ir.qty ELSE 0 END
                - CASE WHEN ir.status='Returned' THEN ir.qty ELSE 0 END
            ),0)
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE LOWER(e.department) = ANY(%s)
        """, (dept_variants,))
        total_stock = c.fetchone()[0]

    # ==========================
    # Issued Today
    # ==========================
    if is_admin:
        c.execute(
            "SELECT COALESCE(SUM(qty),0) FROM issue_register WHERE issue_date=%s",
            (today,)
        )
    else:
        c.execute("""
            SELECT COALESCE(SUM(ir.qty),0)
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE ir.issue_date=%s
            AND LOWER(e.department) = ANY(%s)
        """, (today, dept_variants))

    issued_today = c.fetchone()[0]

    # ==========================
    # Issued Today by Department (admin hover on "Issued Today" KPI)
    # ==========================
    if is_admin:
        c.execute("""
            SELECT e.department, COALESCE(SUM(ir.qty),0) AS total
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE ir.issue_date=%s
            AND e.department IS NOT NULL AND TRIM(e.department) <> ''
            GROUP BY e.department
            ORDER BY total DESC
        """, (today,))
        issued_today_by_dept = fetchall(c)
    else:
        issued_today_by_dept = []

    # ==========================
    # Issued This Month
    # ==========================
    if is_admin:
        c.execute(
            "SELECT COALESCE(SUM(qty),0) FROM issue_register WHERE issue_date LIKE %s",
            (month + '%',)
        )
    else:
        c.execute("""
            SELECT COALESCE(SUM(ir.qty),0)
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE ir.issue_date LIKE %s
            AND LOWER(e.department) = ANY(%s)
        """, (month + '%', dept_variants))

    issued_month = c.fetchone()[0]

    # ==========================
    # Issued This Month by Department (admin hover on "This Month" KPI)
    # ==========================
    if is_admin:
        c.execute("""
            SELECT e.department, COALESCE(SUM(ir.qty),0) AS total
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE ir.issue_date LIKE %s
            AND e.department IS NOT NULL AND TRIM(e.department) <> ''
            GROUP BY e.department
            ORDER BY total DESC
        """, (month + '%',))
        issued_month_by_dept = fetchall(c)
    else:
        issued_month_by_dept = []

    # ==========================
    # Low Stock
    # ==========================
    if is_admin:
        c.execute("""
            SELECT i.item_name,
                   i.stock,
                   i.min_stock,
                   COALESCE(
                       string_agg(DISTINCT e.department, ', ') FILTER (WHERE e.department IS NOT NULL),
                       'N/A'
                   ) AS departments
            FROM items i
            LEFT JOIN issue_register ir ON ir.item_id = i.id
            LEFT JOIN employees e ON ir.employee_id = e.id
            WHERE i.stock <= i.min_stock
            AND i.min_stock > 0
            GROUP BY i.item_name, i.stock, i.min_stock
            ORDER BY i.stock ASC
        """)
    else:
        c.execute("""
            SELECT DISTINCT
                i.item_name,
                i.stock,
                i.min_stock
            FROM items i
            JOIN issue_register ir
                ON i.id = ir.item_id
            JOIN employees e
                ON ir.employee_id = e.id
            WHERE LOWER(e.department) = ANY(%s)
            AND i.stock <= i.min_stock
            AND i.min_stock > 0
            ORDER BY i.stock ASC
        """, (dept_variants,))

    low_stock = fetchall(c)

    # ==========================
    # Low Stock by Department (admin hover on "Low Stock" KPI)
    # ==========================
    if is_admin:
        c.execute("""
            SELECT e.department, COUNT(DISTINCT i.id) AS total
            FROM items i
            JOIN issue_register ir ON ir.item_id = i.id
            JOIN employees e ON ir.employee_id = e.id
            WHERE i.stock <= i.min_stock
            AND i.min_stock > 0
            AND e.department IS NOT NULL AND TRIM(e.department) <> ''
            GROUP BY e.department
            ORDER BY total DESC
        """)
        low_stock_by_dept = fetchall(c)
    else:
        low_stock_by_dept = []

    # ==========================
    # Department-wise Stock (Issued - Returned)
    # ==========================
    if is_admin:
        c.execute("""
            SELECT e.department,
                   i.item_name,
                   SUM(CASE WHEN ir.status='Issued' THEN ir.qty ELSE 0 END)
                   - SUM(CASE WHEN ir.status='Returned' THEN ir.qty ELSE 0 END) AS net_stock
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            JOIN items i ON ir.item_id=i.id
            WHERE e.department IS NOT NULL
            GROUP BY e.department, i.item_name
            HAVING SUM(CASE WHEN ir.status='Issued' THEN ir.qty ELSE 0 END)
                   - SUM(CASE WHEN ir.status='Returned' THEN ir.qty ELSE 0 END) > 0
            ORDER BY e.department, i.item_name
        """)
    else:
        c.execute("""
            SELECT e.department,
                   i.item_name,
                   SUM(CASE WHEN ir.status='Issued' THEN ir.qty ELSE 0 END)
                   - SUM(CASE WHEN ir.status='Returned' THEN ir.qty ELSE 0 END) AS net_stock
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            JOIN items i ON ir.item_id=i.id
            WHERE LOWER(e.department) = ANY(%s)
            GROUP BY e.department, i.item_name
            HAVING SUM(CASE WHEN ir.status='Issued' THEN ir.qty ELSE 0 END)
                   - SUM(CASE WHEN ir.status='Returned' THEN ir.qty ELSE 0 END) > 0
            ORDER BY i.item_name
        """, (dept_variants,))

    dept_stock = fetchall(c)

    # ==========================
    # Employees by Department (admin hover tooltip on "Employees" KPI)
    # ==========================
    if is_admin:
        # Fetch every active employee department (same approach as employees.py)
        c.execute("""
            SELECT department
            FROM employees
            WHERE status='Active'
            AND department IS NOT NULL
            AND TRIM(department) <> ''
        """)

        raw_rows = fetchall(c)

        dept_counts = {}

        for row in raw_rows:
            raw = row["department"]
            raw_clean = raw.strip() if raw else ""

            if not raw_clean:
                continue

            # Hide Shipping & Logistics completely
            if raw_clean.strip().lower() in (
                "shipping & logistics",
                "shipping and logistics",
                "shipping",
                "logistics"
            ):
                continue

            # SAME LOGIC USED IN employees.py
            display = _display_dept_name(raw_clean)

            dept_counts[display] = dept_counts.get(display, 0) + 1

        emp_by_dept = [
            {
                "department": department,
                "total": total
            }
            for department, total in sorted(
                dept_counts.items(),
                key=lambda x: (-x[1], x[0])
            )
        ]

    else:
        emp_by_dept = []

    # ==========================
    # Stock by Department (admin hover tooltip on "Total Stock" KPI)
    # ==========================
    if is_admin:
        c.execute("""
            SELECT e.department,
                   SUM(CASE WHEN ir.status='Issued' THEN ir.qty ELSE 0 END)
                   - SUM(CASE WHEN ir.status='Returned' THEN ir.qty ELSE 0 END) AS net_stock
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE e.department IS NOT NULL AND TRIM(e.department) <> ''
            GROUP BY e.department
            ORDER BY net_stock DESC
        """)
        stock_by_dept = fetchall(c)
    else:
        stock_by_dept = []

    # ==========================
    # Items
    # ==========================
    if is_admin:
        c.execute("SELECT COUNT(*) FROM items")
        total_items = c.fetchone()[0]
    else:
        c.execute("""
            SELECT COUNT(DISTINCT ir.item_id)
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE LOWER(e.department) = ANY(%s)
        """, (dept_variants,))
        total_items = c.fetchone()[0]

    # ==========================
    # Top Items
    # ==========================
    if is_admin:
        c.execute("""
            SELECT i.item_name,
                SUM(ir.qty) AS total_issued
            FROM issue_register ir
            JOIN items i ON ir.item_id=i.id
            GROUP BY i.item_name
            ORDER BY total_issued DESC
            LIMIT 10
        """)
    else:
        c.execute("""
            SELECT i.item_name,
                SUM(ir.qty) AS total_issued
            FROM issue_register ir
            JOIN items i ON ir.item_id=i.id
            JOIN employees e ON ir.employee_id=e.id
            WHERE LOWER(e.department) = ANY(%s)
            GROUP BY i.item_name
            ORDER BY total_issued DESC
            LIMIT 10
        """, (dept_variants,))

    top_items = fetchall(c)

    # ==========================
    # Department Consumption
    # ==========================
    if is_admin:
        c.execute("""
            SELECT e.department,
                   SUM(ir.qty) AS total
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE e.department IS NOT NULL
            GROUP BY e.department
            ORDER BY total DESC
        """)
    else:
        c.execute("""
            SELECT e.department,
                   SUM(ir.qty) AS total
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE LOWER(e.department) = ANY(%s)
            GROUP BY e.department
        """, (dept_variants,))

    dept_consumption = fetchall(c)

    # ==========================
    # Monthly Trend
    # ==========================
    if is_admin:
        c.execute("""
            SELECT TO_CHAR(TO_DATE(issue_date,'YYYY-MM-DD'),'YYYY-MM') AS month,
                   SUM(qty) AS total
            FROM issue_register
            GROUP BY month
            ORDER BY month DESC
            LIMIT 12
        """)
    else:
        c.execute("""
            SELECT TO_CHAR(TO_DATE(ir.issue_date,'YYYY-MM-DD'),'YYYY-MM') AS month,
                   SUM(ir.qty) AS total
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            WHERE LOWER(e.department) = ANY(%s)
            GROUP BY month
            ORDER BY month DESC
            LIMIT 12
        """, (dept_variants,))

    monthly_trend = fetchall(c)

    # ==========================
    # Overdue Returns
    # ==========================
    if is_admin:
        c.execute("""
            SELECT ir.id,
                   e.name,
                   e.emp_code,
                   i.item_name,
                   ir.qty,
                   ir.return_due_date
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            JOIN items i ON ir.item_id=i.id
            WHERE ir.returnable=1
            AND ir.status='Issued'
            AND ir.return_due_date < %s
            ORDER BY ir.return_due_date
        """, (today,))
    else:
        c.execute("""
            SELECT ir.id,
                   e.name,
                   e.emp_code,
                   i.item_name,
                   ir.qty,
                   ir.return_due_date
            FROM issue_register ir
            JOIN employees e ON ir.employee_id=e.id
            JOIN items i ON ir.item_id=i.id
            WHERE ir.returnable=1
            AND ir.status='Issued'
            AND ir.return_due_date < %s
            AND LOWER(e.department) = ANY(%s)
            ORDER BY ir.return_due_date
        """, (today, dept_variants))

    overdue_returns = fetchall(c)

    # ==========================
    # Expiry Alerts
    # ==========================
    c.execute("""
        SELECT i.item_name,
               e.expiry_date,
               e.qty,
               e.batch_no
        FROM expiry_tracking e
        JOIN items i ON e.item_id=i.id
        WHERE e.status='Active'
        AND TO_DATE(e.expiry_date,'YYYY-MM-DD')
        <= CURRENT_DATE + INTERVAL '30 days'
        ORDER BY e.expiry_date
    """)
    expiry_alerts = fetchall(c)

    # ==========================
    # Calibration Alerts
    # ==========================
    c.execute("""
        SELECT i.item_name,
               c.serial_no,
               c.next_calibration_date
        FROM calibration_tracking c
        JOIN items i ON c.item_id=i.id
        WHERE c.status='Valid'
        AND TO_DATE(c.next_calibration_date,'YYYY-MM-DD')
        <= CURRENT_DATE + INTERVAL '30 days'
        ORDER BY c.next_calibration_date
    """)
    calibration_alerts = fetchall(c)

    conn.close()

    return render_template(
        "dashboard.html",
        is_admin=is_admin,
        total_employees=total_employees,
        total_items=total_items,
        total_stock=total_stock,
        issued_today=issued_today,
        issued_today_by_dept=issued_today_by_dept,
        issued_month=issued_month,
        issued_month_by_dept=issued_month_by_dept,
        low_stock=low_stock,
        low_stock_by_dept=low_stock_by_dept,
        dept_stock=dept_stock,
        emp_by_dept=emp_by_dept,
        stock_by_dept=stock_by_dept,
        top_items=top_items,
        dept_consumption=dept_consumption,
        monthly_trend=monthly_trend,
        overdue_returns=overdue_returns,
        expiry_alerts=expiry_alerts,
        calibration_alerts=calibration_alerts
    )