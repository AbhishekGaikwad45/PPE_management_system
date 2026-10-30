import pytest
import psycopg2


class TestDatabaseTransactionsAndRollback:
    """Integration tests verifying database transaction integrity and rollback on failures."""

    def test_database_rollback_on_constraint_violation(self, db_conn):
        """Simulate a transaction error and verify rollback restores clean state."""
        c = db_conn.cursor()

        # Step 1: Insert item
        c.execute("""
            INSERT INTO items (item_name, category, unit, stock)
            VALUES ('Rollback Test Mask', 'Respiratory', 'Nos', 100)
            RETURNING id;
        """)
        item_id = c.fetchone()[0]
        db_conn.commit()

        # Step 2: Attempt a transaction that executes a valid update then an invalid insert
        try:
            c.execute("UPDATE items SET stock = stock - 20 WHERE id=%s", (item_id,))

            # Intentionally violate a NOT NULL or Foreign Key constraint
            # employee_id = 99999999 (does not exist in employees table)
            c.execute("""
                INSERT INTO issue_register (issue_date, employee_id, item_id, qty, status)
                VALUES ('2026-10-30', 99999999, %s, 20, 'Issued')
            """, (item_id,))

            db_conn.commit()
            pytest.fail("Expected ForeignKey / Constraint violation was not raised!")
        except Exception:
            db_conn.rollback()

        # Step 3: Verify the UPDATE was rolled back and stock remains 100
        c.execute("SELECT stock FROM items WHERE id=%s", (item_id,))
        final_stock = c.fetchone()[0]
        assert final_stock == 100

        # Verify no orphan issue record was saved
        c.execute("SELECT COUNT(*) FROM issue_register WHERE item_id=%s", (item_id,))
        assert c.fetchone()[0] == 0

    def test_cascade_and_relationship_integrity(self, db_conn):
        """Verify foreign key relationship between employees and issue_register."""
        c = db_conn.cursor()

        # Insert item and employee
        c.execute("""
            INSERT INTO items (item_name, category, unit, stock)
            VALUES ('FK Test Vest', 'Body', 'Nos', 50)
            RETURNING id;
        """)
        item_id = c.fetchone()[0]

        c.execute("""
            INSERT INTO employees (emp_code, name, department, status)
            VALUES ('EMP-FK-001', 'FK Test Employee', 'Logistics', 'Active')
            RETURNING id;
        """)
        emp_id = c.fetchone()[0]

        c.execute("""
            INSERT INTO issue_register (issue_date, employee_id, item_id, qty, status)
            VALUES ('2026-10-30', %s, %s, 1, 'Issued')
            RETURNING id;
        """, (emp_id, item_id))
        issue_id = c.fetchone()[0]
        db_conn.commit()

        # Verify issue_register links properly to both employee and item
        c.execute("""
            SELECT ir.id, e.emp_code, i.item_name
            FROM issue_register ir
            JOIN employees e ON ir.employee_id = e.id
            JOIN items i ON ir.item_id = i.id
            WHERE ir.id = %s
        """, (issue_id,))
        row = c.fetchone()
        assert row is not None
        assert row[1] == 'EMP-FK-001'
        assert row[2] == 'FK Test Vest'

