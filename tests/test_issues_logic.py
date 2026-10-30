import pytest
from unittest.mock import MagicMock
from modules.issues import find_issue_department


class TestFindIssueDepartment:
    """Unit tests for find_issue_department() stock deduction and allocation algorithm."""

    def test_employee_department_has_sufficient_stock(self):
        """When employee's department has balance >= qty, it must be selected first."""
        cur = MagicMock()
        cur.description = [('balance',)]
        cur.fetchone.return_value = (50,)

        result = find_issue_department(
            cur=cur,
            item_id=1,
            employee_department='Electrical',
            qty=10,
            user_dept='Mechanical',
            assigned_depts=['Marine'],
            is_admin=False
        )

        assert result == 'Electrical'
        assert cur.fetchone.call_count == 1

    def test_fallback_to_user_primary_department_when_employee_dept_insufficient(self):
        """When employee's department is insufficient, fallback to user's primary department."""
        cur = MagicMock()
        cur.description = [('balance',)]
        cur.fetchone.side_effect = [
            (5,),
            (20,)
        ]

        result = find_issue_department(
            cur=cur,
            item_id=1,
            employee_department='Electrical',
            qty=10,
            user_dept='Mechanical',
            assigned_depts=['Marine'],
            is_admin=False
        )

        assert result == 'Mechanical'
        assert cur.fetchone.call_count == 2

    def test_fallback_to_assigned_department_when_primary_insufficient(self):
        """When employee and user depts are insufficient, fallback to assigned departments."""
        cur = MagicMock()
        cur.description = [('balance',)]
        cur.fetchone.side_effect = [
            (0,),
            (2,),
            (15,)
        ]

        result = find_issue_department(
            cur=cur,
            item_id=1,
            employee_department='Electrical',
            qty=10,
            user_dept='Mechanical',
            assigned_depts=['Marine'],
            is_admin=False
        )

        assert result == 'Marine'
        assert cur.fetchone.call_count == 3

    def test_insufficient_stock_across_all_candidate_departments_returns_none(self):
        """When no candidate department has sufficient stock, return None."""
        cur = MagicMock()
        cur.description = [('balance',)]
        cur.fetchone.side_effect = [
            (2,),
            (4,),
            (1,)
        ]

        result = find_issue_department(
            cur=cur,
            item_id=1,
            employee_department='Electrical',
            qty=10,
            user_dept='Mechanical',
            assigned_depts=['Marine'],
            is_admin=False
        )

        assert result is None

    def test_admin_discovers_other_departments_with_stock(self):
        """Admin can discover any department holding stock receipts for item."""
        cur = MagicMock()

        def mock_execute(query, params=None):
            if "SELECT DISTINCT department" in query:
                cur.description = [('department',)]
            else:
                cur.description = [('balance',)]

        cur.execute.side_effect = mock_execute
        cur.fetchall.return_value = [('Logistics',)]
        cur.fetchone.side_effect = [
            (0,),    # Electrical balance: 0
            (100,)   # Logistics balance: 100 (sufficient)
        ]

        result = find_issue_department(
            cur=cur,
            item_id=5,
            employee_department='Electrical',
            qty=10,
            user_dept=None,
            assigned_depts=None,
            is_admin=True
        )

        assert result == 'Logistics'

    def test_duplicate_departments_are_deduplicated_case_insensitively(self):
        """Departments with different casing should not be queried multiple times."""
        cur = MagicMock()
        cur.description = [('balance',)]
        cur.fetchone.return_value = (0,)

        find_issue_department(
            cur=cur,
            item_id=1,
            employee_department='electrical',
            qty=10,
            user_dept='ELECTRICAL',
            assigned_depts=[' Electrical '],
            is_admin=False
        )

        assert cur.fetchone.call_count == 1

    def test_none_or_blank_departments_are_skipped(self):
        """None or empty string departments must not cause invalid queries."""
        cur = MagicMock()
        cur.description = [('balance',)]
        cur.fetchone.return_value = (10,)

        result = find_issue_department(
            cur=cur,
            item_id=1,
            employee_department=None,
            qty=5,
            user_dept='   ',
            assigned_depts=[None, '', '   ', 'Safety'],
            is_admin=False
        )

        assert result == 'Safety'
        assert cur.fetchone.call_count == 1
