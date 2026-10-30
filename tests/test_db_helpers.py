import pytest
from unittest.mock import MagicMock, patch
from database.db import fetchall, fetchone, get_database_url


class TestDatabaseHelpers:
    """Tests for database extraction and URL serialization utilities."""

    def test_fetchall_normal(self):
        cursor = MagicMock()
        cursor.description = [('id',), ('name',), ('department',)]
        cursor.fetchall.return_value = [
            (1, 'Alice', 'Electrical'),
            (2, 'Bob', 'Mechanical'),
        ]

        result = fetchall(cursor)
        assert len(result) == 2
        assert result[0] == {'id': 1, 'name': 'Alice', 'department': 'Electrical'}
        assert result[1] == {'id': 2, 'name': 'Bob', 'department': 'Mechanical'}

    def test_fetchall_empty(self):
        cursor = MagicMock()
        cursor.description = [('id',), ('item_name',)]
        cursor.fetchall.return_value = []

        result = fetchall(cursor)
        assert result == []

    def test_fetchone_normal(self):
        cursor = MagicMock()
        cursor.description = [('id',), ('stock',), ('unit',)]
        cursor.fetchone.return_value = (10, 45, 'Nos')

        result = fetchone(cursor)
        assert result == {'id': 10, 'stock': 45, 'unit': 'Nos'}

    def test_fetchone_no_row(self):
        cursor = MagicMock()
        cursor.description = [('id',), ('stock',)]
        cursor.fetchone.return_value = None

        result = fetchone(cursor)
        assert result is None

    def test_fetchone_none_description(self):
        cursor = MagicMock()
        cursor.description = None

        result = fetchone(cursor)
        assert result is None

    @patch('database.db.DB_CONFIG', {
        'user': 'test_user@domain',
        'password': 'p@ss/word+123#%',
        'host': '127.0.0.1',
        'port': '5432',
        'database': 'ppe_db'
    })
    def test_get_database_url_encodes_special_characters(self):
        url = get_database_url()
        # Verify user and password special chars are URL-encoded
        assert 'test_user%40domain' in url
        assert 'p%40ss%2Fword%2B123%23%25' in url
        assert '@127.0.0.1:5432/ppe_db' in url
        assert url.startswith('postgresql+psycopg2://')

