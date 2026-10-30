import pytest


class TestInventoryAndIssueIntegration:
    """Integration tests for Items, Stock Receipts, Issues, and Stock Balance mutations."""

    def test_stock_receipt_increments_item_stock(self, client, db_conn):
        """Receiving stock increments items.stock and records in stock_receipts."""
        c = db_conn.cursor()

        # Insert a clean test item
        c.execute("""
            INSERT INTO items (item_name, category, unit, stock, min_stock)
            VALUES ('Integration Test Helmet', 'Head Protection', 'Nos', 50, 10)
            RETURNING id;
        """)
        item_id = c.fetchone()[0]
        db_conn.commit()

        # Authenticate as Store Keeper with can_create permission
        with client.session_transaction() as sess:
            sess['user'] = 'test_store_keeper'
            sess['role'] = 'Store Keeper'
            sess['full_name'] = 'Store Keeper Test'
            sess['department'] = 'Stores'

        # Post stock receipt: +30
        response = client.post('/stock/receive', data={
            'item_id': item_id,
            'qty': 30,
            'receipt_date': '2026-10-30',
            'grn_no': 'GRN-TEST-1001',
            'department': 'Stores',
            'remarks': 'Integration test stock addition'
        }, follow_redirects=True)

        assert response.status_code == 200

        # Verify database record in items
        c.execute("SELECT stock FROM items WHERE id=%s", (item_id,))
        updated_stock = c.fetchone()[0]
        assert updated_stock == 80  # 50 initial + 30 received

        # Verify record in stock_receipts
        c.execute("SELECT qty, grn_no FROM stock_receipts WHERE item_id=%s AND grn_no=%s", (item_id, 'GRN-TEST-1001'))
        receipt_row = c.fetchone()
        assert receipt_row is not None
        assert receipt_row[0] == 30

    def test_issue_ppe_deducts_stock_and_creates_register_entry(self, client, db_conn):
        """Issuing PPE to an employee reduces items.stock and creates an issue_register row."""
        c = db_conn.cursor()

        # 1. Create Test Department, Item and Employee
        c.execute("""
            INSERT INTO items (item_name, category, unit, stock, min_stock)
            VALUES ('Integration Test Gloves', 'Hand Protection', 'Pairs', 25, 5)
            RETURNING id;
        """)
        item_id = c.fetchone()[0]

        c.execute("""
            INSERT INTO employees (emp_code, name, department, status)
            VALUES ('EMP-TEST-001', 'Integration Employee', 'Safety', 'Active')
            RETURNING id;
        """)
        emp_id = c.fetchone()[0]

        # Allocate department stock receipt so find_issue_department succeeds
        c.execute("""
            INSERT INTO stock_receipts (receipt_date, item_id, qty, grn_no, department, received_by)
            VALUES ('2026-10-30', %s, 25, 'GRN-TEST-INIT', 'Safety', 'Tester');
        """, (item_id,))
        db_conn.commit()

        # Authenticate as Admin
        with client.session_transaction() as sess:
            sess['user'] = 'test_admin'
            sess['role'] = 'Admin'
            sess['full_name'] = 'Admin Test'
            sess['department'] = 'Safety'

        # Issue 5 items
        response = client.post('/issues/add', data={
            'employee_id': str(emp_id),
            'item_id': str(item_id),
            'qty': 5,
            'issue_date': '2026-10-30',
            'remarks': 'Issued for testing'
        }, follow_redirects=True)

        assert response.status_code == 200

        # Verify items.stock decreased from 25 to 20
        c.execute("SELECT stock FROM items WHERE id=%s", (item_id,))
        new_stock = c.fetchone()[0]
        assert new_stock == 20

        # Verify entry created in issue_register
        c.execute("""
            SELECT qty, status, department FROM issue_register
            WHERE employee_id=%s AND item_id=%s
        """, (emp_id, item_id))
        issue_row = c.fetchone()
        assert issue_row is not None
        assert issue_row[0] == 5
        assert issue_row[1] == 'Issued'

    def test_issue_ppe_insufficient_stock_fails_gracefully(self, client, db_conn):
        """Attempting to issue more items than available stock must fail and preserve existing stock."""
        c = db_conn.cursor()

        c.execute("""
            INSERT INTO items (item_name, category, unit, stock, min_stock)
            VALUES ('Integration Low Stock Goggles', 'Eye Protection', 'Nos', 2, 5)
            RETURNING id;
        """)
        item_id = c.fetchone()[0]

        c.execute("""
            INSERT INTO employees (emp_code, name, department, status)
            VALUES ('EMP-TEST-002', 'Low Stock Employee', 'Safety', 'Active')
            RETURNING id;
        """)
        emp_id = c.fetchone()[0]
        db_conn.commit()

        with client.session_transaction() as sess:
            sess['user'] = 'test_admin'
            sess['role'] = 'Admin'
            sess['full_name'] = 'Admin Test'
            sess['department'] = 'Safety'

        # Attempt to issue 10 items when only 2 exist
        response = client.post('/issues/add', data={
            'employee_id': str(emp_id),
            'item_id': str(item_id),
            'qty': 10,
            'issue_date': '2026-10-30'
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Insufficient stock' in response.data

        # Verify items.stock was untouched (still 2)
        c.execute("SELECT stock FROM items WHERE id=%s", (item_id,))
        stock_after = c.fetchone()[0]
        assert stock_after == 2

        # Verify no issue record was created
        c.execute("SELECT COUNT(*) FROM issue_register WHERE employee_id=%s AND item_id=%s", (emp_id, item_id))
        assert c.fetchone()[0] == 0

