import pytest
import html
from flask import session
from unittest.mock import patch, MagicMock
from app import app
from modules.user_admin import get_user_dept_variants


class TestSecurityAuditRegressions:
    """Security regression tests verifying fixes for audit findings."""

    # ── Test 1: Unauthenticated Employee Search (SEC-03) ──
    def test_employees_search_requires_authentication(self):
        """Unauthenticated requests to /employees/search must be rejected with 401 or redirect to login."""
        with app.test_client() as client:
            resp = client.get('/employees/search?q=test')
            assert resp.status_code in (401, 302), f"Expected 401/302 but got {resp.status_code}"

    # ── Test 2: XSS in PDF/HTML Export (SEC-04) ──
    @patch('modules.reports.get_db')
    def test_reports_pdf_export_escapes_html_and_scripts(self, mock_get_db):
        """PDF/HTML report export must escape malicious script tags in query params and fields."""
        mock_cursor = MagicMock()
        mock_cursor.description = [('item_name',), ('total_qty',)]
        mock_cursor.fetchall.return_value = [{'item_name': '<img src=x onerror=alert(1)>', 'total_qty': 5}]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user'] = 'admin_user'
                sess['role'] = 'Admin'

            xss_payload = "<script>alert('xss')</script>"
            resp = client.get(f'/reports/export/pdf?from_date=2026-01-01&to_date={xss_payload}')
            assert resp.status_code == 200
            # Script tags must be escaped and not present as executable HTML tags
            assert b"<script>alert('xss')</script>" not in resp.data
            assert b"&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in resp.data or b"&lt;script&gt;alert('xss')&lt;/script&gt;" in resp.data

    # ── Test 3: IDOR Cross-Department Record Deletion (SEC-05) ──
    @patch('modules.issues.get_db')
    def test_issues_delete_blocks_cross_department_idor(self, mock_get_db):
        """A user assigned to Mechanical cannot delete an issue record belonging to Electrical."""
        mock_cursor = MagicMock()
        mock_cursor.description = [('id',), ('department',), ('qty',), ('item_id',)]
        # Record #50 belongs to Electrical
        mock_cursor.fetchone.return_value = {'id': 50, 'department': 'Electrical', 'qty': 5, 'item_id': 1}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user'] = 'mech_officer'
                sess['role'] = 'Safety Officer'
                sess['department'] = 'Mechanical'
                sess['assigned_departments'] = []

            with patch('modules.issues.has_permission', return_value=True):
                resp = client.post('/issues/delete/50', follow_redirects=True)
                # Verify that DELETE query was NOT executed
                executed_statements = [call[0][0] for call in mock_cursor.execute.call_args_list]
                delete_calls = [stmt for stmt in executed_statements if 'DELETE FROM issue_register' in stmt]
                assert len(delete_calls) == 0, "IDOR check failed: cross-department record was deleted!"

    @patch('modules.stock.get_db')
    def test_stock_delete_blocks_cross_department_idor(self, mock_get_db):
        """A user assigned to Mechanical cannot delete a stock receipt belonging to Electrical."""
        mock_cursor = MagicMock()
        mock_cursor.description = [('id',), ('department',), ('qty',), ('item_id',)]
        mock_cursor.fetchone.return_value = {'id': 88, 'department': 'Electrical', 'qty': 20, 'item_id': 2}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user'] = 'mech_officer'
                sess['role'] = 'Store Keeper'
                sess['department'] = 'Mechanical'
                sess['assigned_departments'] = []

            with patch('modules.stock.has_permission', return_value=True):
                resp = client.post('/stock/delete/88', follow_redirects=True)
                executed_statements = [call[0][0] for call in mock_cursor.execute.call_args_list]
                delete_calls = [stmt for stmt in executed_statements if 'DELETE FROM stock_receipts' in stmt]
                assert len(delete_calls) == 0, "IDOR check failed: cross-department stock receipt was deleted!"

    # ── Test 4: OTP Brute Force Rate Limiting (SEC-07) ──
    @patch('modules.password_reset.get_db')
    def test_otp_verification_locks_after_repeated_failures(self, mock_get_db):
        """Entering incorrect OTP repeatedly must trigger lockout and invalidate session."""
        mock_cursor = MagicMock()
        mock_cursor.description = [('id',), ('otp_code',), ('expires_at',), ('used',)]
        from datetime import datetime, timedelta
        mock_cursor.fetchone.return_value = (
            1, '654321', datetime.now() + timedelta(minutes=10), False
        )
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['reset_user_id'] = 10

            # Submit 5 incorrect attempts
            for i in range(5):
                resp = client.post('/verify-otp', data={'otp': '000000'}, follow_redirects=True)

            # 6th attempt should be blocked / locked out and redirected to forgot-password
            resp6 = client.post('/verify-otp', data={'otp': '654321'}, follow_redirects=False)
            assert resp6.status_code == 302
            assert '/forgot-password' in resp6.headers['Location']
            with client.session_transaction() as sess:
                assert 'reset_user_id' not in sess

    # ── Test 5: Whitespace-Only Department Normalization (BUG-01) ──
    def test_whitespace_department_variants_returns_none(self):
        """Whitespace-only departments must not produce empty strings in allowed departments list."""
        with app.test_request_context():
            session['role'] = 'Safety Officer'
            session['department'] = '   '
            session['assigned_departments'] = ['  ', '']
            assert get_user_dept_variants() is None
