import pytest
from unittest.mock import patch, MagicMock
from flask import session
from modules.user_admin import get_user_dept_variants, has_permission


class TestDepartmentVariants:
    """Tests for get_user_dept_variants() resolution and normalization."""

    def test_admin_returns_none(self, test_app):
        with test_app.test_request_context():
            session['role'] = 'Admin'
            session['department'] = 'Electrical'
            assert get_user_dept_variants() is None

    def test_super_admin_returns_none(self, test_app):
        with test_app.test_request_context():
            session['role'] = 'Super Admin'
            session['department'] = 'Marine'
            session['assigned_departments'] = ['Operations']
            assert get_user_dept_variants() is None

    def test_regular_user_single_department(self, test_app):
        with test_app.test_request_context():
            session['role'] = 'Safety Officer'
            session['department'] = 'Mechanical'
            session['assigned_departments'] = []
            assert get_user_dept_variants() == ['mechanical']

    def test_regular_user_multiple_assigned_departments_normalized(self, test_app):
        with test_app.test_request_context():
            session['role'] = 'Department User'
            session['department'] = ' Electrical '
            session['assigned_departments'] = ['OPERATIONS', 'electrical', '  Marine  ', '']
            result = get_user_dept_variants()
            assert result == ['electrical', 'operations', 'marine']

    def test_empty_session_returns_none(self, test_app):
        with test_app.test_request_context():
            session['role'] = 'Viewer'
            session['department'] = None
            session['assigned_departments'] = []
            assert get_user_dept_variants() is None

    def test_whitespace_only_department_behavior(self, test_app):
        """Documents current behavior: whitespace strings are stripped to '' and returned as [''].
        A defect fix is proposed to return None when all departments are whitespace."""
        with test_app.test_request_context():
            session['role'] = 'Viewer'
            session['department'] = '   '
            session['assigned_departments'] = ['  ']
            assert get_user_dept_variants() is None


class TestHasPermission:
    """Tests for has_permission() access control rules."""

    def test_admin_has_all_permissions(self, test_app):
        with test_app.test_request_context():
            session['role'] = 'Admin'
            assert has_permission('can_create') is True
            assert has_permission('can_edit') is True
            assert has_permission('can_delete') is True
            assert has_permission('can_view') is True
            assert has_permission('delete', module='employees') is True

    def test_super_admin_has_all_permissions(self, test_app):
        with test_app.test_request_context():
            session['role'] = 'Super Admin'
            assert has_permission('can_delete', module='stock') is True

    def test_can_view_action_defaults_to_true_for_general(self, test_app):
        with test_app.test_request_context():
            session['role'] = 'Viewer'
            assert has_permission('can_view') is True
            assert has_permission('view') is True

    @patch('modules.user_admin.get_db')
    def test_module_permission_allowed(self, mock_get_db, test_app):
        with test_app.test_request_context():
            session['role'] = 'Safety Officer'
            session['department'] = 'Safety'

            mock_cursor = MagicMock()
            mock_cursor.description = [('can_view',), ('can_create',), ('can_edit',), ('can_delete',)]
            mock_cursor.fetchone.return_value = (True, True, False, False)

            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_db.return_value = mock_conn

            assert has_permission('can_create', module='issues') is True
            assert has_permission('can_delete', module='issues') is False

    @patch('modules.user_admin.get_department_role_permissions')
    def test_department_role_permission_fallback(self, mock_dept_perms, test_app):
        with test_app.test_request_context():
            session['role'] = 'Store Keeper'
            session['department'] = 'Logistics'

            mock_dept_perms.return_value = {
                'Store Keeper': {'can_create': True, 'can_edit': True, 'can_delete': False}
            }

            assert has_permission('can_create') is True
            assert has_permission('can_delete') is False

    @patch('modules.user_admin.get_role_permissions')
    def test_global_role_permission_fallback_when_no_dept(self, mock_role_perms, test_app):
        with test_app.test_request_context():
            session['role'] = 'Viewer'
            session['department'] = None

            mock_role_perms.return_value = {
                'Viewer': {'can_create': False, 'can_edit': False, 'can_delete': False}
            }

            assert has_permission('can_create') is False
            assert has_permission('can_edit') is False
