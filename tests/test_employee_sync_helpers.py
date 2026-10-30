import pytest
from modules.employee_sync import _normalize, DEPARTMENT_ALIASES, VALID_CATEGORIES, FIELD_ALIASES


class TestEmployeeSyncHelpers:
    """Unit tests for employee sync normalization, field mapping, and validation rules."""

    def test_normalize_collapses_whitespace_and_uppercases(self):
        assert _normalize('  employee   name  ') == 'EMPLOYEE NAME'
        assert _normalize('john\t\tdoe') == 'JOHN DOE'
        assert _normalize('first\nsecond') == 'FIRST SECOND'

    def test_normalize_handles_none_and_empty(self):
        assert _normalize(None) == ''
        assert _normalize('') == ''
        assert _normalize('   ') == ''

    def test_department_aliases_mapping(self):
        assert DEPARTMENT_ALIASES.get('INFORMATION TECHNOLOGY') == 'IT'
        assert DEPARTMENT_ALIASES.get('HR & ADMIN') == 'HR/Admin'
        assert DEPARTMENT_ALIASES.get('HR AND ADMIN') == 'HR/Admin'
        assert DEPARTMENT_ALIASES.get('CIVIL & PROJECT') == 'Civil/Project'
        assert DEPARTMENT_ALIASES.get('ELECTRICAL OPERATIONS') == 'Electrical Operation'

    def test_valid_categories_membership(self):
        assert 'MBC' in VALID_CATEGORIES
        assert 'MANPOWER BASED' in VALID_CATEGORIES
        assert 'JBA' in VALID_CATEGORIES
        assert 'CONTRACTOR' not in VALID_CATEGORIES
        assert 'RANDOM' not in VALID_CATEGORIES

    def test_field_aliases_has_all_required_employee_fields(self):
        expected_fields = ['emp_code', 'name', 'department', 'designation', 'contractor', 'category', 'status']
        for field in expected_fields:
            assert field in FIELD_ALIASES
            assert len(FIELD_ALIASES[field]) >= 1

